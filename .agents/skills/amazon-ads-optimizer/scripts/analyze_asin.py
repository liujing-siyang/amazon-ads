#!/usr/bin/env python3
"""Generate evidence-backed Amazon Ads optimization recommendations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
ACTIVE_IMPORT_SQL = "import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)"

DEFAULT_RULE_PROFILE: dict[str, Any] = {
    "name": "default",
    "target_acos": 0.2,
    "wasted_click_threshold": 20,
    "wasted_spend_threshold": 5.0,
    "min_orders_to_scale": 2,
    "scale_acos_headroom": 0.75,
    "ranking_acos_tolerance": 2.0,
    "lookback_days": 0,
    "keyword_gap_min_token_length": 4,
}


def _load_script(name: str):
    script = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_schema(db_path: str | Path) -> None:
    _load_script("import_ad_reports").ensure_schema(db_path)


def _margin_model(model: dict[str, Any] | None, target_acos: float | None) -> dict[str, Any]:
    model = dict(model or {})
    selling_price = float(model.get("selling_price") or 0)
    cost = sum(float(model.get(k) or 0) for k in ["product_cost", "fba_fee", "referral_fee", "shipping_packaging", "return_allowance", "other_cost"])
    desired_profit_buffer = float(model.get("desired_profit_buffer") or 0)
    if selling_price > 0:
        break_even = max(0.0, (selling_price - cost) / selling_price)
        recommended = max(0.0, break_even - desired_profit_buffer)
        model.update({
            "selling_price": selling_price,
            "total_non_ad_cost": round(cost, 4),
            "break_even_acos": round(break_even, 4),
            "recommended_target_acos": round(recommended, 4),
            "gross_margin": round((selling_price - cost) / selling_price, 4),
            "profit_per_unit_before_ads": round(selling_price - cost, 4),
        })
        if target_acos is None:
            target_acos = recommended
    return {"model": model, "target_acos": target_acos}


def build_rule_profile(target_acos: float | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = dict(DEFAULT_RULE_PROFILE)
    overrides = dict(overrides or {})
    nested = overrides.get("rule_profile") if isinstance(overrides.get("rule_profile"), dict) else None
    if nested:
        overrides.update(nested)
    explicit_target = target_acos if target_acos is not None else overrides.get("target_acos")
    margin = _margin_model(overrides.get("margin_model"), explicit_target)
    if margin["target_acos"] is not None:
        profile["target_acos"] = margin["target_acos"]
    profile.update({k: v for k, v in overrides.items() if k not in {"margin_model", "rule_profile"}})
    profile["margin_model"] = margin["model"]
    profile["target_acos"] = float(profile["target_acos"])
    profile["wasted_click_threshold"] = int(profile.get("wasted_click_threshold", 20))
    profile["wasted_spend_threshold"] = float(profile.get("wasted_spend_threshold", 0) or 0)
    profile["min_orders_to_scale"] = int(profile["min_orders_to_scale"])
    profile["scale_acos_headroom"] = float(profile["scale_acos_headroom"])
    profile["ranking_acos_tolerance"] = float(profile["ranking_acos_tolerance"])
    profile["lookback_days"] = int(profile.get("lookback_days") or 0)
    profile["keyword_gap_min_token_length"] = int(profile["keyword_gap_min_token_length"])
    selling_price = profile["margin_model"].get("selling_price") or profile.get("average_order_value")
    if selling_price:
        profile["allowed_test_spend"] = round(float(selling_price) * profile["target_acos"], 4)
    elif profile.get("allowed_test_spend") is None:
        profile["allowed_test_spend"] = profile["wasted_spend_threshold"]
    if profile.get("avg_cpc") and profile.get("allowed_test_spend"):
        profile["estimated_test_clicks"] = round(float(profile["allowed_test_spend"]) / float(profile["avg_cpc"]), 2)
    if profile["target_acos"] <= 0:
        raise ValueError("target_acos must be a positive decimal, e.g. 0.2 for 20%")
    return profile


def _metric(row: sqlite3.Row) -> dict[str, Any]:
    spend = round(float(row["spend"] or 0), 2)
    sales = round(float(row["sales"] or 0), 2)
    clicks = int(row["clicks"] or 0)
    orders = int(row["orders"] or 0)
    return {
        "spend": spend,
        "sales": sales,
        "clicks": clicks,
        "orders": orders,
        "acos": round(spend / sales, 4) if sales else None,
        "cvr": round(orders / clicks, 4) if clicks else None,
    }


def _latest_listing_text(conn: sqlite3.Connection, asin: str) -> str:
    row = conn.execute(
        """
        select title, bullets_json from listing_snapshots
        where asin = ? order by captured_at desc, id desc limit 1
        """,
        (asin,),
    ).fetchone()
    if not row:
        return ""
    bullets = []
    if row["bullets_json"]:
        try:
            bullets = json.loads(row["bullets_json"])
        except json.JSONDecodeError:
            bullets = []
    return " ".join([row["title"] or "", *[str(b) for b in bullets]]).lower()


def _seller_evidence(conn: sqlite3.Connection, term: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select source_name, source_file, source_url, captured_date, cpc, search_volume,
               organic_rank, sponsored_rank, competition, confidence
        from external_keyword_evidence
        where lower(keyword) = lower(?) and source_type = 'sellersprite_excel'
        order by captured_date desc, id desc limit 1
        """,
        (term,),
    ).fetchone()
    return dict(row) if row else None


