#!/usr/bin/env python3
"""Import SellerSprite keyword exports as sourced estimate evidence."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"


def _load_importer():
    script = Path(__file__).with_name("import_ad_reports.py")
    spec = importlib.util.spec_from_file_location("import_ad_reports", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _num(value: Any, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if integer else number


def _read_xlsx(path: Path) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    return [dict(zip(headers, row)) for row in rows[1:] if any(v is not None for v in row)]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if file.suffix.lower() == ".xlsx":
        return _read_xlsx(file)
    if file.suffix.lower() == ".csv":
        return _read_csv(file)
    raise ValueError("SellerSprite import supports .xlsx and .csv files")


def _mapped(row: dict[str, Any], mapping: dict[str, str], key: str) -> Any:
    col = mapping.get(key)
    return row.get(col) if col else None


def import_sellersprite(
    db_path: str | Path,
    source_file: str | Path,
    mapping: dict[str, str],
    captured_date: str | None = None,
    source_name: str = "SellerSprite",
) -> dict[str, Any]:
    if "keyword" not in mapping:
        raise ValueError("mapping must include keyword")
    source = Path(source_file)
    captured = captured_date or date.fromtimestamp(source.stat().st_mtime).isoformat()
    rows = read_rows(source)
    _load_importer().ensure_schema(db_path)
    imported = 0
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for row in rows:
            keyword = _mapped(row, mapping, "keyword")
            if keyword is None or str(keyword).strip() == "":
                continue
            conn.execute(
                """
                insert into external_keyword_evidence
                (keyword, source_name, source_type, source_file, captured_date, cpc, search_volume,
                 organic_rank, sponsored_rank, competition, confidence, notes)
                values (?, ?, 'sellersprite_excel', ?, ?, ?, ?, ?, ?, ?, 'estimate', ?)
                """,
                (
                    str(keyword).strip(),
                    source_name,
                    str(source),
                    captured,
                    _num(_mapped(row, mapping, "cpc")),
                    _num(_mapped(row, mapping, "search_volume"), integer=True),
                    _num(_mapped(row, mapping, "organic_rank"), integer=True),
                    _num(_mapped(row, mapping, "sponsored_rank"), integer=True),
                    str(_mapped(row, mapping, "competition") or "").strip() or None,
                    str(_mapped(row, mapping, "notes") or "").strip() or None,
                ),
            )
            imported += 1
    return {"rows_imported": imported, "source_file": str(source), "captured_date": captured}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import SellerSprite Excel/CSV keyword evidence.")
    parser.add_argument("source_file")
    parser.add_argument("--mapping", required=True, help="JSON file or inline JSON mapping canonical fields to column names")
    parser.add_argument("--captured-date")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    mapping_arg = args.mapping
    mapping = json.loads(Path(mapping_arg).read_text(encoding="utf-8-sig") if Path(mapping_arg).exists() else mapping_arg)
    print(json.dumps(import_sellersprite(args.db, args.source_file, mapping, args.captured_date), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

