# Data Schema And Import Rules

## Filename Convention

Expected CSV filename: `{start_date}——{end_date}_{asin}_{ad_mode}.csv`.

Examples:
- `2026-05-01——06-25_B0GXZQXFM4_手动.csv`
- `2026-05-01——2026-06-25_B0GXZQXFM4_自动.csv`

Reject malformed names unless explicit metadata is provided by the user.

## Main Tables

- `asins`: ASIN master data, marketplace, currency, product URL, target ACOS, latest title/price/category.
- `asin_scopes`: single-ASIN, parent, or multi-variant scope registry. `variant_group` supports 2+ child ASINs plus an optional shared manual/parent ad group id.
- `evidence_sources`: versioned evidence index for uploaded files, Sorftime MCP captures, web snapshots, external tools, and user assumptions. Only active versions are used by default analysis.
- `listing_snapshots`: scraped Amazon listing title, bullets, price, rating, review count, extraction status, URL, and captured timestamp.
- `ad_report_imports`: imported source file, checksum, ASIN/scope, date range, ad mode, import timestamp, row count, active flag, and superseded import id.
- `search_term_performance`: normalized search-term metrics from Amazon ad CSV reports.
- `external_keyword_evidence`: external keyword-tool estimates with canonical fields for keyword, search volume, estimated CPC, competition, organic rank, sponsored rank, competitor ASIN/brand, source tool, source file/URL, and source date.
- `sorftime_snapshots`: Sorftime MCP payloads by ASIN, marketplace, metric type, query date, source type, JSON payload, active flag, and superseded snapshot id.
- `recommendations`: generated actions with metric evidence and source references.
- `rule_profiles`: named optimization rule sets.
- `rule_profile_values`: JSON-encoded settings for a rule profile.
- `analysis_runs`: persisted analysis run metadata, config, and summary.
- `analysis_artifacts`: generated HTML/CSV/JSON/middle-file manifest with path and checksum.
- `data_corrections`: auditable manual or automated corrections, with old/new values and reason.
- `recommendation_feedback`: recommendation status tracking with status, execution date, action taken, old bid, new bid, campaign, ad group, follow-up window, and notes.

## Versioning Rules

- Re-uploading an Amazon Ads report for the same ASIN, report start/end, and ad mode should mark the prior import inactive and insert a new active version.
- Re-fetching a Sorftime metric for the same ASIN/marketplace/metric type should mark the prior metric snapshot inactive and insert a new active version.
- Do not delete superseded rows. They remain available for audit, backtesting, and explaining why prior recommendations changed.
- Default analysis and report builders must filter to active imports/snapshots unless the user explicitly asks for historical backtesting.

## ASIN And Scope Data Packs

Single ASIN evidence lives under:

- `data/asins/<ASIN>/raw/uploads/`
- `data/asins/<ASIN>/raw/sorftime/<date>/`
- `data/asins/<ASIN>/raw/web/<date>/`
- `data/asins/<ASIN>/intermediate/<run_id>/`
- `data/asins/<ASIN>/corrections/`
- `data/asins/<ASIN>/reports/`

Multi-variant or shared-ad evidence lives under:

- `data/scopes/<scope_id>/members.json`
- `data/scopes/<scope_id>/shared_ad_reports/`
- `data/scopes/<scope_id>/intermediate/<run_id>/`
- `data/scopes/<scope_id>/reports/`

Each agent run should write these middle files when applicable: `evidence_index.json`, `normalized_ad_terms.json`, `sorftime_context.json`, `opportunity_map.json`, `variant_routing_map.json`, and `decision_log.json`.

## CSV Headers

Automatic reports support: `顾客搜索词`, `关键词`, `展示量`, `点击量`, `点击率`, `总成本 (AUD)`, `CPC (AUD)`, `购买量`, `销售额 (AUD)`, `ACOS`, `ROAS`, `购买率`.

Manual reports also support: `已添加为`, `目标竞价 (AUD)`.

## External Keyword Mapping

Use `scripts/import_external_keywords.py` for SellerSprite, Helium 10, Jungle Scout, or future keyword files. Canonical mapping fields: `keyword` required; optional fields are `search_volume`, `estimated_cpc` or `cpc`, `competition`, `organic_rank`, `sponsored_rank`, `competitor_asin`, `competitor_brand`, and `notes`. Store rows as sourced estimates.

## Sorftime Storage

Store Sorftime payloads as external market/product context in `sorftime_snapshots`. Metric types should distinguish product detail/report, product trend, traffic terms, keyword ranking trend, and reviews.
