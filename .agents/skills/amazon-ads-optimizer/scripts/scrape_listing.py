#!/usr/bin/env python3
"""Scrape Amazon AU listing snapshots for ASIN-level ad analysis."""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from contextlib import closing
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"


def _import_schema_helper():
    import importlib.util
    script = Path(__file__).with_name("import_ad_reports.py")
    spec = importlib.util.spec_from_file_location("import_ad_reports", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture_title = False
        self.title_parts: list[str] = []
        self.in_feature_bullets = False
        self.capture_bullet = False
        self.current_bullet: list[str] = []
        self.bullets: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        if attr.get("id") == "productTitle":
            self.capture_title = True
        if attr.get("id") == "feature-bullets":
            self.in_feature_bullets = True
            self.depth = 1
        elif self.in_feature_bullets:
            self.depth += 1
        if self.in_feature_bullets and tag == "span" and "a-list-item" in attr.get("class", ""):
            self.capture_bullet = True
            self.current_bullet = []

    def handle_endtag(self, tag: str) -> None:
        if self.capture_title and tag == "span":
            self.capture_title = False
        if self.capture_bullet and tag == "span":
            text = _clean(" ".join(self.current_bullet))
            if text and not text.lower().startswith("make sure"):
                self.bullets.append(text)
            self.capture_bullet = False
        if self.in_feature_bullets:
            self.depth -= 1
            if self.depth <= 0:
                self.in_feature_bullets = False

    def handle_data(self, data: str) -> None:
        if self.capture_title:
            self.title_parts.append(data)
        if self.capture_bullet:
            self.current_bullet.append(data)


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return cleaned or None


def _match_float(patterns: list[str], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _match_int(patterns: list[str], text: str) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def fetch_html(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept-Language": "en-AU,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_listing(html_text: str) -> dict[str, Any]:
    parser = ProductParser()
    parser.feed(html_text)
    title = _clean(" ".join(parser.title_parts))
    if not title:
        match = re.search(r'<span[^>]+id="productTitle"[^>]*>(.*?)</span>', html_text, re.I | re.S)
        title = _clean(re.sub(r"<.*?>", " ", match.group(1))) if match else None
    price = _match_float([
        r'"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'class="a-offscreen"[^>]*>\$([0-9,]+(?:\.[0-9]+)?)<',
    ], html_text)
    rating = _match_float([
        r'([0-9.]+) out of 5 stars',
        r'"ratingValue"\s*:\s*"?([0-9.]+)',
    ], html_text)
    review_count = _match_int([
        r'id="acrCustomerReviewText"[^>]*>\s*([0-9,]+)',
        r'([0-9,]+) ratings',
    ], html_text)
    return {
        "title": title,
        "bullets": parser.bullets[:8],
        "price": price,
        "rating": rating,
        "review_count": review_count,
    }


def scrape_listing(db_path: str | Path, asin: str, url: str | None = None) -> dict[str, Any]:
    asin = asin.upper()
    product_url = url or f"https://www.amazon.com.au/dp/{asin}"
    schema = _import_schema_helper()
    schema.ensure_schema(db_path)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status = "ok"
    raw_error = None
    try:
        listing = extract_listing(fetch_html(product_url))
        if not listing["title"]:
            status = "partial"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        listing = {"title": None, "bullets": [], "price": None, "rating": None, "review_count": None}
        status = "error"
        raw_error = str(exc)

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
            insert into asins (asin, marketplace, currency, product_url, latest_title, latest_price, updated_at)
            values (?, 'AU', 'AUD', ?, ?, ?, ?)
            on conflict(asin) do update set
                product_url = excluded.product_url,
                latest_title = coalesce(excluded.latest_title, latest_title),
                latest_price = coalesce(excluded.latest_price, latest_price),
                updated_at = excluded.updated_at
            """,
            (asin, product_url, listing["title"], listing["price"], captured_at),
        )
        conn.execute(
            """
            insert into listing_snapshots
            (asin, marketplace, product_url, captured_at, title, bullets_json, price, rating, review_count, extraction_status, raw_error)
            values (?, 'AU', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asin,
                product_url,
                captured_at,
                listing["title"],
                json.dumps(listing["bullets"], ensure_ascii=False),
                listing["price"],
                listing["rating"],
                listing["review_count"],
                status,
                raw_error,
            ),
        )
    return {"asin": asin, "url": product_url, "captured_at": captured_at, "extraction_status": status, **listing}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape an Amazon AU listing snapshot into SQLite.")
    parser.add_argument("asin")
    parser.add_argument("--url")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    print(json.dumps(scrape_listing(args.db, args.asin, args.url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


