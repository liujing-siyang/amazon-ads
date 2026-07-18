# Evidence Standard

## Source Hierarchy

1. Amazon ad CSV exports: direct performance evidence for impressions, clicks, spend, CPC, orders, sales, ACOS, ROAS, and conversion rate.
2. Amazon product page snapshots: direct listing evidence for title, bullets, price when available, rating, and review count.
3. Sorftime MCP data: sourced external product, trend, traffic term, ranking, and review context.
4. External keyword-tool exports such as SellerSprite, Helium 10, and Jungle Scout: estimate evidence for search volume, CPC, competition, organic rank, sponsored rank, and competitor references.
5. Public web research: contextual evidence only unless the page directly contains the relevant product or keyword data.

## Requirements

For every external keyword, CPC, rank, search-volume, competition, Sorftime trend, or review-theme claim, store source name or metric type, source type, source URL/file or query metadata, captured/query date, ASIN/marketplace when relevant, and confidence label.

External keyword-tool rows must be marked as estimates. Do not scale bids based only on external volume or CPC; use them to prioritize review and explain opportunity size.

Sorftime values are not Amazon Ads internal truth. Use them for market context, ranking strategy, listing diagnosis, review-theme extraction, and traffic-term comparison.

When a source is corrected or refreshed, keep the old source and mark it inactive. Default recommendations must use active evidence versions only, while reports may cite superseded versions only when explaining historical changes.

## Recommendation Citation

Every bid, negative, budget, or search-term-promotion recommendation must include metric evidence from imported Amazon CSV rows. Add listing snapshot, external-tool, or Sorftime references only when used in the reason or displayed in the HTML report.
