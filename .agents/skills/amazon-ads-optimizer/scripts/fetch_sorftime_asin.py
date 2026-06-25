#!/usr/bin/env python3
"""Store Sorftime MCP payloads for ASIN analysis."""
from __future__ import annotations
import argparse, importlib.util, json, sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"

def _load_importer():
    spec=importlib.util.spec_from_file_location('import_ad_reports', Path(__file__).with_name('import_ad_reports.py'))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def store_sorftime_payloads(db_path: str|Path, asin: str, marketplace: str, payloads: dict[str, Any], query_date: str|None=None):
    _load_importer().ensure_schema(db_path)
    qd=query_date or date.today().isoformat(); count=0
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for metric_type, payload in payloads.items():
            conn.execute('''insert into sorftime_snapshots (asin, marketplace, source_type, metric_type, query_date, payload_json)
                            values (?, ?, 'sorftime_mcp', ?, ?, ?)''', (asin.upper(), marketplace, metric_type, qd, json.dumps(payload, ensure_ascii=False)))
            count += 1
    return {'rows_stored': count, 'asin': asin.upper(), 'marketplace': marketplace, 'query_date': qd}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('asin'); ap.add_argument('--site', default='AU'); ap.add_argument('--payload-json'); ap.add_argument('--db', default=str(DEFAULT_DB)); a=ap.parse_args()
    payloads=json.loads(Path(a.payload_json).read_text(encoding='utf-8-sig')) if a.payload_json else {}
    print(json.dumps(store_sorftime_payloads(a.db, a.asin, a.site, payloads), ensure_ascii=False, indent=2))
if __name__=='__main__': main()
