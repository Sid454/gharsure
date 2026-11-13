"""Rent & bills: deposit tracking, bills raised by the owner, direct UPI payment to the owner.

Nestly never holds money. The tenant pays the owner's own UPI ID (UPI deep link / QR),
enters the UTR reference, and the owner confirms receipt. Everything is kept as a ledger.
"""
import io
import re
import secrets
from datetime import date
from urllib.parse import quote, urlencode

import qrcode
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from . import db

router = APIRouter()
BILL_KINDS = {"rent", "water", "electricity", "maintenance", "other"}
UPI_RE = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$")
UTR_RE = re.compile(r"^[A-Za-z0-9]{8,22}$")


def owner_listing_ids(token: str) -> list[str]:
    with db.connect() as con:
        rows = con.execute("SELECT id FROM listings WHERE owner_token = ?", (token,)).fetchall()
    if not rows:
        raise HTTPException(404, "Invalid owner link")
    return [r["id"] for r in rows]


def owner_tenancy(token: str, tenancy_id: str):
    ids = owner_listing_ids(token)
    with db.connect() as con:
        t = con.execute("SELECT * FROM tenancies WHERE id = ?", (tenancy_id,)).fetchone()
    if not t or t["listing_id"] not in ids:
        raise HTTPException(404, "Tenancy not found")
    return t


def upi_link(t, bill) -> str:
    params = {"pa": t["owner_upi"], "pn": "Owner", "am": f"{bill['amount']:.2f}", "cu": "INR",
              "tn": f"{bill['kind'].title()} {bill['period']}"[:50]}
    return "upi://pay?" + urlencode(params, quote_via=quote)


def ledger(tenancy) -> dict:
    with db.connect() as con:
        bills = [dict(b) for b in con.execute(
            "SELECT * FROM bills WHERE tenancy_id = ? ORDER BY due_date DESC, created_at DESC",
            (tenancy["id"],)).fetchall()]
        listing = con.execute("SELECT title, locality, city, owner_name FROM listings WHERE id = ?",
                              (tenancy["listing_id"],)).fetchone()
    today = date.today().isoformat()
    for b in bills:
        b["overdue"] = b["status"] == "due" and b["due_date"] < today
        if b["status"] != "paid":
            b["upi_link"] = upi_link(tenancy, b)
    return {
        "tenancy": {k: tenancy[k] for k in tenancy.keys() if k != "booking_id"},
        "listing": dict(listing) if listing else None,
        "summary": {
            "deposit_held": tenancy["deposit"] - tenancy["deposit_refunded"],
            "total_paid": sum(b["amount"] for b in bills if b["status"] == "paid"),
            "awaiting_confirmation": sum(b["amount"] for b in bills if b["status"] == "submitted"),
            "total_due": sum(b["amount"] for b in bills if b["status"] == "due"),
            "overdue_count": sum(1 for b in bills if b["overdue"]),
        },
        "bills": bills,
    }


def insert_bill(con, tenancy_id: str, kind: str, period: str, amount: int, due: str, note: str = "") -> str:
    bill_id = secrets.token_hex(5)
    con.execute("INSERT INTO bills (id, tenancy_id, kind, period, amount, due_date, note) VALUES (?,?,?,?,?,?,?)",
                (bill_id, tenancy_id, kind, period, amount, due, note))
    return bill_id


# ---------- owner side ----------

class TenancyIn(BaseModel):
    booking_id: str
    deposit: int = Field(ge=0, le=10_000_000)
    owner_upi: str
    start_date: date

    @field_validator("owner_upi")
    @classmethod
    def check_upi(cls, v: str) -> str:
        v = v.strip()
        if not UPI_RE.match(v):
            raise ValueError("Enter a valid UPI ID, e.g. name@okaxis")
        return v


@router.post("/api/owner/{token}/tenancies")
def start_tenancy(token: str, t: TenancyIn):
    ids = owner_listing_ids(token)
    with db.connect() as con:
        b = con.execute("SELECT * FROM bookings WHERE id = ?", (t.booking_id,)).fetchone()
        if not b or b["listing_id"] not in ids:
            raise HTTPException(404, "Booking not found")
        if b["status"] != "accepted":
            raise HTTPException(400, "Accept the booking before moving the tenant in")
        if con.execute("SELECT 1 FROM tenancies WHERE booking_id = ?", (t.booking_id,)).fetchone():
            raise HTTPException(409, "Tenant already moved in")
        rent = con.execute("SELECT rent FROM listings WHERE id = ?", (b["listing_id"],)).fetchone()["rent"]
        tenancy_id = secrets.token_hex(5)
        con.execute(
            "INSERT INTO tenancies (id, listing_id, booking_id, tenant_name, tenant_phone, rent, deposit, owner_upi,"
            " start_date) VALUES (?,?,?,?,?,?,?,?,?)",
            (tenancy_id, b["listing_id"], b["id"], b["tenant_name"], b["tenant_phone"], rent, t.deposit,
             t.owner_upi, t.start_date.isoformat()))
        con.execute("UPDATE listings SET available = 0 WHERE id = ?", (b["listing_id"],))
        insert_bill(con, tenancy_id, "rent", t.start_date.strftime("%b %Y"), rent, t.start_date.isoformat(),
                    "First month rent")
    return {"tenancy_id": tenancy_id}


