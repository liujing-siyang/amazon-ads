#!/usr/bin/env python3
"""Render a multi-variant Amazon Ads report with a shared manual campaign group."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
ACTIONS_FOR_TABLE = {
    "promote_to_exact",
    "increase_bid_or_budget",
    "add_negative_or_reduce_bid",
    "ranking_support_review",
    "reduce_bid_for_high_acos",
}


def _load_analyzer():
    script = Path(__file__).with_name("analyze_asin.py")
    spec = importlib.util.spec_from_file_location("analyze_asin", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _money(value: Any) -> str:
    return "AUD 0.00" if value is None else f"AUD {float(value):,.2f}"


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def _metric_from_row(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {"impressions": 0, "clicks": 0, "spend": 0.0, "orders": 0, "sales": 0.0, "acos": None, "cvr": None}
    impressions = int(row["impressions"] or 0)
    clicks = int(row["clicks"] or 0)
    spend = round(float(row["spend"] or 0), 2)
    orders = int(row["orders"] or 0)
    sales = round(float(row["sales"] or 0), 2)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "orders": orders,
        "sales": sales,
        "acos": round(spend / sales, 4) if sales else None,
        "cvr": round(orders / clicks, 4) if clicks else None,
    }


def _summary(conn: sqlite3.Connection, asin: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
               sum(orders) orders, sum(sales) sales
        from search_term_performance
        where asin = ? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        """,
        (asin,),
    ).fetchone()
    return _metric_from_row(row)


def _sources(conn: sqlite3.Connection, asin: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select source_file, report_start, report_end, ad_mode, rows_imported
        from ad_report_imports
        where asin = ? and coalesce(is_active, 1)=1
        order by report_start, report_end, id
        """,
        (asin,),
    ).fetchall()
    return [dict(row) for row in rows]


def _periods(conn: sqlite3.Connection, asin: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select report_start, report_end, ad_mode,
               sum(spend) spend, sum(sales) sales, sum(orders) orders, sum(clicks) clicks
        from search_term_performance
        where asin = ? and import_id in (select id from ad_report_imports where coalesce(is_active, 1)=1)
        group by report_start, report_end, ad_mode
        order by report_start, report_end, ad_mode
        """,
        (asin,),
    ).fetchall()
    periods = []
    for row in rows:
        spend = float(row["spend"] or 0)
        sales = float(row["sales"] or 0)
        periods.append({
            "report_start": row["report_start"],
            "report_end": row["report_end"],
            "ad_mode": row["ad_mode"],
            "spend": round(spend, 2),
            "sales": round(sales, 2),
            "orders": int(row["orders"] or 0),
            "clicks": int(row["clicks"] or 0),
            "acos": round(spend / sales, 4) if sales else None,
        })
    return periods


def _filtered_recs(result: dict[str, Any], source_label: str) -> list[dict[str, Any]]:
    recs = []
    for rec in result.get("recommendations", []):
        if rec.get("action") not in ACTIONS_FOR_TABLE:
            continue
        if not (rec.get("search_term") or "").strip():
            continue
        item = dict(rec)
        item["source_label"] = source_label
        recs.append(item)
    return recs


def _top_terms(recs: list[dict[str, Any]], action: str | None = None, limit: int = 12) -> list[str]:
    terms = []
    for rec in recs:
        if action and rec.get("action") != action:
            continue
        term = rec.get("search_term")
        if term and term not in terms:
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _action_label(action: str) -> str:
    return {
        "promote_to_exact": "加入手动精准/词组",
        "increase_bid_or_budget": "小幅加价或加预算",
        "add_negative_or_reduce_bid": "否词或降价",
        "ranking_support_review": "排名支持复核",
        "reduce_bid_for_high_acos": "高 ACOS 降价",
    }.get(action, action)


def _next_step_zh(rec: dict[str, Any], target_acos: float) -> str:
    action = rec.get("action")
    if action == "promote_to_exact":
        return "建手动精准；若是长尾日系/场景词，可按对应 ASIN 单独建组。"
    if action == "increase_bid_or_budget":
        return "在当前 CPC 基础上小幅加价 10%-15%，7-14 天复盘 ACOS。"
    if action == "add_negative_or_reduce_bid":
        return "先判定相关性；明显无关做否定精准/词组，相关但未转化先降价。"
    if action == "ranking_support_review":
        return f"仅当需要排名保留；预算单独控制，ACOS 高于 {target_acos:.0%} 时不作为利润词放量。"
    if action == "reduce_bid_for_high_acos":
        return "降价或拆到低预算排名测试组，避免拖累整体利润。"
    return rec.get("suggested_next_step") or "复核后执行。"


