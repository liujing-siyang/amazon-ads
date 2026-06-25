#!/usr/bin/env python3
"""Track recommendation execution and follow-up state."""
from __future__ import annotations
import argparse, importlib.util, json, sqlite3
from contextlib import closing
from pathlib import Path
DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"

def _load_importer():
    spec=importlib.util.spec_from_file_location('import_ad_reports', Path(__file__).with_name('import_ad_reports.py'))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def record_feedback(db_path, asin, recommendation_id=None, status='planned', action_taken=None, old_bid=None, new_bid=None, campaign=None, ad_group=None, followup_days=14, note=None):
    _load_importer().ensure_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        cur=conn.execute('''insert into recommendation_feedback
        (recommendation_id, asin, status, action_taken, old_bid, new_bid, campaign, ad_group, followup_days, note)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (recommendation_id, asin.upper(), status, action_taken, old_bid, new_bid, campaign, ad_group, followup_days, note))
    return {'id': cur.lastrowid, 'asin': asin.upper(), 'status': status}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('asin'); ap.add_argument('--status', default='planned'); ap.add_argument('--old-bid', type=float); ap.add_argument('--new-bid', type=float); ap.add_argument('--note'); ap.add_argument('--db', default=str(DEFAULT_DB)); a=ap.parse_args()
    print(json.dumps(record_feedback(a.db, a.asin, status=a.status, old_bid=a.old_bid, new_bid=a.new_bid, note=a.note), ensure_ascii=False, indent=2))
if __name__=='__main__': main()
