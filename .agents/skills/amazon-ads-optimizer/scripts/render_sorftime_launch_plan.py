#!/usr/bin/env python3
"""Render Sorftime-backed launch/rebuild advertising plans."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
CAMPAIGN_FIELDS = ["RecordType", "Campaign", "AdGroup", "TargetingType", "DailyBudgetAUD", "BiddingStrategy", "Entity", "MatchType", "Target", "BidAUD", "State", "Evidence", "Notes"]
NEGATIVE_FIELDS = ["Scope", "NegativeMatchType", "Term", "Category", "Reason"]
DEFAULT_CORE_TERMS = ["book nook", "book nook kit", "book nook japanese", "booknook", "book nook kits australia", "miniature house kit"]
DEFAULT_LONGTAIL_TERMS = ["japanese book nook", "japanese garden book nook", "book nook alley", "book nook cat", "diy miniature house kit japanese", "book nook japan street", "book nook kit showa"]
DEFAULT_OBSERVATION_TERMS = ["3d puzzle", "3d puzzles for adults", "dollhouse", "wooden puzzle", "bookshelf decor", "adult craft"]
DEFAULT_RANKING_TERMS = ["book nook", "book nook kit", "book nook japanese"]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value: Any) -> str:
    return "A$0.00" if value is None else f"A${float(value):,.2f}"


def pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "BookNook"


def load_context(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def first_number(text: str, label: str) -> float | None:
    m = re.search(re.escape(label) + r"[:：]?\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


def parse_product_detail(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "")
    out: dict[str, Any] = {"raw": text}
    patterns = {
        "asin": r"产品ASIN码[:：](.+)",
        "parent_asin": r"父级ASIN码[:：](.+)",
        "title": r"标题[:：](.+)",
        "brand": r"品牌[:：](.+)",
        "category": r"所属大类[:：](.+)",
        "subcategory": r"所属细分类目[:：](.+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            out[key] = m.group(1).strip()
    for key, label in [("price", "价格"), ("rating", "星级"), ("review_count", "评论数"), ("fba_fee", "FBA费用"), ("gross_profit", "毛利"), ("gross_margin", "毛利率")]:
        out[key] = first_number(text, label)
    m = re.search(r"月销量[:：]月销量[:：]([0-9]+)", text)
    if m:
        out["monthly_sales"] = int(m.group(1))
    m = re.search(r"月销额[:：]月销额[:：]([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        out["monthly_revenue"] = float(m.group(1))
    return out


def parse_keyword_detail(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def parse_jsonish(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def ad_summary(conn: sqlite3.Connection, asin: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select sum(impressions), sum(clicks), sum(spend), sum(orders), sum(sales)
        from search_term_performance
        where asin=? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        """,
        (asin,),
    ).fetchone()
    impressions, clicks, spend, orders, sales = row or (0, 0, 0, 0, 0)
    spend = float(spend or 0)
    sales = float(sales or 0)
    clicks = int(clicks or 0)
    orders = int(orders or 0)
    return {"impressions": int(impressions or 0), "clicks": clicks, "spend": round(spend, 2), "orders": orders, "sales": round(sales, 2), "acos": round(spend / sales, 4) if sales else None, "cvr": round(orders / clicks, 4) if clicks else None}


def term_metrics(conn: sqlite3.Connection, asins: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in asins)
    rows = conn.execute(
        f"""
        select lower(trim(search_term)) term, min(search_term) display_term,
               sum(clicks) clicks, sum(spend) spend, sum(orders) orders, sum(sales) sales,
               group_concat(distinct asin) source_asins
        from search_term_performance
        where asin in ({placeholders}) and trim(search_term) <> ''
          and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        group by lower(trim(search_term))
        order by sales desc, orders desc, spend desc
        """,
        asins,
    ).fetchall()
    out = []
    for row in rows:
        spend = float(row["spend"] or 0)
        sales = float(row["sales"] or 0)
        clicks = int(row["clicks"] or 0)
        orders = int(row["orders"] or 0)
        out.append({"term": row["display_term"], "clicks": clicks, "spend": round(spend, 2), "orders": orders, "sales": round(sales, 2), "acos": round(spend / sales, 4) if sales else None, "source_asins": row["source_asins"] or ""})
    return out


