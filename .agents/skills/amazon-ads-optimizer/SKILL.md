---
name: amazon-ads-optimizer
description: Analyze and optimize Amazon AU Sponsored Products advertising for a single ASIN using dynamic rule profiles, margin models, Amazon ad CSV reports, scraped listing snapshots, external keyword-tool evidence, Sorftime MCP product context, recommendation tracking, and Chinese HTML decision reports. Use when Codex needs to import ASIN ad files, configure profit/ranking thresholds, scrape listings, validate evidence, import SellerSprite/Helium 10/Jungle Scout keyword estimates, fetch Sorftime context, run ad analysis, generate listing copy, or produce HTML reports for bid, negative keyword, search-term promotion, budget, ranking-support, ad-structure, and listing optimization recommendations.
---

# Amazon Ads Optimizer

Use this skill for Amazon AU Sponsored Products optimization where the goal is profit efficiency first, with explicit ranking support separated from profit scaling. Raw search terms, keywords, ASINs, and generated listing copy stay in English. Operator explanations in HTML reports should be Chinese.

## Book Nook Route

For Book Nook, booknook, book nook kit, DIY miniature bookshelf insert, or themed Book Nook products, prefer the dedicated `book-nook-ads-optimizer` skill and `scripts/book_nook_optimizer.py`. That route keeps reusable Book Nook category knowledge, theme profiles, Sorftime context, shared manual scope handling, and the default HTML/Campaign Build CSV/Pre-Negatives CSV/JSON output together.

Legacy single-ASIN HTML and dual-ASIN reports remain available as internal support, but they are not the default Book Nook delivery format.

## Default Sorftime Execution Plan Workflow

For future Amazon AU ad optimization requests, default to the Sorftime execution-plan format when Sorftime MCP is available. Deliver:
- `reports/<scope>_sorftime_launch_plan_<date>.html`
- `reports/<scope>_sorftime_campaign_build_<date>.csv`
- `reports/<scope>_pre_negatives_<date>.csv`
- `configs/<scope>_sorftime_launch_plan_<date>.json`

The HTML should follow the sleep-mask architecture report style: delivery files, budget structure, Sorftime evidence summary, core execution rules, Campaign Build, Pre-Negatives, and Amazon Ads calibration notes. Treat Sorftime keyword/CPC/rank/search-volume/category values as external estimates; final bid scaling, negatives, and expansion must be grounded in Amazon Ads CSV evidence when available.

Use `scripts/render_sorftime_launch_plan.py` for this output. Use legacy single-ASIN HTML reports only as internal analysis support or when the user explicitly asks for the older format.

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
2. Import ad reports named `{start_date}——{end_date}_{asin}_{手动|自动}.csv`:
   `python scripts/import_ad_reports.py data/imports/2026-05-01——06-25_B0GXZQXFM4_手动.csv --db data/amazon_ads.sqlite`
3. Import external keyword evidence from SellerSprite, Helium 10, Jungle Scout, or compatible files:
   `python scripts/import_external_keywords.py keywords.xlsx --tool SellerSprite --mapping mapping.json --captured-date 2026-06-25 --db data/amazon_ads.sqlite`
4. Store Sorftime MCP payloads when available:
   `python scripts/fetch_sorftime_asin.py B0GXZQXFM4 --site AU --db data/amazon_ads.sqlite --payload-json sorftime_payloads.json`
5. Validate evidence:
   `python scripts/validate_evidence.py --db data/amazon_ads.sqlite`
6. Analyze with a config, margin-derived target ACOS, or legacy target ACOS:
   `python scripts/analyze_asin.py B0GXZQXFM4 --target-acos 0.20 --html-output reports/B0GXZQXFM4.html`

## ASIN Evidence-Pack Agent Workflow

Use `scripts/ads_agent_workflow.py` when a task needs durable ASIN-level evidence packs, middle files, or multi-variant scope analysis. The workflow preserves raw evidence, records active versions in SQLite, and writes JSON middle files under `data/asins/<ASIN>/` and `data/scopes/<scope_id>/`.

Default flow:
1. Import uploaded Amazon Ads CSV files with `scripts/import_ad_reports.py`; overlapping ASIN/date/mode imports keep the old version but mark only the newest as active.
2. Store Sorftime MCP payloads with `scripts/fetch_sorftime_asin.py`; older metric snapshots stay in the database while the latest metric version is active.
3. Register a single-ASIN or multi-variant scope and write middle files:
   `python scripts/ads_agent_workflow.py --scope-id BookNook_Library_Group --asin B0AAA11111 --asin B0BBB22222 --shared-id B0AAA11111-B0BBB22222`
4. Use generated middle files for later reports and reviews:
   - `evidence_index.json`
   - `normalized_ad_terms.json`
   - `sorftime_context.json`
   - `opportunity_map.json`
   - `variant_routing_map.json`
   - `decision_log.json`

For parent or multi-variant products, use a `variant_group` scope for 2+ child ASINs. Shared manual or parent-level ad reports remain attached to the group scope unless a clear variant-routing rule or direct ASIN ad evidence supports migrating a term to one child ASIN. Do not double-count shared spend or sales in child ASIN summaries.

## Required Behavior

- Default waste evaluation uses at least 20 clicks plus dynamic allowed test spend: `average_order_value * target_acos` or `selling_price * target_acos`.
- Margin model should compute break-even ACOS and recommended target ACOS when selling price and costs are supplied.
- Classify terms as profit, ranking, exploration, defense, competitor, or irrelevant before recommending action.
- Competitor brand terms may be tested in competitor campaigns but must not be inserted into generated listing copy or backend terms.
- Period-only ad CSVs cannot produce true 7/14/30-day trends; state this clearly in Chinese.
- All third-party keyword/CPC/rank values are sourced estimates, never Amazon Ads truth.
- Corrected or re-uploaded data should supersede the prior active version, not overwrite it. Default analysis should use only active evidence/import versions.

## References

Read `references/data-schema.md` before changing imports or tables. Read `references/optimization-playbook.md` before changing thresholds, margin logic, intent logic, or recommendation logic. Read `references/evidence-standard.md` before using external tool or Sorftime data.
