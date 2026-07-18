#!/usr/bin/env python3
"""Book Nook specific Amazon Ads optimization facade.

This module keeps Book Nook defaults, category knowledge, scope evidence packs,
and Sorftime launch-plan outputs behind one stable entry point.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data"
DEFAULT_KNOWLEDGE_JSON = Path(__file__).resolve().parents[4] / "configs" / "book_nook_category_knowledge.json"
DEFAULT_KNOWLEDGE_MD = Path(__file__).resolve().parents[4] / "reports" / "book_nook_category_knowledge.md"

DEFAULT_CORE_TERMS = ["book nook", "book nook kit", "booknook"]
DEFAULT_GENERIC_OBSERVATION_TERMS = [
    "miniature house kit",
    "3d wooden puzzle",
    "3d puzzles for adults",
    "bookshelf decor",
    "adult craft",
]
DEFAULT_BUDGETS = {
    "auto_research": "8.00",
    "exact_core": "14.00",
    "phrase_longtail": "8.00",
    "generic_observation": "3.00",
    "asin_test": "4.00",
    "ranking_push": "5.00",
}

DEFAULT_PRE_NEGATIVES = [
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "kindle", "category": "电子书/阅读器", "reason": "电子书或阅读器需求错误，不是实体 DIY Book Nook"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "ebook", "category": "电子书/阅读器", "reason": "非实体 DIY 书立套件需求"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "reading light", "category": "阅读灯", "reason": "阅读灯配件需求与 Book Nook 套件不一致"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "book light", "category": "阅读灯", "reason": "阅读灯配件需求与 Book Nook 套件不一致"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "furniture", "category": "家具", "reason": "家具需求偏离 DIY 书立场景"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "bookcase", "category": "家具/书架", "reason": "真实书柜家具需求错误"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "colouring book", "category": "图书", "reason": "涂色书需求错误"},
    {"scope": "All search campaigns", "negative_match_type": "negative phrase", "term": "kids", "category": "错误人群", "reason": "儿童玩具需求与成人 DIY craft 不一致"},
    {"scope": "All search campaigns", "negative_match_type": "negative exact", "term": "doll house", "category": "真实玩具屋", "reason": "真实玩具屋意图偏离 Book Nook"},
    {"scope": "Listing/backend only", "negative_match_type": "do not use in listing", "term": "CUTEBEE", "category": "竞品品牌词", "reason": "可低价广告测试，但不能进入 Listing/backend"},
    {"scope": "Listing/backend only", "negative_match_type": "do not use in listing", "term": "Rolife", "category": "竞品品牌词", "reason": "可低价广告测试，但不能进入 Listing/backend"},
    {"scope": "Listing/backend only", "negative_match_type": "do not use in listing", "term": "LEGO", "category": "竞品品牌词", "reason": "可低价广告测试，但不能进入 Listing/backend"},
    {"scope": "Listing/backend only", "negative_match_type": "do not use in listing", "term": "FUNPOLA", "category": "竞品品牌词", "reason": "可低价广告测试，但不能进入 Listing/backend"},
    {"scope": "Listing/backend only", "negative_match_type": "do not use in listing", "term": "Cuteroom", "category": "竞品品牌词", "reason": "可低价广告测试，但不能进入 Listing/backend"},
]


def _load_script(name: str):
    script = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _as_terms(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        return [str(k).strip() for k in value if str(k).strip()]
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            term = item.strip()
        elif isinstance(item, dict):
            term = str(item.get("term") or item.get("keyword") or item.get("target") or item.get("Term") or "").strip()
        else:
            term = str(item or "").strip()
        if term:
            out.append(term)
    return out


def dedupe_terms(*term_lists: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for terms in term_lists:
        for term in _as_terms(terms):
            key = term.lower()
            if key not in seen:
                seen.add(key)
                out.append(term)
    return out


def _negative_item(term: str, known_items: list[dict[str, str]] | None = None) -> dict[str, str]:
    for item in known_items or []:
        if str(item.get("term") or item.get("Term") or "").lower() == term.lower():
            return {
                "scope": str(item.get("scope") or item.get("Scope") or "All search campaigns"),
                "negative_match_type": str(item.get("negative_match_type") or item.get("NegativeMatchType") or "negative phrase"),
                "term": term,
                "category": str(item.get("category") or item.get("Category") or "长期预否词"),
                "reason": str(item.get("reason") or item.get("Reason") or "Book Nook知识库长期预否词"),
            }
    return {
        "scope": "All search campaigns",
        "negative_match_type": "negative phrase",
        "term": term,
        "category": "长期预否词",
        "reason": "Book Nook知识库长期预否词",
    }


def load_book_nook_knowledge(path: str | Path = DEFAULT_KNOWLEDGE_JSON) -> dict[str, Any]:
    renderer = _load_script("render_sorftime_launch_plan")
    knowledge = renderer.load_knowledge(path)
    knowledge.setdefault("category", "Book Nook")
    knowledge.setdefault("themes", [])
    knowledge.setdefault("core_keywords", {})
    knowledge.setdefault("competitor_brands", [])
    knowledge.setdefault("long_term_pre_negatives", [])
    return knowledge


def build_theme_profile(context: dict[str, Any], knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    knowledge = knowledge or {}
    theme_label = context.get("theme_label") or context.get("parent_label") or "BookNook_Generic"
    long_term_negatives = knowledge.get("long_term_pre_negatives") or []
    negative_defaults = DEFAULT_PRE_NEGATIVES[:]
    negative_terms = dedupe_terms(negative_defaults, long_term_negatives, context.get("pre_negative_terms"))
    profile = {
        "theme_label": theme_label,
        "parent_label": context.get("parent_label") or theme_label,
        "core_terms": dedupe_terms(DEFAULT_CORE_TERMS, context.get("core_terms")),
        "theme_longtail_terms": dedupe_terms(context.get("theme_longtail_terms")),
        "generic_observation_terms": dedupe_terms(DEFAULT_GENERIC_OBSERVATION_TERMS, context.get("generic_observation_terms")),
        "ranking_terms": dedupe_terms(context.get("ranking_terms") or ["book nook", "book nook kit"]),
        "variant_routing_rules": context.get("variant_routing_rules") or {},
        "pre_negative_terms": [_negative_item(term, negative_defaults) for term in negative_terms],
        "competitor_brands": dedupe_terms(knowledge.get("competitor_brands"), context.get("competitor_brands"), ["CUTEBEE", "Rolife", "LEGO", "FUNPOLA", "Cuteroom"]),
        "budgets": {**DEFAULT_BUDGETS, **(context.get("budgets") or {})},
    }
    return profile


def build_book_nook_context(context: dict[str, Any], knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = build_theme_profile(context, knowledge)
    merged = {**context}
    merged.update({
        "theme_label": profile["theme_label"],
        "parent_label": profile["parent_label"],
        "core_terms": profile["core_terms"],
        "theme_longtail_terms": profile["theme_longtail_terms"],
        "generic_observation_terms": profile["generic_observation_terms"],
        "ranking_terms": profile["ranking_terms"],
        "variant_routing_rules": profile["variant_routing_rules"],
        "pre_negative_terms": profile["pre_negative_terms"],
        "competitor_brands": profile["competitor_brands"],
        "budgets": profile["budgets"],
    })
    if "shared_id" not in merged:
        merged["shared_id"] = None
    return merged


def run_book_nook_optimization(
    *,
    db_path: str | Path = DEFAULT_DB,
    context_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    report_prefix: str | Path,
    knowledge_json: str | Path = DEFAULT_KNOWLEDGE_JSON,
    knowledge_md: str | Path = DEFAULT_KNOWLEDGE_MD,
    generated_at: str,
    target_acos: float = 0.2,
) -> dict[str, Any]:
    context = load_json(context_json, {})
    knowledge = load_book_nook_knowledge(knowledge_json)
    context = build_book_nook_context(context, knowledge)
    asins = [str(asin).upper() for asin in context.get("asins", [])]
    if not asins:
        raise ValueError("Book Nook context requires at least one ASIN in `asins`.")
    shared_id = context.get("shared_id")
    scope_id = context.get("scope_id") or shared_id or "_".join(asins)

    workflow = _load_script("ads_agent_workflow")
    renderer = _load_script("render_sorftime_launch_plan")
    workflow_result = workflow.run_agent_workflow(
        db_path,
        scope_id=scope_id,
        asins=asins,
        shared_id=shared_id,
        output_root=output_root,
        marketplace=context.get("marketplace", "AU"),
        parent_asin=context.get("parent_asin"),
        variant_routing_rules=context.get("variant_routing_rules"),
        sorftime_context=context,
        target_acos=target_acos,
        generated_at=generated_at,
    )
    plan = renderer.build_plan(db_path, context, str(report_prefix), generated_at)
    renderer.write_outputs(plan)
    renderer.write_knowledge_base(plan, knowledge_json, knowledge_md)
    return {
        "scope_id": scope_id,
        "asins": asins,
        "shared_id": shared_id,
        "files": plan["campaign_files"],
        "middle_files": workflow_result["files"],
        "data_pack": workflow_result["data_pack"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the default Book Nook ads optimization workflow.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--context-json", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report-prefix", required=True)
    parser.add_argument("--knowledge-json", default=str(DEFAULT_KNOWLEDGE_JSON))
    parser.add_argument("--knowledge-md", default=str(DEFAULT_KNOWLEDGE_MD))
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--target-acos", type=float, default=0.2)
    args = parser.parse_args()
    result = run_book_nook_optimization(
        db_path=args.db,
        context_json=args.context_json,
        output_root=args.output_root,
        report_prefix=args.report_prefix,
        knowledge_json=args.knowledge_json,
        knowledge_md=args.knowledge_md,
        generated_at=args.generated_at,
        target_acos=args.target_acos,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