def term_lookup(metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {m["term"].lower(): m for m in metrics}


def keyword_volume(context: dict[str, Any], keyword: str) -> tuple[int | None, str]:
    details = context.get("keyword_details", {})
    raw = details.get(keyword) or details.get(keyword.lower())
    data = parse_keyword_detail(raw)
    volume = data.get("月搜索量") or data.get("monthly_search_volume")
    season = data.get("词搜索量旺季") or data.get("季节性") or ""
    try:
        volume = int(str(volume).replace(",", "")) if volume not in (None, "") else None
    except ValueError:
        volume = None
    return volume, str(season or "")


def evidence_for(term: str, metrics_by_term: dict[str, dict[str, Any]], context: dict[str, Any]) -> str:
    bits = []
    m = metrics_by_term.get(term.lower())
    if m and m.get("orders", 0) > 0:
        bits.append(f"广告已出{m['orders']}单，ACOS {pct(m.get('acos'))}")
    volume, season = keyword_volume(context, term)
    if volume:
        bits.append(f"Sorftime月搜索量约{volume}")
    if season:
        bits.append(season)
    return "；".join(bits) or "Sorftime/广告数据相关，低价验证"


def bid_for(term: str, metrics_by_term: dict[str, dict[str, Any]], default: float, cap: float = 0.75) -> str:
    m = metrics_by_term.get(term.lower())
    if not m or not m.get("clicks"):
        return f"{default:.2f}"
    cpc = m["spend"] / max(m["clicks"], 1)
    if m.get("orders", 0) >= 2 and (m.get("acos") is not None and m["acos"] <= 0.2):
        return f"{min(cap, max(default, cpc * 1.15)):.2f}"
    return f"{min(cap, max(0.2, cpc)):.2f}"


def bid_for_context(term: str, metrics_by_term: dict[str, dict[str, Any]], context: dict[str, Any], default: float, cap: float = 0.75) -> str:
    overrides = context.get("bid_overrides") or {}
    raw = overrides.get(term) or overrides.get(term.lower())
    if raw not in (None, ""):
        return f"{float(raw):.2f}"
    return bid_for(term, metrics_by_term, default, cap)


def as_term_list(items: Any, defaults: list[str]) -> list[str]:
    if not items:
        return defaults[:]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            term = item.strip()
        elif isinstance(item, dict):
            term = str(item.get("term") or item.get("keyword") or item.get("target") or "").strip()
        else:
            term = str(item or "").strip()
        if term and term.lower() not in {x.lower() for x in out}:
            out.append(term)
    return out or defaults[:]


def route_variant(term: str, context: dict[str, Any]) -> str:
    rules = context.get("variant_routing_rules") or {}
    lower = term.lower()
    for asin, rule in rules.items():
        keywords = rule.get("keywords", []) if isinstance(rule, dict) else rule
        if any(str(k).lower() in lower for k in keywords):
            return asin
    if "garden" in lower or "sakura" in lower or "zen" in lower:
        return "B0FQNHGLPZ"
    asins = context.get("asins") or ["B0G4D6CQRQ"]
    return asins[0]


def campaign_slug(context: dict[str, Any]) -> str:
    return slug(context.get("parent_label") or context.get("theme_label") or "BookNook_Parent")


def budget_amount(context: dict[str, Any], key: str, default: str) -> str:
    budgets = context.get("budgets") or {}
    value = budgets.get(key, default)
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def row(record: str, campaign: str, ad_group: str = "", targeting: str = "Manual", budget: str = "", entity: str = "Keyword", match: str = "", target: str = "", bid: str = "", evidence: str = "", notes: str = "", strategy: str = "") -> dict[str, str]:
    return {"RecordType": record, "Campaign": campaign, "AdGroup": ad_group, "TargetingType": targeting, "DailyBudgetAUD": budget, "BiddingStrategy": strategy, "Entity": entity, "MatchType": match, "Target": target, "BidAUD": bid, "State": "enabled", "Evidence": evidence, "Notes": notes}


def build_campaigns(context: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, str]]:
    metrics_by = term_lookup(metrics)
    parent = campaign_slug(context)
    auto = f"SP_AUTO_Research_{parent}"
    exact = f"SP_EXACT_Core_{parent}"
    longtail = f"SP_PHRASE_Longtail_{parent}" if context.get("theme_longtail_terms") else "SP_PHRASE_Longtail_Japanese"
    observation = "SP_PHRASE_Observation_Generic"
    asin_test = "SP_PRODUCT_ASIN_Test_BookNook"
    ranking = "SP_RANKING_Push_Selected"
    rows: list[dict[str, str]] = []
    rows += [
        row("Campaign", auto, targeting="Auto", budget=budget_amount(context, "auto_research", "8.00"), entity="Campaign", evidence="低价自动探索；负责捞真实搜索词", notes="Close/Loose/Substitutes/Complements分开设置", strategy="Dynamic bids - down only"),
        row("AdGroup", auto, "AUTO_Research", "Auto", entity="Ad Group", bid="0.28", evidence="自动投放低价探索", notes="只承担发现，不承担放量"),
        row("AutoTarget", auto, "AUTO_Research", "Auto", entity="Product Targeting", match="close-match", target="close-match", bid="0.42", evidence="Close match最可能发现强相关搜索词", notes="7天后有订单词迁移Exact"),
        row("AutoTarget", auto, "AUTO_Research", "Auto", entity="Product Targeting", match="loose-match", target="loose-match", bid="0.25", evidence="Loose match只做低价发现", notes="错配词快速否定"),
        row("AutoTarget", auto, "AUTO_Research", "Auto", entity="Product Targeting", match="substitutes", target="substitutes", bid="0.30", evidence="竞品页低价测试", notes="优先观察CUTEBEE/Rolife等同类"),
        row("AutoTarget", auto, "AUTO_Research", "Auto", entity="Product Targeting", match="complements", target="complements", bid="0.18", evidence="Complements弱相关风险高", notes="若跑到家具/电子书/阅读灯，立即否定"),
        row("Campaign", exact, targeting="Manual", budget=budget_amount(context, "exact_core", "14.00"), entity="Campaign", evidence="核心强相关词集中控价", notes="不启用Top of Search溢价", strategy="Dynamic bids - down only"),
        row("AdGroup", exact, "EXACT_Core", entity="Ad Group", bid="0.45", evidence="Exact核心组", notes="按词设置独立起始竞价"),
    ]
    core_terms = as_term_list(context.get("core_terms"), DEFAULT_CORE_TERMS)
    for term in core_terms:
        rows.append(row("Keyword", exact, "EXACT_Core", match="exact", target=term, bid=bid_for_context(term, metrics_by, context, 0.45, 0.75), evidence=evidence_for(term, metrics_by, context), notes="核心词；若7-14天稳定出单可转Ranking Push"))
    longtail_terms = as_term_list(context.get("theme_longtail_terms"), DEFAULT_LONGTAIL_TERMS)
    longtail_ad_group = f"{parent}_Longtail" if context.get("theme_longtail_terms") else "Japanese_Scene_Longtail"
    rows += [row("Campaign", longtail, targeting="Manual", budget=budget_amount(context, "phrase_longtail", "8.00"), entity="Campaign", evidence="主题/场景长尾词", notes="按变体意图拆组", strategy="Dynamic bids - down only"), row("AdGroup", longtail, longtail_ad_group, entity="Ad Group", bid="0.35", evidence="长尾探索组", notes="主题意图分流")]
    for term in longtail_terms:
        target_asin = route_variant(term, context)
        rows.append(row("Keyword", longtail, longtail_ad_group, match="phrase", target=term, bid=bid_for_context(term, metrics_by, context, 0.35, 0.65), evidence=evidence_for(term, metrics_by, context), notes=f"场景长尾；优先承接 {target_asin}"))
    rows += [row("Campaign", observation, targeting="Manual", budget=budget_amount(context, "generic_observation", "3.00"), entity="Campaign", evidence="泛词低价观察", notes="只观察，不承担放量任务", strategy="Dynamic bids - down only"), row("AdGroup", observation, "Generic_Observation", entity="Ad Group", bid="0.25", evidence="低价观察组", notes="若只产生点击无单，快速降价")]
    for term in as_term_list(context.get("generic_observation_terms"), DEFAULT_OBSERVATION_TERMS):
        rows.append(row("Keyword", observation, "Generic_Observation", match="phrase", target=term, bid=bid_for_context(term, metrics_by, context, 0.25, 0.45), evidence=evidence_for(term, metrics_by, context), notes="泛相关词，控价观察"))
    rows += [row("Campaign", asin_test, targeting="Manual", budget=budget_amount(context, "asin_test", "4.00"), entity="Campaign", evidence="Sorftime搜索结果页竞品低价卡位", notes="评论/品牌壁垒强的只低价测试", strategy="Dynamic bids - down only"), row("AdGroup", asin_test, "ASIN_Test", entity="Ad Group", bid="0.25", evidence="ASIN定向组", notes="只投同品类书立/DIY miniature竞品")]
    competitor_asins: list[dict[str, Any]] = []
    for result_list in context.get("keyword_search_results", {}).values():
        parsed = parse_jsonish(result_list)
        if isinstance(parsed, list):
            competitor_asins.extend([x for x in parsed if isinstance(x, dict)])
    seen = set(context.get("asins", []))
    scan_limit = int(context.get("asin_test_scan_limit", 18))
    target_limit = int(context.get("asin_test_limit", 8))
    for item in competitor_asins[:scan_limit]:
        asin = item.get("ASIN") or item.get("asin")
        if not asin or asin in seen:
            continue
        seen.add(asin)
        brand = item.get("品牌") or item.get("brand") or ""
        sales = item.get("本产品月销量") or item.get("monthly_sales") or ""
        title = item.get("标题") or item.get("title") or ""
        rows.append(row("ProductTarget", asin_test, "ASIN_Test", match="asin", target=asin, bid="0.25", entity="Product Targeting", evidence=f"Sorftime自然位竞品；{brand}；月销量{sales}", notes=title[:80]))
        if len([r for r in rows if r["RecordType"] == "ProductTarget"]) >= target_limit:
            break
    rows += [row("Campaign", ranking, targeting="Manual", budget=budget_amount(context, "ranking_push", "5.00"), entity="Campaign", evidence="仅放已验证转化且搜索量值得推的词", notes="30天后按ACOS复盘", strategy="Dynamic bids - down only"), row("AdGroup", ranking, "Ranking_Selected", entity="Ad Group", bid="0.50", evidence="排名支持组", notes="不与利润词共预算")]
    for term in as_term_list(context.get("ranking_terms"), DEFAULT_RANKING_TERMS):
        rows.append(row("Keyword", ranking, "Ranking_Selected", match="exact", target=term, bid=bid_for_context(term, metrics_by, context, 0.5, 0.8), evidence=evidence_for(term, metrics_by, context), notes="仅在利润组稳定出单后开启"))
    return rows


