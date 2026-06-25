---
name: amazon-ads-optimizer
description: Analyze and optimize Amazon AU Sponsored Products advertising for a single ASIN using dynamic rule profiles, margin models, Amazon ad CSV reports, scraped listing snapshots, external keyword-tool evidence, Sorftime MCP product context, recommendation tracking, and Chinese HTML decision reports. Use when Codex needs to import ASIN ad files, configure profit/ranking thresholds, scrape listings, validate evidence, import SellerSprite/Helium 10/Jungle Scout keyword estimates, fetch Sorftime context, run ad analysis, generate listing copy, or produce HTML reports for bid, negative keyword, search-term promotion, budget, ranking-support, ad-structure, and listing optimization recommendations.
---

# Amazon Ads Optimizer

Use this skill for Amazon AU Sponsored Products optimization where the goal is profit efficiency first, with explicit ranking support separated from profit scaling. Raw search terms, keywords, ASINs, and generated listing copy stay in English. Operator explanations in HTML reports should be Chinese.

## HTML Workflows

Static config workflow:
1. Open `ui/config-builder.html` in a browser.
2. Fill ASIN, database path, Amazon URL, margin model, dynamic thresholds, intent tolerances, external keyword mapping, and optional Sorftime switches.
3. Download `analysis-config.json`.
4. Run `python scripts/analyze_asin.py --config analysis-config.json --html-output reports/<ASIN>.html`.

Local web workflow:
1. Run `python scripts/serve_ui.py --db data/amazon_ads.sqlite --port 8765`.
2. Open `http://127.0.0.1:8765`.
3. Use API/UI actions to import CSVs, validate evidence, analyze, and generate HTML reports.

## CLI Workflow

1. Scrape the ASIN listing:
   `python scripts/scrape_listing.py B0GXZQXFM4 --db data/amazon_ads.sqlite`
2. Import ad reports named `{start_date}??{end_date}_{asin}_{??|??}.csv`:
   `python scripts/import_ad_reports.py data/imports/2026-05-01??06-25_B0GXZQXFM4_??.csv --db data/amazon_ads.sqlite`
3. Import external keyword evidence from SellerSprite, Helium 10, Jungle Scout, or compatible files:
   `python scripts/import_external_keywords.py keywords.xlsx --tool SellerSprite --mapping mapping.json --captured-date 2026-06-25 --db data/amazon_ads.sqlite`
4. Store Sorftime MCP payloads when available:
   `python scripts/fetch_sorftime_asin.py B0GXZQXFM4 --site AU --db data/amazon_ads.sqlite --payload-json sorftime_payloads.json`
5. Validate evidence:
   `python scripts/validate_evidence.py --db data/amazon_ads.sqlite`
6. Analyze with a config, margin-derived target ACOS, or legacy target ACOS:
   `python scripts/analyze_asin.py B0GXZQXFM4 --target-acos 0.20 --html-output reports/B0GXZQXFM4.html`

## Required Behavior

- Default waste evaluation uses at least 20 clicks plus dynamic allowed test spend: `average_order_value * target_acos` or `selling_price * target_acos`.
- Margin model should compute break-even ACOS and recommended target ACOS when selling price and costs are supplied.
- Classify terms as profit, ranking, exploration, defense, competitor, or irrelevant before recommending action.
- Competitor brand terms may be tested in competitor campaigns but must not be inserted into generated listing copy or backend terms.
- Period-only ad CSVs cannot produce true 7/14/30-day trends; state this clearly in Chinese.
- All third-party keyword/CPC/rank values are sourced estimates, never Amazon Ads truth.

## References

Read `references/data-schema.md` before changing imports or tables. Read `references/optimization-playbook.md` before changing thresholds, margin logic, intent logic, or recommendation logic. Read `references/evidence-standard.md` before using external tool or Sorftime data.
