#!/usr/bin/env python3
"""Import mapped external keyword-tool exports as sourced estimate evidence."""
from __future__ import annotations
import argparse, csv, importlib.util, json, sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"

def _load_importer():
    spec=importlib.util.spec_from_file_location('import_ad_reports', Path(__file__).with_name('import_ad_reports.py'))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def _num(v: Any, integer: bool=False):
    if v is None: return None
    t=str(v).strip().replace(',','').replace('$','')
    if not t: return None
    try: n=float(t)
    except ValueError: return None
    return int(n) if integer else n

def _rows(path: Path):
    if path.suffix.lower()=='.xlsx':
        import openpyxl
        wb=openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws=wb.active; data=list(ws.iter_rows(values_only=True))
        finally: wb.close()
        if not data: return []
        headers=[str(h).strip() if h is not None else '' for h in data[0]]
        return [dict(zip(headers,r)) for r in data[1:] if any(v is not None for v in r)]
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def import_external_keywords(db_path: str|Path, source_file: str|Path, tool: str, mapping: dict[str,str], captured_date: str|None=None):
    if 'keyword' not in mapping: raise ValueError('mapping must include keyword')
    src=Path(source_file); captured=captured_date or date.fromtimestamp(src.stat().st_mtime).isoformat()
    _load_importer().ensure_schema(db_path)
    count=0
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for row in _rows(src):
            kw=row.get(mapping['keyword'])
            if kw is None or str(kw).strip()=='': continue
            conn.execute('''insert into external_keyword_evidence
            (keyword, source_name, source_type, source_file, captured_date, cpc, search_volume, organic_rank, sponsored_rank, competition, confidence, notes)
            values (?, ?, 'external_keyword_tool', ?, ?, ?, ?, ?, ?, ?, 'estimate', ?)''', (
                str(kw).strip(), tool, str(src), captured,
                _num(row.get(mapping.get('estimated_cpc') or mapping.get('cpc'))),
                _num(row.get(mapping.get('search_volume')), True),
                _num(row.get(mapping.get('organic_rank')), True),
                _num(row.get(mapping.get('sponsored_rank')), True),
                str(row.get(mapping.get('competition')) or '').strip() or None,
                str(row.get(mapping.get('notes')) or '').strip() or None,
            ))
            count += 1
    return {'rows_imported': count, 'source_file': str(src), 'source_tool': tool, 'captured_date': captured}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('source_file'); ap.add_argument('--tool', required=True); ap.add_argument('--mapping', required=True); ap.add_argument('--captured-date'); ap.add_argument('--db', default=str(DEFAULT_DB)); a=ap.parse_args()
    mapping=json.loads(Path(a.mapping).read_text(encoding='utf-8-sig') if Path(a.mapping).exists() else a.mapping)
    print(json.dumps(import_external_keywords(a.db, a.source_file, a.tool, mapping, a.captured_date), ensure_ascii=False, indent=2))
if __name__=='__main__': main()
