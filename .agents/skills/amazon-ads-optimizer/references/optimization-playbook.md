# Optimization Playbook

Use a configurable rule profile for every analysis. Defaults are conservative and profit-first.

## Default Rule Settings

- `target_acos`: 0.20 unless a margin model derives a lower recommended target.
- `wasted_click_threshold`: 20.
- `wasted_spend_threshold`: 5.0 AUD fallback only when no selling price, AOV, or dynamic spend is available.
- `allowed_test_spend`: `average_order_value * target_acos`; if a margin model has `selling_price`, use `selling_price * target_acos`.
- `estimated_test_clicks`: `allowed_test_spend / avg_cpc` when avg CPC is known.
- `min_orders_to_scale`: 2.
- `scale_acos_headroom`: 0.75.
- `ranking_acos_tolerance`: 2.0.
- `lookback_days`: 0, meaning all imported data.
- `keyword_gap_min_token_length`: 4.

## Margin Model

Inputs: selling price, product cost, FBA fee, referral fee, shipping/packaging, return allowance, other cost, and desired profit buffer.

Definitions:
- `break_even_acos = (selling_price - non_ad_costs) / selling_price`.
- `recommended_target_acos = break_even_acos - desired_profit_buffer`.
- Use the margin-derived target ACOS unless the user explicitly provides a target ACOS.

## Intent Classes

- `profit`: converting and at/below target ACOS.
- `ranking`: converting but above profit target.
- `exploration`: relevant-looking term without enough conversion evidence.
- `defense`: own brand or product-defense term.
- `competitor`: competitor brand or ASIN-related term.
- `irrelevant`: term that should not be scaled and may be negative if thresholds are met.

Intent controls ACOS tolerance and campaign placement. Competitor terms are excluded from listing copy and routed to competitor tests.

## Profit Scaling

Promote a search term to manual exact or phrase when it has orders and ACOS at or below target ACOS, especially when it came from automatic targeting or broad discovery sources.

Consider cautious bid or budget increases when a term has at least `min_orders_to_scale` orders and ACOS is below `target_acos * scale_acos_headroom`.

## Waste Reduction

Add a negative keyword or reduce bid only when a term has no orders, clicks are at least `wasted_click_threshold`, and spend is at least `allowed_test_spend`. Add negatives only when the term is irrelevant; reduce bid when relevance is plausible.

## Ranking Support

If a term converts but is above target ACOS, keep it as ranking support only while ACOS is within `target_acos * ranking_acos_tolerance`. If it exceeds that tolerance, recommend bid reduction or isolation into a controlled ranking test.

## Trends

Use daily or segmented ad data for real 7/14/30-day trend calculations. If imported ad files only provide whole-period rows, report that trend analysis is period-level only. Sorftime product trend data can add product sales, sales amount, price, and rank context.

## Ad Structure

Generate a plan with these roles when evidence supports it: automatic exploration, manual exact core terms, manual phrase expansion, competitor keyword/ASIN test, brand defense, and ranking push.

## Nexscope Campaign Blueprint Controls

Use these optional controls when the task is campaign creation, channel strategy, or pre-launch structure rather than only CSV optimization:

- `campaign_mode`: `build` for new campaign blueprints, `optimize` for existing campaign audits, or `mixed` when launch structure and historical CSV evidence both matter.
- `ad_channel_scope`: `sp`, `sb`, `sd`, or `mixed`. Default to `sp` for this project unless the user explicitly asks for Sponsored Brands or Display.
- `negative_keyword_policy`: seed negatives, cross-campaign isolation, negative exact for proven wrong terms, and negative phrase for broad irrelevant modifiers.
- `campaign_blueprint_inputs`: ASIN, marketplace, product type, selling price, margin model, launch/mature stage, monthly budget, priority keywords, competitor ASINs, and source references.

For new launches, structure Sponsored Products with Auto -> Broad/Phrase -> Exact migration and competitor ASIN tests when competitor targets are sourced. Add migrated winners as negatives in the source campaign to reduce internal competition.

Sponsored Products, Sponsored Brands, and Sponsored Display should be discussed as separate budget layers:
- Sponsored Products: default launch and optimization layer; use CSV/Sorftime evidence whenever available.
- Sponsored Brands: optional brand/search expansion layer; only recommend when brand assets and storefront readiness are known.
- Sponsored Display: optional retargeting, competitor-page, or audience layer; do not treat it as a default beginner-seller requirement.

Display and SB guidance must stay strategic unless the project has matching data exports. Do not invent bid landscapes, audience sizes, or conversion rates.

## Listing Optimization

Score ad-to-listing fit from title coverage, bullet coverage, converting-term coverage, rating/review count, price availability, benefit clarity, and keyword gaps. Generate English title, five bullets, long description, and backend search terms. Explain changes in Chinese.
