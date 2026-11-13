"""Accounts: sign up / sign in with phone + password. One account works in Owner and Renter mode.

Passwords are hashed with salted scrypt. Sessions are random bearer tokens.
Signed-in owners get one owner_token shared by all their listings, so the owner dashboard
shows every flat they own. Signed-in renters get their bookings and roommate profile saved.
"""
import hashlib
import hmac
import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import db

router = APIRouter()


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except ValueError:
        return False


def current_account(authorization: str | None):
    """Return the signed-in account row, or None for guests."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    with db.connect() as con:
        return con.execute("SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token = ?",
                           (token,)).fetchone()


def require_account(authorization: str | None):
    acc = current_account(authorization)
    if not acc:
        raise HTTPException(401, "Please sign in")
    return acc


def _new_session(account_id: str) -> str:
    token = secrets.token_urlsafe(24)
    with db.connect() as con:
        con.execute("INSERT INTO sessions (token, account_id) VALUES (?, ?)", (token, account_id))
    return token


class SignupIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str
    password: str = Field(min_length=6, max_length=128)
    mode: Literal["owner", "renter"]


class LoginIn(BaseModel):
    phone: str
    password: str


@router.post("/api/auth/signup")
def signup(s: SignupIn):
    phone = db.normalize_phone(s.phone)
    if len(phone) != 10:
        raise HTTPException(400, "Enter a valid 10-digit phone number")
    acc_id = secrets.token_hex(6)
    with db.connect() as con:
        if con.execute("SELECT 1 FROM accounts WHERE phone = ?", (phone,)).fetchone():
            raise HTTPException(409, "An account with this phone already exists. Please sign in.")
        con.execute("INSERT INTO accounts (id, name, phone, pw_hash, default_mode, owner_token) VALUES (?,?,?,?,?,?)",
                    (acc_id, s.name.strip(), phone, hash_password(s.password), s.mode, secrets.token_urlsafe(16)))
    return {"session": _new_session(acc_id)}


@router.post("/api/auth/login")
def login(body: LoginIn):
    with db.connect() as con:
        acc = con.execute("SELECT * FROM accounts WHERE phone = ?", (db.normalize_phone(body.phone),)).fetchone()
    if not acc or not verify_password(body.password, acc["pw_hash"]):
        raise HTTPException(401, "Wrong phone number or password")
    return {"session": _new_session(acc["id"])}


@router.post("/api/auth/logout")
def logout(authorization: str | None = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token = ?", (authorization.removeprefix("Bearer ").strip(),))
    return {"ok": True}


@router.get("/api/auth/me")
def me(authorization: str | None = Header(None)):
    acc = require_account(authorization)
    with db.connect() as con:
        has_listings = con.execute("SELECT COUNT(*) FROM listings WHERE owner_token = ?",
                                   (acc["owner_token"],)).fetchone()[0]
        bookings = con.execute(
            "SELECT b.id, b.status, b.visit_date, b.move_in_date, l.title, l.locality, l.city, l.rent,"
            " (SELECT 1 FROM tenancies t WHERE t.booking_id = b.id) AS moved_in"
            " FROM account_bookings ab JOIN bookings b ON b.id = ab.booking_id JOIN listings l ON l.id = b.listing_id"
            " WHERE ab.account_id = ? ORDER BY b.created_at DESC", (acc["id"],)).fetchall()
    return {"id": acc["id"], "name": acc["name"], "phone": acc["phone"], "default_mode": acc["default_mode"],
            "owner_token": acc["owner_token"], "listings": has_listings, "roommate_token": acc["roommate_token"],
            "bookings": [dict(b) for b in bookings]}


def link_booking(account_id: str, booking_id: str) -> None:
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO account_bookings VALUES (?, ?)", (account_id, booking_id))


def set_roommate_token(account_id: str, token: str) -> None:
    with db.connect() as con:
        con.execute("UPDATE accounts SET roommate_token = ? WHERE id = ?", (token, account_id))