class BillIn(BaseModel):
    kind: str
    period: str = Field(min_length=2, max_length=40)
    amount: int = Field(ge=1, le=10_000_000)
    due_date: date
    note: str = Field(default="", max_length=300)

    @field_validator("kind")
    @classmethod
    def check_kind(cls, v: str) -> str:
        if v not in BILL_KINDS:
            raise ValueError(f"kind must be one of {sorted(BILL_KINDS)}")
        return v


@router.post("/api/owner/{token}/tenancies/{tenancy_id}/bills")
def raise_bill(token: str, tenancy_id: str, bill: BillIn):
    t = owner_tenancy(token, tenancy_id)
    if t["status"] != "active":
        raise HTTPException(400, "Tenancy has ended")
    with db.connect() as con:
        bill_id = insert_bill(con, tenancy_id, bill.kind, bill.period.strip(), bill.amount,
                              bill.due_date.isoformat(), bill.note.strip())
    return {"bill_id": bill_id}


@router.post("/api/owner/{token}/bills/{bill_id}/confirm")
def confirm_payment(token: str, bill_id: str):
    ids = owner_listing_ids(token)
    with db.connect() as con:
        cur = con.execute(
            f"UPDATE bills SET status = 'paid', confirmed_at = datetime('now') WHERE id = ? AND status != 'paid'"
            f" AND tenancy_id IN (SELECT id FROM tenancies WHERE listing_id IN ({','.join('?' * len(ids))}))",
            (bill_id, *ids))
    if not cur.rowcount:
        raise HTTPException(404, "Unpaid bill not found")
    return {"status": "paid"}


class DepositRefund(BaseModel):
    amount: int = Field(ge=0)
    end_tenancy: bool = True


@router.post("/api/owner/{token}/tenancies/{tenancy_id}/deposit-refund")
def refund_deposit(token: str, tenancy_id: str, r: DepositRefund):
    t = owner_tenancy(token, tenancy_id)
    if r.amount > t["deposit"]:
        raise HTTPException(400, "Refund cannot exceed the deposit")
    with db.connect() as con:
        con.execute("UPDATE tenancies SET deposit_refunded = ?, status = ? WHERE id = ?",
                    (r.amount, "ended" if r.end_tenancy else t["status"], tenancy_id))
        if r.end_tenancy:
            con.execute("UPDATE listings SET available = 1 WHERE id = ?", (t["listing_id"],))
    return {"deposit_refunded": r.amount}


def owner_tenancies(token: str) -> list[dict]:
    ids = owner_listing_ids(token)
    with db.connect() as con:
        rows = con.execute(
            f"SELECT * FROM tenancies WHERE listing_id IN ({','.join('?' * len(ids))}) ORDER BY created_at DESC",
            ids).fetchall()
    return [ledger(t) for t in rows]


# ---------- tenant side (booking id is the tenant's secret link) ----------

def tenant_tenancy(booking_id: str):
    with db.connect() as con:
        t = con.execute("SELECT * FROM tenancies WHERE booking_id = ?", (booking_id,)).fetchone()
    if not t:
        raise HTTPException(404, "No tenancy yet for this booking")
    return t


@router.get("/api/tenancy/{booking_id}")
def tenant_dashboard(booking_id: str):
    return ledger(tenant_tenancy(booking_id))


class PaidIn(BaseModel):
    utr: str

    @field_validator("utr")
    @classmethod
    def check_utr(cls, v: str) -> str:
        v = v.strip()
        if not UTR_RE.match(v):
            raise ValueError("Enter the 12-digit UPI reference (UTR) from your payment app")
        return v


@router.post("/api/tenancy/{booking_id}/bills/{bill_id}/paid")
def mark_paid(booking_id: str, bill_id: str, p: PaidIn):
    t = tenant_tenancy(booking_id)
    with db.connect() as con:
        cur = con.execute(
            "UPDATE bills SET status = 'submitted', utr = ?, submitted_at = datetime('now')"
            " WHERE id = ? AND tenancy_id = ? AND status = 'due'", (p.utr, bill_id, t["id"]))
    if not cur.rowcount:
        raise HTTPException(404, "Due bill not found")
    return {"status": "submitted"}


@router.get("/api/tenancy/{booking_id}/bills/{bill_id}/qr.png")
def bill_qr(booking_id: str, bill_id: str):
    t = tenant_tenancy(booking_id)
    with db.connect() as con:
        bill = con.execute("SELECT * FROM bills WHERE id = ? AND tenancy_id = ?", (bill_id, t["id"])).fetchone()
    if not bill or bill["status"] == "paid":
        raise HTTPException(404, "Bill not found")
    img = qrcode.make(upi_link(t, bill), box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")
