#!/usr/bin/env python3
"""Validate that non-Amazon keyword evidence is sourced and auditable."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from contextlib import closing
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"


def validate_database(db_path: str | Path) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        missing = conn.execute(
            """
            select count(*) from external_keyword_evidence
            where source_type != 'amazon_ads_csv'
              and (captured_date is null or trim(captured_date) = ''
                   or (source_url is null or trim(source_url) = '')
                      and (source_file is null or trim(source_file) = ''))
            """
        ).fetchone()[0]
        total = conn.execute("select count(*) from external_keyword_evidence").fetchone()[0]
    return {"ok": missing == 0, "total_evidence_rows": total, "missing_sources": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate external keyword/CPC evidence sources.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    result = validate_database(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()


