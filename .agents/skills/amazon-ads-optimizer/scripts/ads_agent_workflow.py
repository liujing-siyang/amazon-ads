#!/usr/bin/env python3
"""Persist ASIN-scoped agent evidence packs and middle files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data"


def _load_script(name: str):
    script = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def checksum(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def make_run_id(scope_id: str, generated_at: str | None = None) -> str:
    stamp = (generated_at or utc_now()).replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    return f"{scope_id}_{stamp}"


def ensure_data_pack(output_root: str | Path, asins: list[str], scope_id: str, shared_id: str | None = None) -> dict[str, Any]:
    root = Path(output_root)
    asin_dirs: dict[str, dict[str, str]] = {}
    for asin in asins:
        base = root / "asins" / asin
        paths = {
            "raw_uploads": base / "raw" / "uploads",
            "raw_sorftime": base / "raw" / "sorftime",
            "raw_web": base / "raw" / "web",
            "intermediate": base / "intermediate",
            "corrections": base / "corrections",
            "reports": base / "reports",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        asin_dirs[asin] = {k: str(v) for k, v in paths.items()}
    scope_base = root / "scopes" / scope_id
    scope_paths = {
        "members": scope_base / "members.json",
        "shared_ad_reports": scope_base / "shared_ad_reports",
        "intermediate": scope_base / "intermediate",
        "reports": scope_base / "reports",
    }
    for key, path in scope_paths.items():
        if key != "members":
            path.mkdir(parents=True, exist_ok=True)
    write_json(scope_paths["members"], {"scope_id": scope_id, "shared_id": shared_id, "asins": asins})
    return {"asins": asin_dirs, "scope": {k: str(v) for k, v in scope_paths.items()}}


def active_sources(conn: sqlite3.Connection, asins: list[str], scope_id: str, shared_id: str | None = None) -> list[dict[str, Any]]:
    ids = [*asins]
    if shared_id:
        ids.append(shared_id)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        select id, scope_id, asin, marketplace, source_type, source_name, source_file, source_url,
               checksum, captured_at, version, metadata_json
        from evidence_sources
        where coalesce(is_active, 1)=1
          and (scope_id = ? or asin in ({placeholders}))
        order by captured_at desc, id desc
        """,
        [scope_id, *ids],
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        out.append(item)
    return out


def normalized_ad_terms(conn: sqlite3.Connection, asins: list[str], shared_id: str | None = None) -> list[dict[str, Any]]:
    ids = [*asins]
    if shared_id:
        ids.append(shared_id)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        select asin, report_start, report_end, ad_mode, lower(trim(search_term)) term_key,
               min(search_term) search_term, min(keyword) keyword,
               sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
               sum(orders) orders, sum(sales) sales
        from search_term_performance
        where asin in ({placeholders})
          and trim(search_term) <> ''
          and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        group by asin, report_start, report_end, ad_mode, lower(trim(search_term))
        order by sales desc, orders desc, spend desc
        """,
        ids,
    ).fetchall()
    out = []
    for row in rows:
        spend = round(float(row["spend"] or 0), 2)
        sales = round(float(row["sales"] or 0), 2)
        clicks = int(row["clicks"] or 0)
        orders = int(row["orders"] or 0)
        out.append({
            "scope": "shared" if shared_id and row["asin"] == shared_id else "asin",
            "asin": row["asin"],
            "report_start": row["report_start"],
            "report_end": row["report_end"],
            "ad_mode": row["ad_mode"],
            "search_term": row["search_term"],
            "keyword": row["keyword"],
            "impressions": int(row["impressions"] or 0),
            "clicks": clicks,
            "spend": spend,
            "orders": orders,
            "sales": sales,
            "acos": round(spend / sales, 4) if sales else None,
            "cvr": round(orders / clicks, 4) if clicks else None,
        })
    return out


def build_opportunity_map(terms: list[dict[str, Any]], target_acos: float = 0.2, waste_clicks: int = 20) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "profit_terms": [],
        "ranking_terms": [],
        "exploration_terms": [],
        "competitor_terms": [],
        "negative_candidates": [],
    }
    competitor_tokens = {"cutebee", "rolife", "lego", "dreamwave", "histrips", "onyx", "fitsleeps"}
    for term in terms:
        text = f"{term.get('search_term', '')} {term.get('keyword', '')}".lower()
        compact = {
            "search_term": term["search_term"],
            "asin": term["asin"],
            "scope": term["scope"],
            "orders": term["orders"],
            "clicks": term["clicks"],
            "spend": term["spend"],
            "sales": term["sales"],
            "acos": term["acos"],
        }
        if any(token in text for token in competitor_tokens):
            buckets["competitor_terms"].append(compact)
        if term["orders"] > 0 and term["acos"] is not None and term["acos"] <= target_acos:
            buckets["profit_terms"].append(compact)
        elif term["orders"] > 0:
            buckets["ranking_terms"].append(compact)
        elif term["clicks"] >= waste_clicks:
            buckets["negative_candidates"].append(compact)
        else:
            buckets["exploration_terms"].append(compact)
    return buckets


def route_variants(
    terms: list[dict[str, Any]],
    asins: list[str],
    shared_id: str | None,
    variant_routing_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = variant_routing_rules or {}
    routes = []
    for term in terms:
        lower = str(term.get("search_term") or "").lower()
        recommended = None
        reason = ""
        for asin, rule in rules.items():
            keywords = rule.get("keywords", []) if isinstance(rule, dict) else rule
            if any(str(keyword).lower() in lower for keyword in keywords):
                recommended = asin
                reason = "matched_variant_keyword_rule"
                break
        if not recommended and term.get("scope") == "asin" and term.get("asin") in asins:
            recommended = term["asin"]
            reason = "single_asin_ad_evidence"
        if not recommended:
            recommended = shared_id or "scope"
            reason = "keep_in_variant_group_scope"
        routes.append({
            "search_term": term["search_term"],
            "source_asin": term["asin"],
            "recommended_asin": recommended,
            "reason": reason,
            "orders": term["orders"],
            "acos": term["acos"],
        })
    return {"asins": asins, "shared_id": shared_id, "routes": routes}


def build_decision_log(opportunities: dict[str, list[dict[str, Any]]], evidence_sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rules": [
            "Amazon Ads CSV is required for bid, budget, negative, and promotion decisions.",
            "Sorftime, web, and external keyword tools are market context only and cannot directly trigger bid scaling.",
            "Shared campaign groups remain in variant_group scope unless evidence or explicit routing rules select one ASIN.",
            "Only active evidence source versions are used in default analysis.",
        ],
        "evidence_source_ids": [s["id"] for s in evidence_sources],
        "decisions": [
            {"bucket": bucket, "count": len(items), "terms": items}
            for bucket, items in opportunities.items()
        ],
    }


def record_artifacts(conn: sqlite3.Connection, scope_id: str, files: dict[str, str], run_id: int | None = None) -> None:
    for artifact_type, path in files.items():
        conn.execute(
            """
            insert into analysis_artifacts
            (run_id, scope_id, artifact_type, artifact_path, checksum, metadata_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                scope_id,
                artifact_type,
                str(path),
                checksum(path),
                json.dumps({"generated_by": "ads_agent_workflow"}, ensure_ascii=False),
            ),
        )