def _render_rows(recs: list[dict[str, Any]], target_acos: float) -> str:
    rows = []
    for rec in recs:
        m = rec.get("metric_evidence", {})
        rows.append(
            "<tr>"
            f"<td>{_esc(rec.get('source_label'))}</td>"
            f"<td>{_esc(rec.get('priority'))}</td>"
            f"<td>{_esc(rec.get('intent_label_zh') or rec.get('intent'))}</td>"
            f"<td>{_esc(_action_label(rec.get('action') or ''))}</td>"
            f"<td>{_esc(rec.get('search_term'))}</td>"
            f"<td>{_esc(rec.get('keyword'))}</td>"
            f"<td>{_esc(rec.get('ad_mode'))}</td>"
            f"<td>{_money(m.get('spend'))}</td>"
            f"<td>{_esc(m.get('clicks'))}</td>"
            f"<td>{_esc(m.get('orders'))}</td>"
            f"<td>{_money(m.get('sales'))}</td>"
            f"<td>{_pct(m.get('acos'))}</td>"
            f"<td>{_esc(_next_step_zh(rec, target_acos))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_summary_card(label: str, summary: dict[str, Any]) -> str:
    return f"""
    <div class=\"card\"><h3>{_esc(label)}</h3>
      <div class=\"metrics\"><span>花费 <b>{_money(summary.get('spend'))}</b></span><span>销售 <b>{_money(summary.get('sales'))}</b></span><span>订单 <b>{_esc(summary.get('orders'))}</b></span><span>ACOS <b>{_pct(summary.get('acos'))}</b></span><span>CVR <b>{_pct(summary.get('cvr'))}</b></span></div>
    </div>"""


def _render_sources(label: str, sources: list[dict[str, Any]]) -> str:
    items = []
    for src in sources:
        items.append(
            f"<li>{_esc(label)} | {_esc(src.get('ad_mode'))} | {_esc(src.get('report_start'))} - {_esc(src.get('report_end'))} | rows {_esc(src.get('rows_imported'))} | {_esc(Path(src.get('source_file') or '').name)}</li>"
        )
    return "".join(items)


def build_report(db_path: str | Path, asins: list[str], shared_id: str, target_acos: float) -> dict[str, Any]:
    analyzer = _load_analyzer()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        asin_results = {asin: analyzer.analyze(db_path, asin, target_acos) for asin in asins}
        shared_result = analyzer.analyze(db_path, shared_id, target_acos)
        summaries = {asin: _summary(conn, asin) for asin in asins}
        summaries[shared_id] = _summary(conn, shared_id)
        periods = {asin: _periods(conn, asin) for asin in [*asins, shared_id]}
        sources = {asin: _sources(conn, asin) for asin in [*asins, shared_id]}
    recs_by_source = []
    for asin in asins:
        recs_by_source.extend(_filtered_recs(asin_results[asin], f"{asin} 自动"))
    shared_recs = _filtered_recs(shared_result, "共享手动组")
    recs_by_source.extend(shared_recs)
    recs_by_source.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.get("priority"), 3), -(r.get("metric_evidence", {}).get("sales") or 0), -(r.get("metric_evidence", {}).get("spend") or 0)))
    return {
        "asins": asins,
        "shared_id": shared_id,
        "target_acos": target_acos,
        "summaries": summaries,
        "periods": periods,
        "sources": sources,
        "asin_results": asin_results,
        "shared_result": shared_result,
        "recommendations": recs_by_source,
        "shared_recommendations": shared_recs,
    }