def _threshold_state(metrics: dict[str, Any], profile: dict[str, Any]) -> str:
    if metrics["acos"] is None:
        return "no_sales"
    if metrics["acos"] <= profile["target_acos"]:
        return "below_target"
    if metrics["acos"] <= profile["target_acos"] * profile["ranking_acos_tolerance"]:
        return "ranking_tolerance"
    return "above_tolerance"


def classify_intent(term: str, keyword: str, metrics: dict[str, Any], profile: dict[str, Any]) -> dict[str, str]:
    text = f"{term} {keyword}".lower()
    competitor_brands = set(profile.get("competitor_brands") or ["dreamwave", "hyundai", "somnifye", "kinglucky", "lenovo", "radox"])
    own_brands = set(profile.get("own_brands") or ["luvryon"])
    if any(b in text for b in own_brands):
        return {"intent": "defense", "intent_label_zh": "\u9632\u5b88\u8bcd"}
    if any(b in text for b in competitor_brands):
        return {"intent": "competitor", "intent_label_zh": "\u7ade\u54c1\u8bcd"}
    if metrics["orders"] > 0 and metrics["acos"] is not None and metrics["acos"] <= profile["target_acos"]:
        return {"intent": "profit", "intent_label_zh": "\u5229\u6da6\u8bcd"}
    if metrics["orders"] > 0:
        return {"intent": "ranking", "intent_label_zh": "\u6392\u540d\u8bcd"}
    if any(x in text for x in ["ipad", "tablet", "phone only"]):
        return {"intent": "irrelevant", "intent_label_zh": "\u65e0\u5173\u8bcd"}
    return {"intent": "exploration", "intent_label_zh": "\u63a2\u7d22\u8bcd"}