def run_agent_workflow(
    db_path: str | Path,
    *,
    scope_id: str,
    asins: list[str],
    shared_id: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    marketplace: str = "AU",
    parent_asin: str | None = None,
    variant_routing_rules: dict[str, Any] | None = None,
    sorftime_context: dict[str, Any] | None = None,
    target_acos: float = 0.2,
    generated_at: str | None = None,
) -> dict[str, Any]:
    importer = _load_script("import_ad_reports")
    importer.ensure_schema(db_path)
    asins = [asin.upper() for asin in asins]
    shared_id = shared_id.upper() if shared_id else None
    generated_at = generated_at or utc_now()
    run_slug = make_run_id(scope_id, generated_at)
    data_pack = ensure_data_pack(output_root, asins, scope_id, shared_id)
    intermediate_dir = Path(data_pack["scope"]["intermediate"]) / run_slug
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        importer.register_scope(
            conn,
            scope_id=scope_id,
            scope_type="variant_group" if len(asins) >= 2 else "single",
            marketplace=marketplace,
            parent_asin=parent_asin,
            member_asins=asins,
            shared_ad_group_id=shared_id,
        )
        evidence = active_sources(conn, asins, scope_id, shared_id)
        terms = normalized_ad_terms(conn, asins, shared_id)
        opportunities = build_opportunity_map(terms, target_acos=target_acos)
        routes = route_variants(terms, asins, shared_id, variant_routing_rules)
        decision_log = build_decision_log(opportunities, evidence)

        files = {
            "evidence_index": str(write_json(intermediate_dir / "evidence_index.json", {"scope_id": scope_id, "sources": evidence})),
            "normalized_ad_terms": str(write_json(intermediate_dir / "normalized_ad_terms.json", {"scope_id": scope_id, "terms": terms})),
            "sorftime_context": str(write_json(intermediate_dir / "sorftime_context.json", sorftime_context or {})),
            "opportunity_map": str(write_json(intermediate_dir / "opportunity_map.json", opportunities)),
            "variant_routing_map": str(write_json(intermediate_dir / "variant_routing_map.json", routes)),
            "decision_log": str(write_json(intermediate_dir / "decision_log.json", decision_log)),
        }
        record_artifacts(conn, scope_id, files)
    return {"scope_id": scope_id, "asins": asins, "shared_id": shared_id, "data_pack": data_pack, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create ASIN/scope data packs and middle files for Amazon Ads optimization.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--asin", action="append", required=True)
    parser.add_argument("--shared-id")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--marketplace", default="AU")
    parser.add_argument("--target-acos", type=float, default=0.2)
    parser.add_argument("--routing-json", help="JSON file containing variant_routing_rules")
    parser.add_argument("--sorftime-context-json", help="JSON file containing Sorftime context")
    args = parser.parse_args()
    routing = json.loads(Path(args.routing_json).read_text(encoding="utf-8-sig")) if args.routing_json else None
    sorftime = json.loads(Path(args.sorftime_context_json).read_text(encoding="utf-8-sig")) if args.sorftime_context_json else None
    result = run_agent_workflow(
        args.db,
        scope_id=args.scope_id,
        asins=args.asin,
        shared_id=args.shared_id,
        output_root=args.output_root,
        marketplace=args.marketplace,
        target_acos=args.target_acos,
        variant_routing_rules=routing,
        sorftime_context=sorftime,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
