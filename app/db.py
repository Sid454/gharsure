"""Storage layer. Same code runs on two databases:

- SQLite  (default): local development and the demo (file in data/).
- PostgreSQL (when DATABASE_URL is set): production, e.g. a free Supabase/Neon database,
  so listings, accounts, bills and PHOTOS survive server restarts.

App code writes SQLite-style SQL with `?` placeholders; for Postgres it is translated here.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RENTSHIELD_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "rentshield.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
PHONE_SALT = os.environ.get("RENTSHIELD_PHONE_SALT", "rentshield-dev-salt")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    city TEXT NOT NULL,
    locality TEXT NOT NULL,
    bhk INTEGER NOT NULL,
    sqft INTEGER NOT NULL,
    furnishing TEXT NOT NULL,
    rent INTEGER NOT NULL,
    description TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    owner_phone TEXT NOT NULL,
    owner_token TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,   -- 1 = vacant, 0 = rented out
    risk_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    risk_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS photos (
    listing_id TEXT NOT NULL,
    n INTEGER NOT NULL,
    data BLOB NOT NULL,                      -- re-encoded JPEG (EXIF stripped)
    PRIMARY KEY (listing_id, n)
);
CREATE TABLE IF NOT EXISTS fingerprints (
    image_id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'owner' (posted here) or 'reference' (seen elsewhere)
    city TEXT,
    path TEXT,
    phashes TEXT NOT NULL,
    dhashes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    listing_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    tenant_name TEXT NOT NULL,
    tenant_phone TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    move_in_date TEXT NOT NULL,
    occupants INTEGER NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / accepted / declined / cancelled
    owner_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tenancies (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    booking_id TEXT NOT NULL UNIQUE,      -- tenant opens their dashboard with this secret id
    tenant_name TEXT NOT NULL,
    tenant_phone TEXT NOT NULL,
    rent INTEGER NOT NULL,
    deposit INTEGER NOT NULL,
    deposit_refunded INTEGER NOT NULL DEFAULT 0,
    owner_upi TEXT NOT NULL,
    start_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',   -- active / ended
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,                 -- scrypt, salted
    default_mode TEXT NOT NULL,            -- owner / renter
    owner_token TEXT NOT NULL UNIQUE,      -- all of this account's listings share it
    roommate_token TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS account_bookings (
    account_id TEXT NOT NULL,
    booking_id TEXT NOT NULL,
    PRIMARY KEY (account_id, booking_id)
);
CREATE TABLE IF NOT EXISTS roommates (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,            -- private link to manage the profile
    data TEXT NOT NULL,                    -- JSON profile (habits, budget, interests...)
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS roommate_requests (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / accepted / declined
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (from_id, to_id)
);
CREATE TABLE IF NOT EXISTS bills (
    id TEXT PRIMARY KEY,
    tenancy_id TEXT NOT NULL,
    kind TEXT NOT NULL,                     -- rent / water / electricity / maintenance / other
    period TEXT NOT NULL,
    amount INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'due',     -- due / submitted (tenant paid) / paid (owner confirmed)
    utr TEXT,
    submitted_at TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_listings_owner ON listings (owner_token);
CREATE INDEX IF NOT EXISTS idx_listings_city ON listings (city, available);
CREATE INDEX IF NOT EXISTS idx_bookings_listing ON bookings (listing_id);
CREATE INDEX IF NOT EXISTS idx_bills_tenancy ON bills (tenancy_id);
CREATE INDEX IF NOT EXISTS idx_reports_phone ON reports (phone_hash);
"""

# ---------- SQLite -> PostgreSQL translation ----------
PG_NOW = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


def _pg_sql(sql: str) -> str:
    return sql.replace("%", "%%").replace("?", "%s").replace("datetime('now')", PG_NOW)


def _pg_schema(schema: str) -> str:
    return (schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                  .replace(" REAL ", " DOUBLE PRECISION ").replace(" BLOB ", " BYTEA ")
                  .replace("DEFAULT (datetime('now'))", f"DEFAULT ({PG_NOW})"))