def build_negatives(context: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, str]]:
    negatives = context.get("pre_negative_terms") or [
        ("All search campaigns", "negative phrase", "kindle", "电子书/阅读器", "电子书阅读器需求错配"),
        ("All search campaigns", "negative phrase", "ebook", "电子书/阅读器", "非实体书立/模型套件"),
        ("All search campaigns", "negative phrase", "reading light", "阅读灯", "阅读灯配件错配"),
        ("All search campaigns", "negative phrase", "bookshelf", "家具/书架", "书架家具流量过泛，保留bookshelf decor低价观察"),
        ("All search campaigns", "negative exact", "doll house", "真实玩具屋", "真实玩具屋/儿童玩具意图偏离DIY书立"),
        ("All search campaigns", "negative phrase", "furniture", "家具", "家具类错配"),
        ("All search campaigns", "negative phrase", "kids", "儿童玩具", "儿童玩具需求与成人DIY craft不一致"),
        ("All search campaigns", "negative phrase", "lego", "竞品/强品牌", "LEGO品牌强且价格/受众差异大；只允许ASIN低价测试"),
        ("Listing/backend only", "do not use in listing", "CUTEBEE", "竞品品牌词", "可广告测试，不能进入Listing/backend"),
        ("Listing/backend only", "do not use in listing", "Rolife", "竞品品牌词", "可广告测试，不能进入Listing/backend"),
        ("Listing/backend only", "do not use in listing", "LEGO", "竞品品牌词", "可广告测试，不能进入Listing/backend"),
    ]
    out = []
    for item in negatives:
        if isinstance(item, dict):
            out.append({
                "Scope": str(item.get("scope") or item.get("Scope") or "All search campaigns"),
                "NegativeMatchType": str(item.get("negative_match_type") or item.get("NegativeMatchType") or "negative phrase"),
                "Term": str(item.get("term") or item.get("Term") or ""),
                "Category": str(item.get("category") or item.get("Category") or "预否词"),
                "Reason": str(item.get("reason") or item.get("Reason") or "主题配置预否词"),
            })
        else:
            a, b, c, d, e = item
            out.append({"Scope": a, "NegativeMatchType": b, "Term": c, "Category": d, "Reason": e})
    wasted_clicks = int(context.get("waste_click_threshold", 20))
    wasted_spend = float(context.get("waste_spend_threshold", 8))
    for m in metrics:
        if m["orders"] == 0 and m["clicks"] >= wasted_clicks and m["spend"] >= wasted_spend:
            out.append({"Scope": "Current search campaigns", "NegativeMatchType": "negative exact", "Term": m["term"], "Category": "广告浪费词", "Reason": f"广告数据：{m['clicks']}点击无单，花费{money(m['spend'])}"})
    return out