def render_html(report: dict[str, Any]) -> str:
    asins = report["asins"]
    shared_id = report["shared_id"]
    target_acos = float(report["target_acos"])
    summaries = report["summaries"]
    all_recs = report["recommendations"]
    shared_recs = report["shared_recommendations"]
    exact_terms = []
    for asin in asins:
        terms = _top_terms(_filtered_recs(report["asin_results"][asin], f"{asin} 自动"), "promote_to_exact", 10)
        if terms:
            exact_terms.append(f"<li><b>{_esc(asin)} 单品精准：</b>{_esc(', '.join(terms))}</li>")
    shared_core = _top_terms(shared_recs, "increase_bid_or_budget", 12) or _top_terms(shared_recs, "promote_to_exact", 12)
    negatives = _top_terms([r for r in all_recs if r.get("action") == "add_negative_or_reduce_bid"], None, 20)
    ranking = _top_terms([r for r in all_recs if r.get("action") in {"ranking_support_review", "reduce_bid_for_high_acos"}], None, 20)
    source_items = []
    for asin in [*asins, shared_id]:
        source_items.append(_render_sources(asin, report["sources"].get(asin, [])))
    period_rows = []
    for asin in [*asins, shared_id]:
        for period in report["periods"].get(asin, []):
            period_rows.append(
                "<tr>"
                f"<td>{_esc(asin)}</td><td>{_esc(period['ad_mode'])}</td><td>{_esc(period['report_start'])} - {_esc(period['report_end'])}</td>"
                f"<td>{_money(period['spend'])}</td><td>{_money(period['sales'])}</td><td>{_esc(period['orders'])}</td><td>{_esc(period['clicks'])}</td><td>{_pct(period['acos'])}</td>"
                "</tr>"
            )
    generated = "2026-07-10"
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>多变体 ASIN 广告优化报告 - {generated}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fa;color:#1f2933}}header{{background:#fff;border-bottom:1px solid #d9dee5;padding:22px 28px}}main{{padding:20px 28px}}section,.card{{background:#fff;border:1px solid #d9dee5;border-radius:6px;padding:14px;margin-bottom:14px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}.metrics span{{background:#f8fafc;border:1px solid #e3e7ed;border-radius:4px;padding:8px}}table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff}}th,td{{border-bottom:1px solid #e3e7ed;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef2f6;position:sticky;top:0}}.note{{color:#52616f}}.pill{{display:inline-block;border:1px solid #c8d1dc;border-radius:999px;padding:4px 8px;margin:3px;background:#fff}}</style>
</head><body><header><h1>多变体 ASIN 广告优化报告</h1><p class=\"note\">ASIN: {_esc(', '.join(asins))}；共享手动组：{_esc(shared_id)}；目标 ACOS：{_pct(target_acos)}。共享手动组不并入单品汇总，避免花费和销售双算。</p></header><main>
<section><h2>总览</h2><div class=\"grid\">{''.join(_render_summary_card(asin + ' 自动/已归因数据', summaries[asin]) for asin in asins)}{_render_summary_card('共享手动组', summaries[shared_id])}</div></section>
<section><h2>广告架构建议</h2><ul>
<li>各子 ASIN 继续保留各自自动广告，用于搜索词发现；自动广告中已转化且 ACOS 低于目标的词，迁移到手动精准/词组。</li>
<li>共享手动组保留大词和两品都能承接的共性词，例如：{_esc(', '.join(shared_core[:10]) or '暂无足够共享核心词')}。</li>
<li>长尾、场景、款式词按转化来源或变体意图拆到对应 ASIN 的单品精准组，减少多个变体互相抢预算。</li>
<li>排名支持词单独控预算，不与利润词混在同一预算池。</li>
</ul><ul>{''.join(exact_terms)}</ul></section>
<section><h2>关键词与预算动作</h2><p><b>共享组核心/可加价：</b>{_esc(', '.join(shared_core) or '暂无')}</p><p><b>排名支持或需降价复核：</b>{_esc(', '.join(ranking) or '暂无')}</p><p><b>否词/降价候选：</b>{_esc(', '.join(negatives) or '暂无达到阈值的候选')}</p></section>
<section><h2>周期表现</h2><table><thead><tr><th>对象</th><th>广告方式</th><th>周期</th><th>花费</th><th>销售</th><th>订单</th><th>点击</th><th>ACOS</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table><p class=\"note\">当前 CSV 是周期汇总报表，可做周期级对比，但不能生成真实 7/14/30 天趋势。</p></section>
<section><h2>执行动作表</h2><table><thead><tr><th>来源</th><th>优先级</th><th>意图</th><th>动作</th><th>搜索词</th><th>关键词/投放</th><th>广告方式</th><th>花费</th><th>点击</th><th>订单</th><th>销售</th><th>ACOS</th><th>下一步</th></tr></thead><tbody>{_render_rows(all_recs, target_acos)}</tbody></table></section>
<section><h2>数据来源</h2><ul>{''.join(source_items)}</ul></section>
</main></body></html>"""


def write_html_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a multi-variant report with a shared manual group.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--asin", action="append", required=True, help="ASIN to include; pass once per variant")
    parser.add_argument("--shared-id", required=True)
    parser.add_argument("--target-acos", type=float, default=0.2)
    parser.add_argument("--html-output", required=True)
    args = parser.parse_args()
    report = build_report(args.db, [a.upper() for a in args.asin], args.shared_id.upper(), args.target_acos)
    print(write_html_report(report, args.html_output))


if __name__ == "__main__":
    main()

