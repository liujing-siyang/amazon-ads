# Data Schema And Import Rules

## Filename Convention

Expected CSV filename: `{start_date}??{end_date}_{asin}_{ad_mode}.csv`.

Examples:
- `2026-05-01??06-25_B0GXZQXFM4_??.csv`
- `2026-05-01??2026-06-25_B0GXZQXFM4_??.csv`

Reject malformed names unless explicit metadata is provided by the user.

## Main Tables

- `asins`: ASIN master data, marketplace, currency, product URL, target ACOS, latest title/price/category.
- `listing_snapshots`: scraped Amazon listing title, bullets, price, rating, review count, extraction status, URL, and captured timestamp.
- `ad_report_imports`: imported source file, checksum, ASIN, date range, ad mode, import timestamp, and row count.
- `search_term_performance`: normalized search-term metrics from Amazon ad CSV reports.
- `external_keyword_evidence`: external keyword-tool estimates with canonical fields for keyword, search volume, estimated CPC, competition, organic rank, sponsored rank, competitor ASIN/brand, source tool, source file/URL, and source date.
- `sorftime_snapshots`: Sorftime MCP payloads by ASIN, marketplace, metric type, query date, source type, and JSON payload.
- `recommendations`: generated actions with metric evidence and source references.
- `rule_profiles`: named optimization rule sets.
- `rule_profile_values`: JSON-encoded settings for a rule profile.
- `analysis_runs`: persisted analysis run metadata, config, and summary.
- `recommendation_feedback`: recommendation status tracking with status, execution date, action taken, old bid, new bid, campaign, ad group, follow-up window, and notes.

## CSV Headers

Automatic reports support: `?????`, `???`, `???`, `???`, `???`, `??? (AUD)`, `CPC (AUD)`, `???`, `??? (AUD)`, `ACOS`, `ROAS`, `???`.

Manual reports also support: `????`, `???? (AUD)`.

## External Keyword Mapping

Use `scripts/import_external_keywords.py` for SellerSprite, Helium 10, Jungle Scout, or future keyword files. Canonical mapping fields: `keyword` required; optional fields are `search_volume`, `estimated_cpc` or `cpc`, `competition`, `organic_rank`, `sponsored_rank`, `competitor_asin`, `competitor_brand`, and `notes`. Store rows as sourced estimates.

## Sorftime Storage

Store Sorftime payloads as external market/product context in `sorftime_snapshots`. Metric types should distinguish product detail/report, product trend, traffic terms, keyword ranking trend, and reviews.
