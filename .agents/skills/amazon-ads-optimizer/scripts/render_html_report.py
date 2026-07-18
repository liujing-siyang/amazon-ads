#!/usr/bin/env python3
"""Render interactive HTML reports for Amazon Ads recommendations."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


ZH = {
    "title": "Amazon \u5e7f\u544a\u4f18\u5316\u62a5\u544a",
    "spend": "\u82b1\u8d39",
    "sales": "\u9500\u552e\u989d",
    "orders": "\u8ba2\u5355",
    "margin_section": "\u6bdb\u5229\u6a21\u578b\u4e0e\u76ee\u6807 ACOS",
    "break_even": "\u76c8\u4e8f\u5e73\u8861 ACOS",
    "recommended": "\u5efa\u8bae\u76ee\u6807 ACOS",
    "threshold_section": "\u52a8\u6001\u9608\u503c\u8bf4\u660e",
    "threshold_text": "\u5141\u8bb8\u6d4b\u8bd5\u82b1\u8d39 = \u5ba2\u5355\u4ef7 \u00d7 \u76ee\u6807 ACOS\uff1b\u8fbe\u5230\u52a8\u6001\u82b1\u8d39\u9608\u503c\u4e14\u70b9\u51fb\u6570\u8fbe\u5230\u6700\u4f4e\u8bc4\u4f30\u70b9\u51fb\u540e\uff0c\u624d\u5efa\u8bae\u5426\u5b9a\u6216\u964d\u4ef7\u3002\u6700\u4f4e\u8bc4\u4f30\u70b9\u51fb\uff1a",
    "trend_section": "\u5e7f\u544a\u8868\u73b0\u4e0e\u8d8b\u52bf",
    "structure_section": "\u5e7f\u544a\u7ed3\u6784\u5efa\u8bae",
    "sorftime_section": "Sorftime \u4ea7\u54c1\u8d8b\u52bf/\u6392\u540d/\u6d41\u91cf\u8bcd",
    "no_structure": "\u6682\u65e0\u8db3\u591f\u6570\u636e\u751f\u6210\u7ed3\u6784\u5efa\u8bae",
    "listing_section": "Listing \u627f\u63a5\u80fd\u529b\u8bc4\u5206",
    "score": "\u8bc4\u5206",
    "suggested_title": "\u5efa\u8bae\u6807\u9898",
    "suggested_bullets": "\u5efa\u8bae\u4e94\u70b9\u63cf\u8ff0",
    "suggested_description": "\u5efa\u8bae\u957f\u63cf\u8ff0",
    "backend": "\u5efa\u8bae\u540e\u53f0 search terms",
    "sources_section": "\u6570\u636e\u6765\u6e90\u4e0e\u8bc1\u636e\u5ba1\u8ba1",
    "tracking_section": "\u64cd\u4f5c\u5efa\u8bae\u8ffd\u8e2a",
    "tracking_text": "\u5efa\u8bae\u72b6\u6001\u652f\u6301 open / planned / executed / ignored / expired\uff1b\u6267\u884c\u540e\u53ef\u8bb0\u5f55\u8c03\u6574\u524d\u540e bid\uff0c\u5e76\u5728\u540e\u7eed 7/14 \u5929\u6570\u636e\u5bfc\u5165\u540e\u590d\u76d8\u6548\u679c\u3002",
    "recs_section": "\u5173\u952e\u8bcd\u610f\u56fe\u5206\u7c7b\u4e0e\u64cd\u4f5c\u5efa\u8bae",
    "all_actions": "\u5168\u90e8\u52a8\u4f5c",
    "all_priority": "\u5168\u90e8\u4f18\u5148\u7ea7",
    "all_modes": "\u5168\u90e8\u5e7f\u544a\u65b9\u5f0f",
    "all_acos": "\u5168\u90e8 ACOS \u72b6\u6001",
    "all_evidence": "\u5168\u90e8\u8bc1\u636e",
    "amazon_evidence": "\u4ec5 Amazon \u5e7f\u544a\u6570\u636e",
    "external_evidence": "SellerSprite/\u5916\u90e8\u5de5\u5177\u4f30\u7b97",
    "search": "\u641c\u7d22\u8bcd",
    "priority": "\u4f18\u5148\u7ea7",
    "intent": "\u610f\u56fe",
    "action": "\u52a8\u4f5c",
    "ad_mode": "\u5e7f\u544a\u65b9\u5f0f",
    "clicks": "\u70b9\u51fb",
    "reason": "\u539f\u56e0",
    "next_step": "\u4e0b\u4e00\u6b65",
    "threshold": "\u9608\u503c\u72b6\u6001",
    "external_tool": "\u5916\u90e8\u5de5\u5177\u8bc1\u636e",
    "listing_gap": "Listing \u7f3a\u53e3",
}


def _fmt_money(value: Any) -> str:
    return "" if value is None else f"AUD {float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _list_items(items: list[Any]) -> str:
    return "".join(f"<li>{_esc(x)}</li>" for x in (items or []))


def render_html(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    profile = result.get("rule_profile", {})
    margin = result.get("margin_model", {})
    trend = result.get("trend_analysis", {})
    listing = result.get("listing_optimization", {})
    structure = result.get("ad_structure_plan", [])
    sorftime = result.get("sorftime_context", {}).get("metrics", {})
    recs = result.get("recommendations", [])
    sources = result.get("sources", [])
    evidence = result.get("evidence_validation", {})
    rows = []
    for rec in recs:
        m = rec.get("metric_evidence", {})
        seller = rec.get("sellersprite_evidence") or rec.get("external_keyword_evidence") or {}
        seller_text = ""
        if seller:
            bits = ["SellerSprite/External estimate"]
            if seller.get("search_volume") is not None:
                bits.append(f"SV {seller['search_volume']}")
            if seller.get("cpc") is not None:
                bits.append(f"CPC {seller['cpc']}")
            if seller.get("organic_rank") is not None:
                bits.append(f"Organic #{seller['organic_rank']}")
            seller_text = "; ".join(bits)
        gap = ", ".join(rec.get("listing_gap_tokens") or [])
        rows.append(f"""
        <tr data-action=\"{_esc(rec.get('action'))}\" data-priority=\"{_esc(rec.get('priority'))}\" data-admode=\"{_esc(rec.get('ad_mode'))}\" data-threshold=\"{_esc(rec.get('threshold_state'))}\" data-evidence=\"{'sellersprite' if seller else 'amazon'}\">
          <td>{_esc(rec.get('priority'))}</td><td>{_esc(rec.get('intent_label_zh') or rec.get('intent'))}</td><td>{_esc(rec.get('action'))}</td><td>{_esc(rec.get('search_term'))}</td>
          <td>{_esc(rec.get('keyword'))}</td><td>{_esc(rec.get('ad_mode'))}</td><td>{_fmt_money(m.get('spend'))}</td>
          <td>{_esc(m.get('clicks'))}</td><td>{_esc(m.get('orders'))}</td><td>{_fmt_money(m.get('sales'))}</td><td>{_fmt_pct(m.get('acos'))}</td>
          <td>{_esc(rec.get('threshold_state'))}</td><td>{_esc(seller_text)}</td><td>{_esc(gap)}</td>
          <td>{_esc(rec.get('reason'))}</td><td>{_esc(rec.get('suggested_next_step'))}</td>
        </tr>""")
    source_items = "".join(f"<li>{_esc(s.get('type'))}: {_esc(s.get('label'))}</li>" for s in sources)
    profile_items = "".join(f"<span class='pill'>{_esc(k)}: {_esc(v)}</span>" for k, v in profile.items() if k != 'margin_model')
    structure_html = "".join(f"<div class='plan'><strong>{_esc(g.get('title_zh'))}</strong><div>{_esc(', '.join(g.get('terms') or []))}</div></div>" for g in structure)
    detail = sorftime.get("product_detail", {}) if isinstance(sorftime, dict) else {}
    trend_bits = []
    for key, label in [("trend_sales_volume", "SalesVolume"), ("trend_sales_amount", "SalesAmount"), ("trend_price", "Price"), ("trend_rank", "Rank")]:
        if sorftime.get(key):
            trend_bits.append(f"<li>{label}: {_esc(sorftime.get(key))}</li>")
    traffic_terms = sorftime.get("traffic_terms") or []
    traffic_html = "".join(f"<span class='pill'>{_esc(t.get('keyword'))} | SV {_esc(t.get('search_volume'))} | {_esc(t.get('organic_position'))}</span>" for t in traffic_terms[:12] if isinstance(t, dict))
    sorftime_html = ""
    if sorftime:
        sorftime_html = (
            f"<section><h2>{ZH['sorftime_section']}</h2>"
            f"<p>\u4ef7\u683c {_fmt_money(detail.get('price'))}"
            f"\uff1b\u8bc4\u5206 {_esc(detail.get('rating'))}"
            f"\uff1b\u8bc4\u8bba\u6570 {_esc(detail.get('review_count'))}"
            f"\uff1b\u6708\u9500\u91cf {_esc(detail.get('monthly_sales'))}"
            f"\uff1b\u5927\u7c7b\u6392\u540d {_esc(detail.get('category_rank'))}"
            f"\uff1b\u7ec6\u5206\u7c7b\u76ee\u6392\u540d {_esc(detail.get('subcategory_rank'))}</p>"
            f"<ul>{''.join(trend_bits)}</ul><div>{traffic_html}</div></section>"
        )
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Amazon Ads Optimization Report - {_esc(result.get('asin'))}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;color:#1f2933;background:#f6f7f9}}header{{background:#fff;border-bottom:1px solid #d9dee5;padding:20px 28px}}main{{padding:20px 28px}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}}.kpi,section{{background:#fff;border:1px solid #d9dee5;border-radius:6px;padding:14px;margin-bottom:14px}}.kpi strong{{display:block;font-size:20px;margin-top:4px}}.controls{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}}select,input{{padding:7px 9px;border:1px solid #bac3cf;border-radius:4px}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}th,td{{border-bottom:1px solid #e3e7ed;padding:8px;vertical-align:top;text-align:left}}th{{position:sticky;top:0;background:#eef2f6;z-index:1}}.pill{{display:inline-block;padding:4px 7px;border:1px solid #c8d1dc;border-radius:999px;margin:3px;background:#fff;font-size:12px}}.plan{{border:1px solid #e3e7ed;border-radius:4px;padding:8px;margin:6px 0}}.copy{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e3e7ed;padding:10px;border-radius:4px}}.hidden{{display:none}}</style>
</head><body><header><h1>{ZH['title']}</h1><div>ASIN: <strong>{_esc(result.get('asin'))}</strong></div></header><main>
<div class=\"kpis\"><div class=\"kpi\">{ZH['spend']}<strong>{_fmt_money(summary.get('spend'))}</strong></div><div class=\"kpi\">{ZH['sales']}<strong>{_fmt_money(summary.get('sales'))}</strong></div><div class=\"kpi\">{ZH['orders']}<strong>{_esc(summary.get('orders'))}</strong></div><div class=\"kpi\">ACOS<strong>{_fmt_pct(summary.get('acos'))}</strong></div></div>
<section><h2>{ZH['margin_section']}</h2><p>{ZH['break_even']}: {_fmt_pct(margin.get('break_even_acos'))}\uff1b{ZH['recommended']}: {_fmt_pct(margin.get('recommended_target_acos') or profile.get('target_acos'))}</p></section>
<section><h2>{ZH['threshold_section']}</h2>{profile_items}<p>{ZH['threshold_text']} {profile.get('wasted_click_threshold')}\uff1b\u5f53\u524d\u5141\u8bb8\u6d4b\u8bd5\u82b1\u8d39\uff1a{_fmt_money(profile.get('allowed_test_spend'))}</p></section>
<section><h2>{ZH['trend_section']}</h2><p>{_esc(trend.get('message_zh'))}</p></section>
{sorftime_html}
<section><h2>{ZH['structure_section']}</h2>{structure_html or '<p>' + ZH['no_structure'] + '</p>'}</section>
<section><h2>{ZH['listing_section']}</h2><p>{ZH['score']}：<strong>{_esc(listing.get('score'))}</strong></p><p>{_esc(listing.get('rationale_zh'))}</p><h3>{ZH['suggested_title']}</h3><div class=\"copy\">{_esc(listing.get('title'))}</div><h3>{ZH['suggested_bullets']}</h3><ol>{_list_items(listing.get('bullets') or [])}</ol><h3>{ZH['suggested_description']}</h3><div class=\"copy\">{_esc(listing.get('description'))}</div><h3>{ZH['backend']}</h3><div class=\"copy\">{_esc(' '.join(listing.get('backend_search_terms') or []))}</div></section>
<section><h2>{ZH['sources_section']}</h2><ul>{source_items}</ul><p>{_esc(evidence)}</p></section>
<section><h2>{ZH['tracking_section']}</h2><p>{ZH['tracking_text']}</p></section>
<section><h2>{ZH['recs_section']}</h2><div class=\"controls\"><select id=\"filterAction\"><option value=\"\">{ZH['all_actions']}</option></select><select id=\"filterPriority\"><option value=\"\">{ZH['all_priority']}</option></select><select id=\"filterAdmode\"><option value=\"\">{ZH['all_modes']}</option></select><select id=\"filterThreshold\"><option value=\"\">{ZH['all_acos']}</option></select><select id=\"filterEvidence\"><option value=\"\">{ZH['all_evidence']}</option><option value=\"amazon\">{ZH['amazon_evidence']}</option><option value=\"sellersprite\">{ZH['external_evidence']}</option></select><input id=\"searchBox\" placeholder=\"{ZH['search']}\"></div>
<table id=\"recommendations-table\"><thead><tr><th>{ZH['priority']}</th><th>{ZH['intent']}</th><th>{ZH['action']}</th><th>Search Term</th><th>Keyword</th><th>{ZH['ad_mode']}</th><th>{ZH['spend']}</th><th>{ZH['clicks']}</th><th>{ZH['orders']}</th><th>{ZH['sales']}</th><th>ACOS</th><th>{ZH['threshold']}</th><th>{ZH['external_tool']}</th><th>{ZH['listing_gap']}</th><th>{ZH['reason']}</th><th>{ZH['next_step']}</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
</main><script>
const table=document.getElementById('recommendations-table');const rows=Array.from(table.querySelectorAll('tbody tr'));
function fillSelect(id,attr){{const select=document.getElementById(id);[...new Set(rows.map(r=>r.dataset[attr]).filter(Boolean))].sort().forEach(v=>{{const o=document.createElement('option');o.value=v;o.textContent=v;select.appendChild(o);}})}}
fillSelect('filterAction','action');fillSelect('filterPriority','priority');fillSelect('filterAdmode','admode');fillSelect('filterThreshold','threshold');
function applyFilters(){{const f={{action:filterAction.value,priority:filterPriority.value,admode:filterAdmode.value,threshold:filterThreshold.value,evidence:filterEvidence.value}};const q=searchBox.value.toLowerCase();rows.forEach(r=>{{const ok=(!f.action||r.dataset.action===f.action)&&(!f.priority||r.dataset.priority===f.priority)&&(!f.admode||r.dataset.admode===f.admode)&&(!f.threshold||r.dataset.threshold===f.threshold)&&(!f.evidence||r.dataset.evidence===f.evidence)&&(!q||r.textContent.toLowerCase().includes(q));r.classList.toggle('hidden',!ok);}})}}
document.querySelectorAll('select,input').forEach(el=>el.addEventListener('input',applyFilters));
</script></body></html>"""


def write_html_report(result: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(result), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an HTML report from analysis JSON.")
    parser.add_argument("analysis_json")
    parser.add_argument("output_html")
    args = parser.parse_args()
    result = json.loads(Path(args.analysis_json).read_text(encoding="utf-8-sig"))
    print(write_html_report(result, args.output_html))


if __name__ == "__main__":
    main()

