---
name: book-nook-ads-optimizer
description: Specialized Amazon AU Book Nook advertising optimization using Amazon Ads CSV evidence, Sorftime MCP product/category/keyword/ranking context, reusable Book Nook category knowledge, theme profiles, single-ASIN and variant-group scopes, campaign build CSVs, pre-negatives, and Chinese HTML execution plans. Use when optimizing Book Nook, booknook, book nook kit, miniature library, tavern, garden, Japanese alley, magic, or other Book Nook themed products.
---

# Book Nook Ads Optimizer

Use this skill for Book Nook advertising optimization in Amazon AU. It is the default route for this conversation whenever the product is a Book Nook, booknook, book nook kit, DIY miniature bookshelf insert, or a themed Book Nook variant.

## Evidence Priority

Amazon Ads CSV is the primary performance evidence. Use it for bid changes, budget priority, keyword promotion, negative keyword candidates, and campaign restructuring.

Sorftime evidence is external market context. Use Sorftime product detail, category, market trend, keyword search volume, keyword extensions, search results, and ranking trend to judge market size, competitors, theme fit, and keyword priority. Do not treat Sorftime as Amazon Ads truth.

Listing information is only for advertising word acceptance and theme consistency unless the user explicitly asks for Listing rewrite.

## Default Deliverables

Each run should produce the execution-plan three-pack plus structured JSON:

- HTML execution plan: `reports/<scope>_sorftime_launch_plan_<date>.html`
- Campaign Build CSV: `reports/<scope>_sorftime_campaign_build_<date>.csv`
- Pre-Negatives CSV: `reports/<scope>_pre_negatives_<date>.csv`
- JSON config: `configs/<scope>_sorftime_launch_plan_<date>.json`

Also update the durable Book Nook category knowledge files:

- `configs/book_nook_category_knowledge.json`
- `reports/book_nook_category_knowledge.md`

## Default Workflow

Use `scripts/book_nook_optimizer.py` from the `amazon-ads-optimizer` skill as the stable entry point. It reuses the existing import, evidence-pack, Sorftime launch-plan, and knowledge-base scripts while keeping Book Nook defaults in one place.

1. Import Amazon Ads CSV evidence with active/superseded versioning.
2. Store Sorftime product, keyword, trend, ranking, and search-result payloads when available.
3. Build or load a Book Nook `theme_profile`.
4. Register the scope as single ASIN or variant group.
5. Write middle files under `data/scopes/<scope_id>/intermediate/<run_id>/`.
6. Generate HTML, Campaign Build CSV, Pre-Negatives CSV, and JSON.
7. Append new theme and validated terms to the Book Nook knowledge base without overwriting prior themes.

## Scope Rules

Single ASIN uses `scope_id = ASIN` and `shared_id = null`.

Variant or parent groups use a custom `scope_id` and may include a shared manual ad group. The shared manual group stays shared manual evidence. Do not copy shared manual spend or sales into each child ASIN.

Variant routing rules can recommend an ASIN for theme-specific terms, but shared manual performance must remain in group-level reporting unless direct ASIN evidence supports migration.

## Theme Profile

A `theme_profile` should include:

- `theme_label`: for example `BookNook_Tavern`, `BookNook_Library`, `BookNook_Garden`, `BookNook_Japanese_Alley`, or `BookNook_Magic`.
- `parent_label`: campaign slug label, usually same as `theme_label`.
- `core_terms`: always include `book nook`, `book nook kit`, and `booknook`; add proven conversion terms.
- `theme_longtail_terms`: theme words such as tavern, pub, library, garden, sakura, alley, cat, magic, wizard, or hidden shop.
- `generic_observation_terms`: low-bid broad related terms such as `miniature house kit`, `3d wooden puzzle`, `3d puzzles for adults`, `bookshelf decor`, and `adult craft`.
- `variant_routing_rules`: optional ASIN-level term routing.
- `pre_negative_terms`: long-term category negatives and data-proven waste terms.

Do not leak theme defaults across themes. Library outputs should not inherit Tavern or Japanese longtails unless the context or knowledge base explicitly supplies them.

## Campaign Architecture

The default Book Nook rebuild contains six campaign types:

- `SP_AUTO_Research_<Theme>`: low-bid discovery with close, loose, substitutes, and complements separated.
- `SP_EXACT_Core_<Theme>`: core terms and verified conversion terms.
- `SP_PHRASE_Longtail_<Theme>`: theme-specific longtail terms.
- `SP_PHRASE_Observation_Generic`: broad related terms at low bids.
- `SP_PRODUCT_ASIN_Test_BookNook`: competitor ASIN targeting from Sorftime search results.
- `SP_RANKING_Push_Selected`: only proven terms with controllable ACOS and meaningful search demand.

Default bidding is Dynamic bids - down only, with no Top of Search premium at launch.

## Negative Keyword Rules

Obvious non-category terms such as Kindle, ebook, reading light, furniture, bookcase, and colouring book can be pre-negatives.

Competitor brands such as CUTEBEE, Rolife, LEGO, FUNPOLA, and Cuteroom may be tested in low-bid ads but must not enter Listing or backend terms.

Relevant broad terms such as miniature house kit, 3d wooden puzzle, and bookshelf decor should start in low-bid observation, not immediate negatives.

Data-proven waste terms require Amazon Ads CSV support, normally at least 20 clicks plus a dynamic spend threshold with no order.

## Legacy Boundaries

`render_dual_asin_report.py`, `analyze_asin.py`, and `render_html_report.py` are legacy or internal support for Book Nook work. They should not be the default Book Nook output path.

The Book Nook default path is `scripts/book_nook_optimizer.py` and the Sorftime execution-plan three-pack.