def _recommendations(conn: sqlite3.Connection, asin: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    perf = list(conn.execute(
        """
        select search_term, keyword, ad_mode,
               sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
               sum(orders) orders, sum(sales) sales
        from search_term_performance
        where asin = ? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        group by lower(search_term), keyword, ad_mode
        order by sales desc, spend desc
        """,
        (asin,),
    ))
    listing_text = _latest_listing_text(conn, asin)
    recs: list[dict[str, Any]] = []
    target_acos = profile["target_acos"]
    for row in perf:
        metrics = _metric(row)
        term = row["search_term"] or ""
        keyword = row["keyword"] or ""
        sellersprite = _seller_evidence(conn, term)
        source_refs = [{"type": "amazon_ads_csv", "asin": asin}]
        if sellersprite:
            source_refs.append({"type": "sellersprite_excel", "source_file": sellersprite.get("source_file")})
        threshold_state = _threshold_state(metrics, profile)
        intent_info = classify_intent(term, keyword, metrics, profile)

        def add(action: str, priority: str, reason: str, step: str, listing_gap_tokens: list[str] | None = None) -> None:
            recs.append({
                "action": action,
                "priority": priority,
                "search_term": term,
                "keyword": keyword,
                "ad_mode": row["ad_mode"],
                "reason": reason,
                "suggested_next_step": step,
                "threshold_state": threshold_state,
                **intent_info,
                "sellersprite_evidence": sellersprite,
                "listing_gap_tokens": listing_gap_tokens or [],
                "metric_evidence": metrics,
                "source_refs": source_refs,
            })

        if metrics["orders"] > 0 and metrics["acos"] is not None and metrics["acos"] <= target_acos:
            if row["ad_mode"] == "automatic" or keyword in {"close-match", "loose-match", "substitutes", "complements"}:
                add(
                    "promote_to_exact",
                    "high" if metrics["orders"] >= profile["min_orders_to_scale"] else "medium",
                    f"Search term converted below target ACOS {target_acos:.1%}; add as manual exact/phrase and monitor bid.",
                    "Add as manual exact keyword; optionally keep phrase for expansion.",
                )
        allowed_spend = float(profile.get("allowed_test_spend") or profile.get("wasted_spend_threshold") or 0)
        if metrics["orders"] == 0 and metrics["clicks"] >= profile["wasted_click_threshold"] and metrics["spend"] >= allowed_spend:
            add(
                "add_negative_or_reduce_bid",
                "high",
                "Spend and clicks reached the configured waste threshold with no orders; add negative if irrelevant, otherwise reduce bid.",
                "Check relevance; add negative exact/phrase for irrelevant terms or reduce bid for plausible terms.",
            )
        if metrics["orders"] >= profile["min_orders_to_scale"] and metrics["acos"] is not None and metrics["acos"] <= target_acos * profile["scale_acos_headroom"]:
            add(
                "increase_bid_or_budget",
                "medium",
                "Term has enough orders and ACOS headroom under the configured scaling threshold.",
                "Increase bid or budget cautiously and monitor 7-14 day ACOS movement.",
            )
        if metrics["orders"] > 0 and metrics["acos"] is not None and metrics["acos"] > target_acos:
            if metrics["acos"] <= target_acos * profile["ranking_acos_tolerance"]:
                add(
                    "ranking_support_review",
                    "medium",
                    "Term converts but is above target ACOS while still inside ranking-support tolerance.",
                    "Keep only if this term is strategically important for ranking or launch velocity.",
                )
            else:
                add(
                    "reduce_bid_for_high_acos",
                    "high",
                    "Term converts but exceeds the configured ranking-support ACOS tolerance.",
                    "Reduce bid or isolate into a lower-budget ranking test campaign.",
                )
        important_tokens = [token for token in term.lower().split() if len(token) >= profile["keyword_gap_min_token_length"]]
        missing = sorted(set(token for token in important_tokens if token not in listing_text))
        if metrics["orders"] > 0 and missing:
            add(
                "listing_keyword_gap",
                "medium",
                "Converted search term contains tokens missing from the latest scraped title/bullets: " + ", ".join(missing),
                "Review title, bullets, or backend search terms before increasing ad spend.",
                missing,
            )
    return recs


def _sources(conn: sqlite3.Connection, asin: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for row in conn.execute("select source_file, report_start, report_end, ad_mode, rows_imported from ad_report_imports where asin = ? and coalesce(is_active, 1)=1 order by id", (asin,)):
        sources.append({"type": "amazon_ads_csv", "label": row[0], "report_start": row[1], "report_end": row[2], "ad_mode": row[3], "rows": row[4]})
    for row in conn.execute("select product_url, captured_at, extraction_status from listing_snapshots where asin = ? order by id desc limit 1", (asin,)):
        sources.append({"type": "listing_snapshot", "label": row[0], "captured_at": row[1], "status": row[2]})
    count = conn.execute("select count(*) from external_keyword_evidence where source_type = 'sellersprite_excel'").fetchone()[0]
    if count:
        sources.append({"type": "sellersprite_excel", "label": f"{count} SellerSprite evidence rows"})
    try:
        sorftime_count = conn.execute("select count(*) from sorftime_snapshots where asin = ?", (asin,)).fetchone()[0]
        if sorftime_count:
            sources.append({"type": "sorftime_mcp", "label": f"{sorftime_count} Sorftime MCP snapshots"})
    except sqlite3.OperationalError:
        pass
    return sources


def _ad_structure_plan(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = {
        "automatic_exploration": {"title_zh": "\u81ea\u52a8\u63a2\u7d22", "terms": []},
        "manual_exact_core": {"title_zh": "\u624b\u52a8\u7cbe\u51c6\u6838\u5fc3\u8bcd", "terms": []},
        "manual_phrase_expansion": {"title_zh": "\u624b\u52a8\u8bcd\u7ec4\u6269\u5c55", "terms": []},
        "competitor_test": {"title_zh": "\u7ade\u54c1\u6d4b\u8bd5", "terms": []},
        "brand_defense": {"title_zh": "\u54c1\u724c\u9632\u5b88", "terms": []},
        "ranking_push": {"title_zh": "\u6392\u540d\u51b2\u523a", "terms": []},
    }
    for rec in recommendations:
        term = rec.get("search_term")
        if not term:
            continue
        intent = rec.get("intent")
        action = rec.get("action")
        if intent == "competitor":
            buckets["competitor_test"]["terms"].append(term)
        elif intent == "defense":
            buckets["brand_defense"]["terms"].append(term)
        elif action == "promote_to_exact" or intent == "profit":
            buckets["manual_exact_core"]["terms"].append(term)
        elif intent == "ranking":
            buckets["ranking_push"]["terms"].append(term)
        elif intent == "exploration":
            buckets["automatic_exploration"]["terms"].append(term)
    return [{"role": role, **data, "terms": sorted(set(data["terms"]))} for role, data in buckets.items() if data["terms"]]


def _trend_analysis(conn: sqlite3.Connection, asin: str) -> dict[str, Any]:
    periods = list(conn.execute("select report_start, report_end, sum(spend), sum(sales), sum(orders) from search_term_performance where asin=? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1) group by report_start, report_end order by report_start", (asin,)))
    if len(periods) < 2:
        return {"message_zh": "\u5f53\u524d\u5e7f\u544a\u6587\u4ef6\u53ea\u652f\u6301\u5468\u671f\u7ea7\u5bf9\u6bd4\uff0c\u4e0d\u80fd\u751f\u6210\u771f\u5b9e7/14/30\u5929\u8d8b\u52bf\u3002"}
    return {"message_zh": "\u5df2\u68c0\u6d4b\u5230\u591a\u4e2a\u5e7f\u544a\u5468\u671f\uff0c\u53ef\u8fdb\u884c\u5468\u671f\u7ea7\u8d8b\u52bf\u5bf9\u6bd4\u3002", "periods": [tuple(p) for p in periods]}


def _latest_listing(conn: sqlite3.Connection, asin: str) -> dict[str, Any]:
    row = conn.execute("select title, bullets_json, price, rating, review_count from listing_snapshots where asin=? order by captured_at desc, id desc limit 1", (asin,)).fetchone()
    if not row:
        return {"title": "", "bullets": [], "price": None, "rating": None, "review_count": None}
    try:
        bullets = json.loads(row["bullets_json"] or "[]")
    except json.JSONDecodeError:
        bullets = []
    return {"title": row["title"] or "", "bullets": bullets, "price": row["price"], "rating": row["rating"], "review_count": row["review_count"]}


def _listing_optimization(conn: sqlite3.Connection, asin: str, recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    listing = _latest_listing(conn, asin)
    converting_terms = []
    competitor_terms = []
    for rec in recommendations:
        m = rec.get("metric_evidence", {})
        term = rec.get("search_term") or ""
        if m.get("orders", 0) > 0:
            if rec.get("intent") == "competitor":
                competitor_terms.append(term)
            else:
                converting_terms.append(term)
    text = (listing["title"] + " " + " ".join(listing["bullets"])).lower()
    tokens = []
    for term in converting_terms:
        for token in term.lower().split():
            if len(token) >= 4 and token not in {"with", "for", "speaker", "speakers"} and token not in tokens:
                tokens.append(token)
    covered = [t for t in tokens if t in text]
    missing = [t for t in tokens if t not in text]
    score = 50 + min(25, len(covered) * 5) + (10 if (listing.get("rating") or 0) >= 4.3 else 0) + (10 if (listing.get("review_count") or 0) >= 100 else 0) + (5 if listing.get("title") else 0)
    score = min(100, score)
    product_signal = " ".join([listing["title"], *listing["bullets"], *converting_terms]).lower()
    is_book_nook = any(signal in product_signal for signal in ["book nook", "miniature", "3d puzzle", "wooden puzzle", "japanese", "showa", "alley"])
    if is_book_nook:
        title = "Book Nook Kit - Japanese Showa Street DIY Miniature House with LED Light, Dust Cover, 3D Wooden Puzzle Alley Waiting for the Cat, Craft Kit for Adults and Teens"
        bullets = [
            "Japanese alley atmosphere: recreate a nostalgic Showa street scene with izakaya details, cat figures and warm LED light for immersive bookshelf decor.",
            "Rewarding DIY miniature build: 280 precision-cut wooden pieces create a hands-on 3D puzzle project for adults, teens, beginners and hobby crafters.",
            "Dust cover included: protect the finished book nook from dust while keeping the tiny street, shop signs and sakura details clear on display.",
            "Gift-ready craft kit: a thoughtful choice for Japan lovers, cat enthusiasts, miniature collectors and anyone who enjoys mindful screen-free making.",
            "Designed for shelf display: the compact book nook alley fits between novels and adds a glowing decorative scene to libraries, desks and reading corners.",
        ]
        description = "Build a quiet Japanese street scene for your bookshelf with the Alley Waiting for the Cat book nook kit. The DIY miniature house combines laser-cut wooden pieces, warm LED lighting, a protective dust cover and detailed Showa-inspired storefronts to create a satisfying craft project and a display-ready bookshelf insert for adults and teens."
        rationale_terms = "book nook / book nook japanese / japanese book nook / 3d puzzle"
    else:
        title_terms = "Portable " if "portable" in missing else ""
        title = f"Bluetooth Pillow Speaker for Sleeping - {title_terms}Ultra Thin Under Pillow Speaker with White Noise, Sleep Timer, USB-C, for Side Sleepers, ASMR, Podcasts and Audiobooks"
        bullets = [
            "Ultra-thin comfort for side sleepers: the flat under pillow speaker fits beneath your pillow for private bedtime audio without earbuds or headbands.",
            "Bluetooth sleep audio plus built-in white noise: stream podcasts, ASMR and audiobooks, or switch to calming nature sounds for a steady sleep routine.",
            "Sleep timer and all-night battery: choose 30, 60 or 90 minutes and enjoy up to 10 hours of playback with convenient USB-C charging.",
            "Portable bedtime speaker for home and travel: lightweight design works in bedrooms, hotels and guest rooms without disturbing your routine.",
            "Shared-bed friendly and hygienic: keeps audio close under the pillow while avoiding sweaty headbands and uncomfortable in-ear headphones.",
        ]
        description = "Designed for side sleepers and quiet bedtime listening, this Bluetooth pillow speaker sits under your pillow to deliver podcasts, ASMR, audiobooks and soothing white noise without wearing earbuds. The ultra-thin body, sleep timer and USB-C rechargeable battery make it practical for nightly use at home or while travelling."
        rationale_terms = "pillow speaker / under pillow speaker / sleep speaker"
    backend = []
    for term in converting_terms:
        if term not in backend and not any(b in term.lower() for b in ["dreamwave", "hyundai", "somnifye", "kinglucky", "lenovo", "radox"]):
            backend.append(term)
    for token in missing:
        if token not in " ".join(backend).lower():
            backend.append(token)
    return {
        "score": score,
        "covered_tokens": covered,
        "missing_tokens": missing,
        "competitor_terms_excluded": sorted(set(competitor_terms)),
        "title": title,
        "bullets": bullets,
        "description": description,
        "backend_search_terms": backend[:20],
        "rationale_zh": f"\u4e2d\u6587\u89e3\u8bfb\uff1a\u6839\u636e\u5df2\u8f6c\u5316\u641c\u7d22\u8bcd\u63d0\u70bc {rationale_terms} \u7b49\u4e3b\u8bcd\uff0c\u4f18\u5148\u8865\u8db3\u6807\u9898\u3001\u4e94\u70b9\u548c\u540e\u53f0\u8bcd\uff0c\u63d0\u9ad8Listing\u627f\u63a5\u6548\u7387\u3002",
    }


def _sorftime_context(conn: sqlite3.Connection, asin: str) -> dict[str, Any]:
    rows = list(conn.execute(
        """
        select metric_type, query_date, payload_json
        from sorftime_snapshots
        where asin=? and coalesce(is_active, 1)=1
        order by query_date desc, id desc
        """,
        (asin,),
    ))
    context: dict[str, Any] = {"query_date": None, "metrics": {}}
    for row in rows:
        metric_type = row["metric_type"]
        if metric_type in context["metrics"]:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {"raw": row["payload_json"]}
        context["metrics"][metric_type] = payload
        context["query_date"] = context["query_date"] or row["query_date"]
    return context

def analyze(
    db_path: str | Path,
    asin: str,
    target_acos: float | None = None,
    persist: bool = False,
    rule_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_schema(db_path)
    profile = build_rule_profile(target_acos, rule_overrides)
    asin = asin.upper()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        summary_row = conn.execute(
            """
            select sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
                   sum(orders) orders, sum(sales) sales
            from search_term_performance
            where asin = ? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
            """,
            (asin,),
        ).fetchone()
        summary = _metric(summary_row)
        summary["impressions"] = int(summary_row["impressions"] or 0)
        summary["target_acos"] = profile["target_acos"]
        if not profile.get("margin_model", {}).get("selling_price") and summary.get("orders"):
            aov = summary["sales"] / summary["orders"] if summary["orders"] else 0
            profile["average_order_value"] = round(aov, 4)
            profile["allowed_test_spend"] = round(aov * profile["target_acos"], 4)
        recs = _recommendations(conn, asin, profile)
        evidence_validation = _load_script("validate_evidence").validate_database(db_path)
        sources = _sources(conn, asin)
        ad_structure_plan = _ad_structure_plan(recs)
        trend_analysis = _trend_analysis(conn, asin)
        listing_optimization = _listing_optimization(conn, asin, recs)
        sorftime_context = _sorftime_context(conn, asin)
        if persist:
            generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            cur = conn.execute(
                """
                insert into analysis_runs (asin, profile_name, generated_at, config_json, summary_json)
                values (?, ?, ?, ?, ?)
                """,
                (asin, profile["name"], generated_at, json.dumps(profile, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)),
            )
            run_id = cur.lastrowid
            for rec in recs:
                refs = list(rec["source_refs"]) + [{"type": "analysis_run", "id": run_id}]
                conn.execute(
                    """
                    insert into recommendations
                    (asin, generated_at, action, priority, search_term, keyword, reason,
                     metric_evidence_json, source_refs_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asin,
                        generated_at,
                        rec["action"],
                        rec["priority"],
                        rec.get("search_term"),
                        rec.get("keyword"),
                        rec["reason"],
                        json.dumps(rec["metric_evidence"], ensure_ascii=False),
                        json.dumps(refs, ensure_ascii=False),
                    ),
                )
    return {
        "asin": asin,
        "summary": summary,
        "rule_profile": profile,
        "margin_model": profile.get("margin_model", {}),
        "trend_analysis": trend_analysis,
        "ad_structure_plan": ad_structure_plan,
        "listing_optimization": listing_optimization,
        "sorftime_context": sorftime_context,
        "evidence_validation": evidence_validation,
        "sources": sources,
        "recommendations": recs,
    }


def analyze_from_config(config_path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    db = config.get("db") or DEFAULT_DB
    asin = config["asin"]
    target_acos = config.get("target_acos")
    rule_profile = config.get("rule_profile") or {}
    if "target_acos" in rule_profile and target_acos is None:
        target_acos = rule_profile["target_acos"]
    return analyze(db, asin, target_acos, persist=bool(config.get("persist")), rule_overrides=rule_profile)


def render_markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        f"# Amazon Ads Optimization Report - {result['asin']}",
        "",
        f"Spend: AUD {s['spend']:.2f} | Sales: AUD {s['sales']:.2f} | Orders: {s['orders']} | ACOS: {s['acos'] if s['acos'] is not None else 'n/a'}",
        "",
        "## Recommendations",
    ]
    for rec in result["recommendations"]:
        lines.append(f"- [{rec['priority']}] {rec['action']} - {rec['search_term']}: {rec['reason']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze imported Amazon Ads data for one ASIN.")
    parser.add_argument("asin", nargs="?")
    parser.add_argument("--target-acos", type=float, help="Decimal target ACOS, e.g. 0.2")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config", help="Path to analysis-config.json")
    parser.add_argument("--html-output", help="Write an interactive HTML report to this path")
    parser.add_argument("--rule-profile-json", help="Inline JSON rule overrides")
    args = parser.parse_args()

    if args.config:
        result = analyze_from_config(args.config)
    else:
        if not args.asin:
            parser.error("asin is required unless --config is provided")
        overrides = json.loads(args.rule_profile_json) if args.rule_profile_json else None
        result = analyze(args.db, args.asin.upper(), args.target_acos, persist=args.persist, rule_overrides=overrides)

    if args.html_output:
        renderer = _load_script("render_html_report")
        renderer.write_html_report(result, args.html_output)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_markdown(result))


if __name__ == "__main__":
    main()
