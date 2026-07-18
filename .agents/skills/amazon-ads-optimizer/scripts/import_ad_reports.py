#!/usr/bin/env python3
"""Import Amazon AU Sponsored Products search term CSV reports into SQLite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"
FILENAME_RE = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2})——(?P<end>(?:\d{4}-)?\d{2}-\d{2})_(?P<asin>[A-Z0-9]{10})_(?P<mode>手动|自动)\.csv$",
    re.IGNORECASE,
)
MODE_MAP = {"手动": "manual", "自动": "automatic"}

SCHEMA = """
create table if not exists asins (
    asin text primary key,
    marketplace text not null default 'AU',
    currency text not null default 'AUD',
    product_url text,
    target_acos real,
    latest_title text,
    latest_price real,
    category text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists listing_snapshots (
    id integer primary key autoincrement,
    asin text not null,
    marketplace text not null default 'AU',
    product_url text not null,
    captured_at text not null,
    title text,
    bullets_json text,
    price real,
    rating real,
    review_count integer,
    extraction_status text not null,
    raw_error text,
    foreign key (asin) references asins(asin)
);

create table if not exists ad_report_imports (
    id integer primary key autoincrement,
    source_id integer,
    scope_id text,
    source_file text not null,
    file_checksum text not null unique,
    asin text not null,
    report_start text not null,
    report_end text not null,
    ad_mode text not null check (ad_mode in ('manual', 'automatic')),
    imported_at text not null,
    rows_imported integer not null,
    is_active integer not null default 1,
    supersedes_import_id integer,
    metadata_json text,
    foreign key (asin) references asins(asin),
    foreign key (source_id) references evidence_sources(id),
    foreign key (supersedes_import_id) references ad_report_imports(id)
);

create table if not exists search_term_performance (
    id integer primary key autoincrement,
    import_id integer not null,
    asin text not null,
    marketplace text not null default 'AU',
    currency text not null default 'AUD',
    report_start text not null,
    report_end text not null,
    ad_mode text not null,
    added_as text,
    search_term text not null,
    keyword text,
    target_bid real,
    impressions integer not null default 0,
    clicks integer not null default 0,
    ctr real,
    spend real not null default 0,
    cpc real,
    orders integer not null default 0,
    sales real not null default 0,
    acos real,
    roas real,
    conversion_rate real,
    raw_json text,
    foreign key (import_id) references ad_report_imports(id),
    foreign key (asin) references asins(asin)
);

create index if not exists idx_search_term_asin_period on search_term_performance(asin, report_start, report_end);
create index if not exists idx_search_term_term on search_term_performance(search_term);

create table if not exists external_keyword_evidence (
    id integer primary key autoincrement,
    keyword text not null,
    source_name text not null,
    source_type text not null,
    source_url text,
    source_file text,
    captured_date text not null,
    cpc real,
    search_volume integer,
    organic_rank integer,
    sponsored_rank integer,
    competition text,
    confidence text not null,
    notes text,
    created_at text not null default current_timestamp
);

create table if not exists recommendations (
    id integer primary key autoincrement,
    asin text not null,
    generated_at text not null,
    action text not null,
    priority text not null,
    search_term text,
    keyword text,
    reason text not null,
    metric_evidence_json text not null,
    source_refs_json text not null,
    status text not null default 'open',
    foreign key (asin) references asins(asin)
);

create table if not exists rule_profiles (
    id integer primary key autoincrement,
    name text not null unique,
    description text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists rule_profile_values (
    id integer primary key autoincrement,
    profile_id integer not null,
    key text not null,
    value_json text not null,
    foreign key (profile_id) references rule_profiles(id),
    unique(profile_id, key)
);

create table if not exists analysis_runs (
    id integer primary key autoincrement,
    asin text not null,
    scope_id text,
    profile_name text not null,
    generated_at text not null,
    config_json text not null,
    summary_json text not null,
    report_path text,
    foreign key (asin) references asins(asin)
);

create table if not exists recommendation_feedback (
    id integer primary key autoincrement,
    recommendation_id integer,
    asin text not null,
    status text not null,
    action_taken text,
    old_bid real,
    new_bid real,
    campaign text,
    ad_group text,
    followup_days integer,
    note text,
    created_at text not null default current_timestamp,
    foreign key (recommendation_id) references recommendations(id)
);

create table if not exists sorftime_snapshots (
    id integer primary key autoincrement,
    source_id integer,
    asin text not null,
    marketplace text not null,
    source_type text not null,
    metric_type text not null,
    query_date text not null,
    payload_json text not null,
    is_active integer not null default 1,
    supersedes_snapshot_id integer,
    created_at text not null default current_timestamp
);

create table if not exists asin_scopes (
    scope_id text primary key,
    scope_type text not null check (scope_type in ('single', 'variant_group', 'parent')),
    marketplace text not null default 'AU',
    parent_asin text,
    member_asins_json text not null,
    shared_ad_group_id text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists evidence_sources (
    id integer primary key autoincrement,
    scope_id text,
    asin text,
    marketplace text not null default 'AU',
    source_type text not null,
    source_name text not null,
    source_file text,
    source_url text,
    checksum text,
    captured_at text not null,
    version integer not null default 1,
    is_active integer not null default 1,
    supersedes_source_id integer,
    metadata_json text,
    created_at text not null default current_timestamp,
    foreign key (scope_id) references asin_scopes(scope_id),
    foreign key (supersedes_source_id) references evidence_sources(id)
);

create table if not exists data_corrections (
    id integer primary key autoincrement,
    source_id integer,
    run_id integer,
    scope_id text,
    asin text,
    table_name text,
    record_id integer,
    field_name text not null,
    old_value_json text,
    new_value_json text not null,
    reason text not null,
    created_at text not null default current_timestamp,
    foreign key (source_id) references evidence_sources(id),
    foreign key (run_id) references analysis_runs(id),
    foreign key (scope_id) references asin_scopes(scope_id)
);

create table if not exists analysis_artifacts (
    id integer primary key autoincrement,
    run_id integer,
    scope_id text,
    asin text,
    artifact_type text not null,
    artifact_path text not null,
    checksum text,
    created_at text not null default current_timestamp,
    metadata_json text,
    foreign key (run_id) references analysis_runs(id),
    foreign key (scope_id) references asin_scopes(scope_id)
);
"""

HEADER_MAP = {
    "已添加为": "added_as",
    "顾客搜索词": "search_term",
    "关键词": "keyword",
    "目标竞价 (AUD)": "target_bid",
    "展示量": "impressions",
    "点击量": "clicks",
    "点击率": "ctr",
    "总成本 (AUD)": "spend",
    "CPC (AUD)": "cpc",
    "购买量": "orders",
    "销售额 (AUD)": "sales",
    "ACOS": "acos",
    "ROAS": "roas",
    "购买率": "conversion_rate",
}
INT_FIELDS = {"impressions", "clicks", "orders"}
FLOAT_FIELDS = {"target_bid", "ctr", "spend", "cpc", "sales", "acos", "roas", "conversion_rate"}


def parse_report_filename(filename: str) -> dict[str, str]:
    name = Path(filename).name
    match = FILENAME_RE.match(name)
    if not match:
        raise ValueError(
            "Expected filename pattern {start_date}——{end_date}_{asin}_{ad_mode}.csv, "
            f"got {name!r}"
        )
    start = match.group("start")
    end = match.group("end")
    if len(end) == 5:
        end = f"{start[:4]}-{end}"
    datetime.strptime(start, "%Y-%m-%d")
    datetime.strptime(end, "%Y-%m-%d")
    return {
        "report_start": start,
        "report_end": end,
        "asin": match.group("asin").upper(),
        "ad_mode": MODE_MAP[match.group("mode")],
    }


def ensure_schema(db_path: str | Path) -> None:
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executescript(SCHEMA)
        for ddl in [
            "alter table ad_report_imports add column source_id integer",
            "alter table ad_report_imports add column scope_id text",
            "alter table ad_report_imports add column is_active integer not null default 1",
            "alter table ad_report_imports add column supersedes_import_id integer",
            "alter table analysis_runs add column scope_id text",
            "alter table recommendation_feedback add column action_taken text",
            "alter table recommendation_feedback add column old_bid real",
            "alter table recommendation_feedback add column new_bid real",
            "alter table recommendation_feedback add column campaign text",
            "alter table recommendation_feedback add column ad_group text",
            "alter table recommendation_feedback add column followup_days integer",
            "alter table sorftime_snapshots add column source_id integer",
            "alter table sorftime_snapshots add column is_active integer not null default 1",
            "alter table sorftime_snapshots add column supersedes_snapshot_id integer",
        ]:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def register_scope(
    conn: sqlite3.Connection,
    scope_id: str,
    scope_type: str,
    member_asins: list[str],
    marketplace: str = "AU",
    parent_asin: str | None = None,
    shared_ad_group_id: str | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        insert into asin_scopes
        (scope_id, scope_type, marketplace, parent_asin, member_asins_json, shared_ad_group_id, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(scope_id) do update set
            scope_type=excluded.scope_type,
            marketplace=excluded.marketplace,
            parent_asin=excluded.parent_asin,
            member_asins_json=excluded.member_asins_json,
            shared_ad_group_id=excluded.shared_ad_group_id,
            updated_at=excluded.updated_at
        """,
        (
            scope_id,
            scope_type,
            marketplace,
            parent_asin,
            json.dumps([a.upper() for a in member_asins], ensure_ascii=False),
            shared_ad_group_id,
            now,
            now,
        ),
    )


def register_evidence_source(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    source_name: str,
    captured_at: str,
    marketplace: str = "AU",
    asin: str | None = None,
    scope_id: str | None = None,
    source_file: str | None = None,
    source_url: str | None = None,
    checksum: str | None = None,
    metadata: dict[str, Any] | None = None,
    supersedes_source_id: int | None = None,
) -> int:
    where = ["source_type = ?", "coalesce(asin, '') = ?", "coalesce(scope_id, '') = ?"]
    params: list[Any] = [source_type, asin or "", scope_id or ""]
    if source_file:
        where.append("source_file = ?")
        params.append(source_file)
    previous_version = conn.execute(
        f"select max(version) from evidence_sources where {' and '.join(where)}",
        params,
    ).fetchone()[0]
    version = int(previous_version or 0) + 1
    if supersedes_source_id:
        conn.execute("update evidence_sources set is_active=0 where id=?", (supersedes_source_id,))
    cur = conn.execute(
        """
        insert into evidence_sources
        (scope_id, asin, marketplace, source_type, source_name, source_file, source_url, checksum,
         captured_at, version, is_active, supersedes_source_id, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            scope_id,
            asin,
            marketplace,
            source_type,
            source_name,
            source_file,
            source_url,
            checksum,
            captured_at,
            version,
            supersedes_source_id,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


def file_checksum(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    if text.endswith("%"):
        text = str(float(text[:-1]) / 100)
    if field in INT_FIELDS:
        return int(float(text))
    if field in FLOAT_FIELDS:
        return float(text)
    return None


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for original, value in row.items():
        key = HEADER_MAP.get((original or "").strip())
        if not key:
            continue
        if key in INT_FIELDS or key in FLOAT_FIELDS:
            normalized[key] = parse_number(value, key)
        else:
            normalized[key] = (value or "").strip() or None
    normalized.setdefault("added_as", None)
    normalized.setdefault("target_bid", None)
    for field in INT_FIELDS:
        normalized[field] = normalized.get(field) or 0
    for field in ("spend", "sales"):
        normalized[field] = normalized.get(field) or 0.0
    return normalized


def read_rows(csv_path: str | Path) -> list[dict[str, Any]]:
    with Path(csv_path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [normalize_row(row) for row in reader]


def import_report(db_path: str | Path, csv_path: str | Path, metadata: dict[str, str] | None = None) -> dict[str, Any]:
    csv_file = Path(csv_path)
    parsed = metadata or parse_report_filename(csv_file.name)
    parsed = dict(parsed)
    parsed["asin"] = parsed["asin"].upper()
    marketplace = str(parsed.get("marketplace") or "AU")
    scope_id = parsed.get("scope_id")
    checksum = file_checksum(csv_file)
    rows = read_rows(csv_file)
    ensure_schema(db_path)
    imported_at = utc_now()

    with closing(sqlite3.connect(db_path)) as conn, conn:
        exists = conn.execute(
            "select id, rows_imported from ad_report_imports where file_checksum = ?",
            (checksum,),
        ).fetchone()
        if exists:
            return {"duplicate": True, "import_id": exists[0], "rows_imported": exists[1]}

        conn.execute(
            """
            insert into asins (asin, marketplace, currency, product_url, updated_at)
            values (?, ?, 'AUD', ?, ?)
            on conflict(asin) do update set updated_at = excluded.updated_at
            """,
            (parsed["asin"], marketplace, f"https://www.amazon.com.au/dp/{parsed['asin']}", imported_at),
        )
        previous = conn.execute(
            """
            select id, source_id from ad_report_imports
            where asin=? and report_start=? and report_end=? and ad_mode=? and coalesce(is_active, 1)=1
            order by id desc limit 1
            """,
            (parsed["asin"], parsed["report_start"], parsed["report_end"], parsed["ad_mode"]),
        ).fetchone()
        supersedes_import_id = previous[0] if previous else None
        supersedes_source_id = previous[1] if previous else None
        if previous:
            conn.execute("update ad_report_imports set is_active=0 where id=?", (previous[0],))
        source_id = register_evidence_source(
            conn,
            source_type="amazon_ads_csv",
            source_name="Amazon Ads CSV",
            source_file=str(csv_file),
            checksum=checksum,
            captured_at=imported_at,
            marketplace=marketplace,
            asin=parsed["asin"],
            scope_id=scope_id,
            metadata=parsed,
            supersedes_source_id=supersedes_source_id,
        )
        cur = conn.execute(
            """
            insert into ad_report_imports
            (source_id, scope_id, source_file, file_checksum, asin, report_start, report_end, ad_mode,
             imported_at, rows_imported, is_active, supersedes_import_id, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                source_id,
                scope_id,
                str(csv_file),
                checksum,
                parsed["asin"],
                parsed["report_start"],
                parsed["report_end"],
                parsed["ad_mode"],
                imported_at,
                len(rows),
                supersedes_import_id,
                json.dumps(parsed, ensure_ascii=False),
            ),
        )
        import_id = cur.lastrowid
        for row in rows:
            conn.execute(
                """
                insert into search_term_performance
                (import_id, asin, report_start, report_end, ad_mode, added_as, search_term, keyword, target_bid,
                 impressions, clicks, ctr, spend, cpc, orders, sales, acos, roas, conversion_rate, raw_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    parsed["asin"],
                    parsed["report_start"],
                    parsed["report_end"],
                    parsed["ad_mode"],
                    row.get("added_as"),
                    row.get("search_term") or "",
                    row.get("keyword"),
                    row.get("target_bid"),
                    row.get("impressions", 0),
                    row.get("clicks", 0),
                    row.get("ctr"),
                    row.get("spend", 0.0),
                    row.get("cpc"),
                    row.get("orders", 0),
                    row.get("sales", 0.0),
                    row.get("acos"),
                    row.get("roas"),
                    row.get("conversion_rate"),
                    json.dumps(row, ensure_ascii=False),
                ),
            )
    return {"duplicate": False, "import_id": import_id, "rows_imported": len(rows), **parsed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Amazon Ads CSV reports into SQLite.")
    parser.add_argument("csv_files", nargs="+", help="CSV files named {start}——{end}_{asin}_{手动|自动}.csv")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    args = parser.parse_args()
    results = [import_report(args.db, path) for path in args.csv_files]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()




