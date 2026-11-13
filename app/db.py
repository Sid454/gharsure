"""SQLite storage for listings, photo fingerprints, scam reports and inquiries."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RENTSHIELD_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "rentshield.db"
UPLOAD_DIR = DATA_DIR / "uploads"
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
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


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
        row = con.execute("SELECT COUNT(*) FROM reports WHERE phone_hash = ?", (hash_phone(phone),)).fetchone()
    return row[0]


def add_report(phone: str, reason: str, listing_id: str | None = None) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO reports (phone_hash, reason, listing_id) VALUES (?, ?, ?)",
            (hash_phone(phone), reason, listing_id),
        )


def save_fingerprint(image_id, listing_id, source, city, path, phashes, dhashes) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO fingerprints VALUES (?, ?, ?, ?, ?, ?, ?)",
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