class Row(dict):
    """dict that also supports row[0], like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _PgConnection:
    """Wraps a psycopg connection so app code can keep using `?` and con.execute(...)."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql: str, params=()):
        return self._con.execute(_pg_sql(sql), tuple(params))

    def executescript(self, script: str):
        self._con.execute(script)


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        def row_factory(cursor):
            make = dict_row(cursor)
            return lambda values: Row(make(values))

        # prepare_threshold=None keeps it compatible with PgBouncer / Supabase's pooler
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=int(os.environ.get("DB_POOL_SIZE", "5")),
                               kwargs={"row_factory": row_factory, "prepare_threshold": None}, open=True)
    return _pool


# Columns added after the first release. Applied on startup, so old databases upgrade in place.
MIGRATIONS = [
    ("listings", "kind", "TEXT NOT NULL DEFAULT 'owner'"),       # owner / vacating (tenant leaving) / flatmate
    ("listings", "available_from", "TEXT"),
    ("listings", "spots", "INTEGER NOT NULL DEFAULT 1"),         # flatmate: how many people wanted
    ("listings", "pref_gender", "TEXT NOT NULL DEFAULT 'any'"),
    ("listings", "rent_share", "INTEGER"),                       # flatmate: rent per new person
    ("listings", "owner_contact_name", "TEXT"),                  # vacating: real owner, only with consent
    ("listings", "owner_contact_phone", "TEXT"),
]


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(_pg_schema(SCHEMA) if IS_POSTGRES else SCHEMA)
        for table, column, decl in MIGRATIONS:
            if IS_POSTGRES:
                con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}")
            else:
                existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
                if column not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


@contextmanager
def connect():
    if IS_POSTGRES:
        with _get_pool().connection() as pg:   # commits on success, rolls back on error
            yield _PgConnection(pg)
        return
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def backend() -> str:
    return "postgres" if IS_POSTGRES else "sqlite"


# ---------- helpers ----------

def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def hash_phone(phone: str) -> str:
    """Phones are stored only as salted hashes in the reports table."""
    return hashlib.sha256((PHONE_SALT + normalize_phone(phone)).encode()).hexdigest()


def count_reports(phone: str) -> int:
    if not normalize_phone(phone):
        return 0
    with connect() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM reports WHERE phone_hash = ?", (hash_phone(phone),)).fetchone()
    return row["n"]


def add_report(phone: str, reason: str, listing_id: str | None = None) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO reports (phone_hash, reason, listing_id) VALUES (?, ?, ?)",
            (hash_phone(phone), reason, listing_id),
        )


def save_fingerprint(image_id, listing_id, source, city, path, phashes, dhashes) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO fingerprints (image_id, listing_id, source, city, path, phashes, dhashes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (image_id) DO UPDATE SET"
            " listing_id = excluded.listing_id, source = excluded.source, city = excluded.city,"
            " path = excluded.path, phashes = excluded.phashes, dhashes = excluded.dhashes",
            (image_id, listing_id, source, city, path,
             json.dumps([str(h) for h in phashes]), json.dumps([str(h) for h in dhashes])),
        )


def all_fingerprints():
    with connect() as con:
        rows = con.execute("SELECT * FROM fingerprints").fetchall()
    for r in rows:
        yield (r["image_id"], r["listing_id"], [int(h) for h in json.loads(r["phashes"])],
               [int(h) for h in json.loads(r["dhashes"])])


def fingerprint_meta(image_id: str):
    with connect() as con:
        return con.execute(
            "SELECT f.*, l.title, l.locality FROM fingerprints f "
            "LEFT JOIN listings l ON l.id = f.listing_id WHERE f.image_id = ?",
            (image_id,),
        ).fetchone()


def save_photo_bytes(listing_id: str, n: int, data: bytes) -> None:
    with connect() as con:
        con.execute("INSERT INTO photos (listing_id, n, data) VALUES (?, ?, ?)"
                    " ON CONFLICT (listing_id, n) DO UPDATE SET data = excluded.data", (listing_id, n, data))


def load_photo_bytes(listing_id: str, n: int) -> bytes | None:
    with connect() as con:
        row = con.execute("SELECT data FROM photos WHERE listing_id = ? AND n = ?", (listing_id, n)).fetchone()
    return bytes(row["data"]) if row else None


def close() -> None:
    """Close the Postgres pool on shutdown (no-op for SQLite)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