def write_csv(path: str | Path, rows: list[dict[str, str]], fields: list[str]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return p


def render_html(plan: dict[str, Any]) -> str:
    campaign_rows = "".join(f"<tr><td>{esc(r['RecordType'])}</td><td>{esc(r['Campaign'])}</td><td>{esc(r['AdGroup'])}</td><td>{esc(r['MatchType'])}</td><td>{esc(r['Target'])}</td><td>{esc(r['BidAUD'])}</td><td>{esc(r['Evidence'])}</td><td>{esc(r['Notes'])}</td></tr>" for r in plan["campaigns"])
    neg_rows = "".join(f"<tr><td>{esc(r['Scope'])}</td><td>{esc(r['NegativeMatchType'])}</td><td>{esc(r['Term'])}</td><td>{esc(r['Category'])}</td><td>{esc(r['Reason'])}</td></tr>" for r in plan["pre_negatives"])
    budget_cards = "".join(f"<div class='card'><b>{esc(b['name'])}</b><br>{esc(b['budget'])}/天<br><span class='note'>{esc(b['note'])}</span></div>" for b in plan["budget_structure"])
    evidence_tags = "".join(f"<span class='tag'>{esc(x)}</span>" for x in plan["evidence_highlights"])
    files = plan["campaign_files"]
    summaries = "".join(f"<li>{esc(k)}：花费 {money(v['spend'])}，销售 {money(v['sales'])}，订单 {esc(v['orders'])}，ACOS {pct(v['acos'])}</li>" for k, v in plan["ad_summaries"].items())
    calibration_note = "共享手动组只作为共同关键词证据，不拆分到单个ASIN，避免花费/销售双算。" if plan.get("shared_id") else "本报告为单 ASIN 口径，手动与自动广告均归入该 ASIN，不涉及跨 ASIN 归因。"
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{esc(plan['title'])}</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fa;color:#17202a;line-height:1.55}}header{{background:#fff;border-bottom:1px solid #d9e0e8;padding:22px 30px}}main{{padding:22px 30px;max-width:1180px;margin:auto}}section{{background:#fff;border:1px solid #d9e0e8;border-radius:8px;padding:16px;margin:14px 0}}h1{{margin:0 0 8px}}h2{{margin:0 0 10px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}.card{{border:1px solid #dde5ee;border-radius:6px;padding:12px;background:#fbfcfe}}.tag{{display:inline-block;border:1px solid #b9c6d4;border-radius:999px;padding:3px 8px;margin:3px;background:#fff;font-size:12px}}table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff}}th,td{{border-bottom:1px solid #e5ebf1;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef3f8;position:sticky;top:0}}.note{{color:#52616f}}.warn{{border-left:4px solid #c2410c}}.ok{{border-left:4px solid #15803d}}.mono{{font-family:Consolas,monospace}}</style>
</head><body><header><h1>{esc(plan['title'])}</h1><div>Marketplace: Amazon AU | Product: {esc(plan.get('theme_label', 'Book Nook parent'))} | 目标：控亏测词 + 重建广告架构</div></header><main>
<section class=\"ok\"><h2>交付文件</h2><p>广告搭建CSV：<span class=\"mono\">{esc(files['campaign_build_csv'])}</span></p><p>预否词CSV：<span class=\"mono\">{esc(files['pre_negatives_csv'])}</span></p><p>结构化JSON：<span class=\"mono\">{esc(files['json_config'])}</span></p></section>
<section><h2>预算结构</h2><div class=\"grid\">{budget_cards}</div></section>
<section><h2>Sorftime证据摘要</h2>{evidence_tags}<p class=\"note\">Sorftime数据均为外部估算，不是Amazon Ads后台真实表现；最终升价、否词、扩量以后续广告报表为准。</p></section>
<section><h2>核心执行规则</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in plan['validation_rules'])}</ul></section>
<section><h2>广告数据校准说明</h2><ul>{summaries}</ul><p class=\"note\">{esc(calibration_note)}</p></section>
<section><h2>Campaign Build</h2><table><thead><tr><th>Record</th><th>Campaign</th><th>Ad Group</th><th>Match</th><th>Target</th><th>Bid</th><th>Evidence</th><th>Notes</th></tr></thead><tbody>{campaign_rows}</tbody></table></section>
<section class=\"warn\"><h2>Pre-Negatives</h2><table><thead><tr><th>Scope</th><th>Match</th><th>Term</th><th>Category</th><th>Reason</th></tr></thead><tbody>{neg_rows}</tbody></table></section>
</main></body></html>"""


def load_knowledge(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {
            "category": "Book Nook",
            "themes": [],
            "core_keywords": {},
            "competitor_brands": [],
            "long_term_pre_negatives": [],
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        data = {}
    data.setdefault("category", "Book Nook")
    data.setdefault("themes", [])
    data.setdefault("core_keywords", {})
    data.setdefault("competitor_brands", [])
    data.setdefault("long_term_pre_negatives", [])
    return sanitize_knowledge(data)


MOJIBAKE_MARKERS = ("骞垮憡", "鏍稿績", "宸插嚭", "鍗", "璇")


def sanitize_knowledge(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize_knowledge(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_knowledge(v) for v in value]
    if isinstance(value, str) and any(marker in value for marker in MOJIBAKE_MARKERS):
        return ""
    return value


def best_terms_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for campaign in plan.get("campaigns", []):
        target = str(campaign.get("Target") or "").strip()
        if not target or campaign.get("Entity") != "Keyword":
            continue
        evidence = str(campaign.get("Evidence") or "")
        if "广告已出" in evidence or campaign.get("MatchType") == "exact":
            terms.append({
                "term": target,
                "match_type": campaign.get("MatchType", ""),
                "evidence": evidence,
                "notes": campaign.get("Notes", ""),
            })
    return terms[:30]


def write_knowledge_base(plan: dict[str, Any], json_path: str | Path, md_path: str | Path) -> None:
    context = plan.get("sorftime_context", {})
    knowledge = sanitize_knowledge(load_knowledge(json_path))
    parent_asin = context.get("parent_asin")
    if not parent_asin:
        details = context.get("product_details", {})
        for detail in details.values():
            parsed = parse_product_detail(detail)
            parent_asin = parsed.get("parent_asin")
            if parent_asin:
                break
    parent_asin = parent_asin or plan.get("shared_id") or "-".join(plan.get("asins", []))
    theme_label = context.get("theme_label") or context.get("parent_label") or "BookNook_Parent"
    products = []
    for asin, raw_detail in (context.get("product_details") or {}).items():
        detail = parse_product_detail(raw_detail)
        products.append({
            "asin": asin,
            "title": detail.get("title", ""),
            "price": detail.get("price"),
            "rating": detail.get("rating"),
            "review_count": detail.get("review_count"),
            "monthly_sales": detail.get("monthly_sales"),
            "subcategory": detail.get("subcategory") or detail.get("category", ""),
        })
    theme_entry = {
        "parent_asin": parent_asin,
        "theme_label": theme_label,
        "asins": plan.get("asins", []),
        "shared_id": plan.get("shared_id"),
        "products": products,
        "ad_summaries": plan.get("ad_summaries", {}),
        "validated_terms": best_terms_from_plan(plan),
    }
    themes = [t for t in knowledge["themes"] if not (t.get("parent_asin") == parent_asin and t.get("theme_label") == theme_label)]
    themes.append(theme_entry)
    knowledge["themes"] = themes
    for keyword, raw in (context.get("keyword_details") or {}).items():
        parsed = parse_keyword_detail(raw)
        volume = parsed.get("月搜索量") or parsed.get("monthly_search_volume")
        season = parsed.get("词搜索量旺季") or parsed.get("season") or parsed.get("季节性")
        knowledge["core_keywords"][keyword] = {"monthly_search_volume": volume, "season": season}
    for brand in context.get("competitor_brands", []):
        if brand and brand not in knowledge["competitor_brands"]:
            knowledge["competitor_brands"].append(brand)
    for neg in plan.get("pre_negatives", []):
        term = str(neg.get("Term") or "").strip()
        if term and term not in knowledge["long_term_pre_negatives"]:
            knowledge["long_term_pre_negatives"].append(term)
    jp = Path(json_path)
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Book Nook 类目知识库",
        "",
        "## 类目格局",
        "Book Nook 在 Amazon AU 主要由大词 `book nook`、`book nook kit`、`booknook` 和泛相关 `miniature house kit` 承接。Sorftime 估算用于市场和竞品判断，Amazon Ads CSV 用于最终竞价、否词和扩量。",
        "",
        "## 已分析主题",
    ]
    for theme in knowledge["themes"]:
        lines.append(f"- {theme.get('theme_label')} / {theme.get('parent_asin')}：ASIN {', '.join(theme.get('asins', []))}")
    lines += ["", "## 核心关键词"]
    for keyword, info in knowledge["core_keywords"].items():
        lines.append(f"- {keyword}：月搜索量 {info.get('monthly_search_volume') or 'n/a'}；旺季 {info.get('season') or 'n/a'}")
    lines += ["", "## 竞品与 Listing 禁入品牌"]
    lines.append(", ".join(knowledge["competitor_brands"]) or "暂无")
    lines += ["", "## 长期预否词"]
    lines.append(", ".join(knowledge["long_term_pre_negatives"]) or "暂无")
    lines += ["", "## 常用广告架构模板", "- Auto Research、Exact Core、Phrase Longtail、Generic Observation、ASIN Test、Ranking Push。共享手动组只作为共同证据，不拆分双算。"]
    mp = Path(md_path)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_plan(db_path: str | Path, context: dict[str, Any], output_prefix: str, generated_at: str) -> dict[str, Any]:
    asins = context.get("asins") or ["B0G4D6CQRQ", "B0FQNHGLPZ"]
    shared_id = context.get("shared_id") if "shared_id" in context else "B0G4D6CQRQ-B0FQNHGLPZ"
    metric_ids = [*asins, shared_id] if shared_id else [*asins]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        metrics = term_metrics(conn, metric_ids)
        summaries = {asin: ad_summary(conn, asin) for asin in metric_ids}
    campaigns = build_campaigns(context, metrics)
    negatives = build_negatives(context, metrics)
    details = {asin: parse_product_detail(context.get("product_details", {}).get(asin, "")) for asin in asins}
    parent = campaign_slug(context)
    theme_name = context.get("theme_label") or parent
    evidence = []
    for asin, detail in details.items():
        if detail.get("monthly_sales"):
            evidence.append(f"{asin} Sorftime月销量约{detail['monthly_sales']}，细分类目{detail.get('subcategory', '')}")
        if detail.get("gross_margin"):
            evidence.append(f"{asin} 毛利率约{detail['gross_margin']}%，可承受控亏测词")
    for kw in ["book nook", "book nook kit", "booknook", "miniature house kit"]:
        volume, season = keyword_volume(context, kw)
        if volume:
            evidence.append(f"{kw} 月搜索量约{volume}；{season}")
    if not evidence:
        evidence = ["book nook类目词由Sorftime与广告数据共同校准", "广告数据用于最终竞价和否词判断"]
    base = Path(output_prefix)
    files = {
        "html_report": str(base.with_suffix(".html")),
        "campaign_build_csv": str(Path(str(base).replace("_launch_plan", "_campaign_build") + ".csv")),
        "pre_negatives_csv": str(Path(str(base).replace("_sorftime_launch_plan", "_pre_negatives") + ".csv")),
        "json_config": str(Path(str(base).replace("reports", "configs") + ".json")),
    }
    plan = {
        "title": f"{' + '.join(asins)} Sorftime扩展版广告执行方案",
        "asins": asins,
        "shared_id": shared_id,
        "marketplace": "AU",
        "generated_at": generated_at,
        "theme_label": theme_name,
        "objective": "控亏测词：用Sorftime确定市场/竞品/类目优先级，用广告数据校准竞价与否词",
        "budget_structure": [
            {"name": "Auto Research", "budget": f"A${budget_amount(context, 'auto_research', '8.00')}", "note": "捞真实搜索词"},
            {"name": "Exact Core", "budget": f"A${budget_amount(context, 'exact_core', '14.00')}", "note": "核心强相关词"},
            {"name": "Phrase Longtail", "budget": f"A${budget_amount(context, 'phrase_longtail', '8.00')}", "note": f"{theme_name}主题/场景长尾"},
            {"name": "Generic Observation", "budget": f"A${budget_amount(context, 'generic_observation', '3.00')}", "note": "泛词低价观察"},
            {"name": "ASIN Test", "budget": f"A${budget_amount(context, 'asin_test', '4.00')}", "note": "竞品低价卡位"},
            {"name": "Ranking Push", "budget": f"A${budget_amount(context, 'ranking_push', '5.00')}", "note": "仅放已验证词"},
        ],
        "evidence_highlights": evidence[:10],
        "validation_rules": [
            "上线不启用Top of Search溢价，所有活动使用 Dynamic bids - down only。",
            "7天后把有订单搜索词迁移Exact，并在来源广告组加否定Exact。",
            "14天看词级点击：相关词20点击无单且花费超过动态测试花费，降价或暂停。",
            "30天后仅对已出单、ACOS可控且Sorftime搜索量足够的词开Ranking Push。",
        ],
        "campaign_files": files,
        "campaigns": campaigns,
        "pre_negatives": negatives,
        "ad_summaries": summaries,
        "sorftime_context": context,
    }
    return plan


def write_outputs(plan: dict[str, Any]) -> None:
    files = plan["campaign_files"]
    write_csv(files["campaign_build_csv"], plan["campaigns"], CAMPAIGN_FIELDS)
    write_csv(files["pre_negatives_csv"], plan["pre_negatives"], NEGATIVE_FIELDS)
    json_path = Path(files["json_config"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = Path(files["html_report"])
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(plan), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Sorftime launch-plan style advertising files.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--context-json", required=True)
    parser.add_argument("--output-prefix", required=True, help="reports/<name>_launch_plan_YYYY-MM-DD without extension")
    parser.add_argument("--generated-at", default="2026-07-10")
    parser.add_argument("--knowledge-json")
    parser.add_argument("--knowledge-md")
    args = parser.parse_args()
    plan = build_plan(args.db, load_context(args.context_json), args.output_prefix, args.generated_at)
    write_outputs(plan)
    if args.knowledge_json and args.knowledge_md:
        write_knowledge_base(plan, args.knowledge_json, args.knowledge_md)
    print(json.dumps(plan["campaign_files"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

