"""Nestly (RentShield AI engine) - FastAPI backend.

Owners list flats directly, tenants browse a map / cards and book visits like a hotel,
and every listing passes through the AI scam-risk engine.
"""
import io
import json
import secrets
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, field_validator

from . import auth, db, imaging, roommates, tenancy
from .assistant import Assistant
from .rent_model import CITY_CENTERS, LOCALITIES, MODEL_PATH as RENT_MODEL, RentModel, generate_sample_data, RENT_CSV
from .risk import ListingInput, analyze
from .text_model import MODEL_PATH as TEXT_MODEL, ScamTextModel

MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 8 * 1024 * 1024
FURNISHING = {"unfurnished", "semi-furnished", "furnished"}
STATE: dict = {}


def load_models() -> None:
    if not RENT_CSV.exists():
        generate_sample_data()
    if not RENT_MODEL.exists():
        RentModel.train().save()
    if not TEXT_MODEL.exists():
        ScamTextModel.train().save()
    STATE["rent"] = RentModel.load()
    STATE["text"] = ScamTextModel.load()
    STATE["assistant"] = Assistant()


def rebuild_index() -> None:
    imaging.index_reset()
    for image_id, listing_id, ph, dh in db.all_fingerprints():
        imaging.index_add(listing_id, image_id, ph, dh)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    load_models()
    rebuild_index()
    yield


app = FastAPI(title="Nestly API", version="0.1.0", lifespan=lifespan)
app.include_router(tenancy.router)
app.include_router(roommates.router)
app.include_router(auth.router)
db.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=db.UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=db.ROOT / "static"), name="static")


# ---------- helpers ----------

async def read_photos(photos: list[UploadFile] | None) -> list[bytes]:
    photos = [p for p in (photos or []) if p.filename]
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(400, f"At most {MAX_PHOTOS} photos allowed")
    out = []
    for p in photos:
        data = await p.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(400, f"{p.filename} is larger than 8 MB")
        try:
            imaging.validate_image(data)
        except ValueError:
            raise HTTPException(400, f"{p.filename} is not a valid image") from None
        out.append(data)
    return out


def save_photo(data: bytes, listing_id: str, n: int) -> str:
    """Re-encode as JPEG: strips EXIF (GPS!) and anything that isn't image data."""
    folder = db.UPLOAD_DIR / listing_id
    folder.mkdir(parents=True, exist_ok=True)
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(folder / f"{n}.jpg", "JPEG", quality=85)
    return f"/uploads/{listing_id}/{n}.jpg"


def listing_photos(listing_id: str) -> list[str]:
    with db.connect() as con:
        rows = con.execute(
            "SELECT path FROM fingerprints WHERE listing_id = ? AND source = 'owner' ORDER BY image_id",
            (listing_id,)).fetchall()
    return [r["path"] for r in rows]


def public_listing(row) -> dict:
    """What tenants see. The owner's phone is NOT exposed until they accept a booking."""
    risk = json.loads(row["risk_json"])
    return {
        "id": row["id"], "title": row["title"], "city": row["city"], "locality": row["locality"],
        "bhk": row["bhk"], "sqft": row["sqft"], "furnishing": row["furnishing"], "rent": row["rent"],
        "description": row["description"], "owner_name": row["owner_name"].split()[0],
        "lat": row["lat"], "lng": row["lng"], "available": bool(row["available"]),
        "photos": listing_photos(row["id"]), "created_at": row["created_at"],
        "safety": {"score": row["risk_score"], "level": row["risk_level"],
                   "verified": row["risk_level"] == "low",
                   "fair_rent": (risk.get("price") or {}).get("fair_rent")},
    }


def check_city(city: str, locality: str) -> None:
    if city not in LOCALITIES:
        raise HTTPException(400, f"Unsupported city. Choose one of: {', '.join(LOCALITIES)}")
    if locality not in LOCALITIES[city]:
        raise HTTPException(400, f"Unknown locality for {city}")


def valid_phone(phone: str) -> str:
    p = db.normalize_phone(phone)
    if len(p) != 10:
        raise HTTPException(400, "Enter a valid 10-digit phone number")
    return p


def owner_or_404(token: str):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM listings WHERE owner_token = ?", (token,)).fetchall()
    if not rows:
        raise HTTPException(404, "Invalid owner link")
    return rows


# ---------- pages ----------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(db.ROOT / "static" / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so it can control the whole app
    return FileResponse(db.ROOT / "static" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/meta")
def meta():
    return {"cities": {c: {"center": CITY_CENTERS[c], "localities": list(l)} for c, l in LOCALITIES.items()},
            "furnishing": sorted(FURNISHING)}


@app.get("/api/stats")
def stats():
    with db.connect() as con:
        q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        return {"listings": q("SELECT COUNT(*) FROM listings WHERE risk_level != 'high'"),
                "vacant": q("SELECT COUNT(*) FROM listings WHERE available = 1 AND risk_level != 'high'"),
                "blocked": q("SELECT COUNT(*) FROM listings WHERE risk_level = 'high'"),
                "bookings": q("SELECT COUNT(*) FROM bookings"),
                "reports": q("SELECT COUNT(*) FROM reports"),
                "photos_indexed": imaging.index_size()}


# ---------- listings (owner posts, tenant browses) ----------

@app.get("/api/listings")
def list_listings(city: str | None = None, max_rent: int | None = None, bhk: int | None = None,
                  vacant_only: bool = True, sort: str = "newest"):
    sql = "SELECT * FROM listings WHERE risk_level != 'high'"
    args: list = []
    if city:
        sql += " AND city = ?"; args.append(city)
    if max_rent:
        sql += " AND rent <= ?"; args.append(max_rent)
    if bhk:
        sql += " AND bhk = ?" if bhk < 4 else " AND bhk >= ?"; args.append(bhk)
    if vacant_only:
        sql += " AND available = 1"
    sql += {"price_low": " ORDER BY rent ASC", "price_high": " ORDER BY rent DESC",
            "safest": " ORDER BY risk_score ASC"}.get(sort, " ORDER BY created_at DESC")
    with db.connect() as con:
        rows = con.execute(sql, args).fetchall()
    return [public_listing(r) for r in rows]


@app.get("/api/listings/{listing_id}")
def get_listing(listing_id: str):
    with db.connect() as con:
        row = con.execute("SELECT * FROM listings WHERE id = ? AND risk_level != 'high'", (listing_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")
    return public_listing(row)


@app.post("/api/listings")
async def create_listing(
    title: str = Form(..., min_length=5, max_length=120),
    city: str = Form(...), locality: str = Form(...),
    bhk: int = Form(..., ge=1, le=10), sqft: int = Form(..., ge=100, le=20000),
    furnishing: str = Form(...), rent: int = Form(..., ge=500, le=2_000_000),
    description: str = Form(..., min_length=10, max_length=3000),
    owner_name: str = Form(..., min_length=2, max_length=80), owner_phone: str = Form(...),
    lat: float = Form(..., ge=-90, le=90), lng: float = Form(..., ge=-180, le=180),
    photos: list[UploadFile] | None = File(None),
    authorization: str | None = Header(None),
):
    check_city(city, locality)
    if furnishing not in FURNISHING:
        raise HTTPException(400, "Invalid furnishing")
    phone = valid_phone(owner_phone)
    images = await read_photos(photos)
    if not images:
        raise HTTPException(400, "Add at least one photo of the flat")

    listing_id = secrets.token_hex(5)
    risk = analyze(ListingInput(text=f"{title}. {description}", city=city, locality=locality, bhk=bhk,
                                sqft=sqft, furnishing=furnishing, rent=rent, phone=phone, images=images,
                                listing_id=listing_id), STATE["text"], STATE["rent"])
    account = auth.current_account(authorization)
    token = account["owner_token"] if account else secrets.token_urlsafe(16)
    with db.connect() as con:
        con.execute(
            "INSERT INTO listings (id, title, city, locality, bhk, sqft, furnishing, rent, description, owner_name,"
            " owner_phone, owner_token, lat, lng, risk_score, risk_level, risk_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (listing_id, title.strip(), city, locality, bhk, sqft, furnishing, rent, description.strip(),
             owner_name.strip(), phone, token, lat, lng, risk["score"], risk["level"], json.dumps(risk)))
    # Index photos AFTER the check, so future listings reusing them get caught.
    for n, data in enumerate(images):
        path = save_photo(data, listing_id, n)
        ph, dh = imaging.fingerprint(data)
        image_id = f"{listing_id}-{n}"
        db.save_fingerprint(image_id, listing_id, "owner", city, path, ph, dh)
        imaging.index_add(listing_id, image_id, ph, dh)
    return {"id": listing_id, "owner_token": token, "published": risk["level"] != "high", "risk": risk}


# ---------- bookings (hotel-style visit / reserve requests) ----------

class BookingIn(BaseModel):
    listing_id: str
    name: str = Field(min_length=2, max_length=80)
    phone: str
    visit_date: date
    move_in_date: date
    occupants: int = Field(ge=1, le=12)
    message: str = Field(default="", max_length=1000)

    @field_validator("visit_date")
    @classmethod
    def not_past(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("Visit date cannot be in the past")
        return v


@app.post("/api/bookings")
def create_booking(b: BookingIn, authorization: str | None = Header(None)):
    phone = valid_phone(b.phone)
    if b.move_in_date < b.visit_date:
        raise HTTPException(400, "Move-in date must be on or after the visit date")
    with db.connect() as con:
        row = con.execute("SELECT available, risk_level FROM listings WHERE id = ?", (b.listing_id,)).fetchone()
        if not row or row["risk_level"] == "high":
            raise HTTPException(404, "Listing not found")
        if not row["available"]:
            raise HTTPException(409, "This flat is no longer vacant")
        booking_id = secrets.token_urlsafe(8)
        con.execute(
            "INSERT INTO bookings (id, listing_id, tenant_name, tenant_phone, visit_date, move_in_date, occupants,"
            " message) VALUES (?,?,?,?,?,?,?,?)",
            (booking_id, b.listing_id, b.name.strip(), phone, b.visit_date.isoformat(),
             b.move_in_date.isoformat(), b.occupants, b.message.strip()))
    account = auth.current_account(authorization)
    if account:
        auth.link_booking(account["id"], booking_id)
    return {"booking_id": booking_id, "status": "pending"}


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: str):
    with db.connect() as con:
        row = con.execute(
            "SELECT b.*, l.title, l.locality, l.city, l.rent, l.owner_name, l.owner_phone, l.lat, l.lng"
            " FROM bookings b JOIN listings l ON l.id = b.listing_id WHERE b.id = ?", (booking_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Booking not found")
    out = {k: row[k] for k in ("id", "listing_id", "title", "locality", "city", "rent", "visit_date",
                               "move_in_date", "occupants", "status", "owner_note", "created_at")}
    with db.connect() as con:
        out["moved_in"] = con.execute("SELECT 1 FROM tenancies WHERE booking_id = ?", (booking_id,)).fetchone() is not None
    if row["status"] == "accepted":  # connect directly only once the owner accepts
        out["owner"] = {"name": row["owner_name"], "phone": row["owner_phone"],
                        "whatsapp": f"https://wa.me/91{row['owner_phone']}",
                        "lat": row["lat"], "lng": row["lng"]}
    return out


@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str):
    with db.connect() as con:
        cur = con.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ? AND status IN ('pending','accepted')",
                          (booking_id,))
    if not cur.rowcount:
        raise HTTPException(400, "Booking cannot be cancelled")
    return {"status": "cancelled"}


# ---------- owner dashboard (secret link, no password needed) ----------

@app.get("/api/owner/{token}")
def owner_dashboard(token: str):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM listings WHERE owner_token = ? ORDER BY created_at DESC", (token,)).fetchall()
        account = con.execute("SELECT name FROM accounts WHERE owner_token = ?", (token,)).fetchone()
    if not rows:
        if not account:
            raise HTTPException(404, "Invalid owner link")
        return {"owner_name": account["name"], "listings": [], "bookings": [], "tenancies": []}
    ids = [r["id"] for r in rows]
    with db.connect() as con:
        bookings = con.execute(
            f"SELECT * FROM bookings WHERE listing_id IN ({','.join('?' * len(ids))}) ORDER BY created_at DESC",
            ids).fetchall()
    return {"owner_name": account["name"] if account else rows[0]["owner_name"],
            "listings": [{**public_listing(r), "risk": json.loads(r["risk_json"])} for r in rows],
            "bookings": [dict(b) for b in bookings],
            "tenancies": tenancy.owner_tenancies(token)}


class BookingDecision(BaseModel):
    status: str
    note: str = Field(default="", max_length=500)


@app.post("/api/owner/{token}/bookings/{booking_id}")
def decide_booking(token: str, booking_id: str, d: BookingDecision):
    if d.status not in {"accepted", "declined"}:
        raise HTTPException(400, "status must be accepted or declined")
    ids = [r["id"] for r in owner_or_404(token)]
    with db.connect() as con:
        cur = con.execute(
            f"UPDATE bookings SET status = ?, owner_note = ? WHERE id = ? AND status = 'pending'"
            f" AND listing_id IN ({','.join('?' * len(ids))})", (d.status, d.note.strip(), booking_id, *ids))
    if not cur.rowcount:
        raise HTTPException(404, "Pending booking not found")
    return {"status": d.status}


class Availability(BaseModel):
    available: bool


@app.post("/api/owner/{token}/listings/{listing_id}/availability")
def set_availability(token: str, listing_id: str, a: Availability):
    if listing_id not in {r["id"] for r in owner_or_404(token)}:
        raise HTTPException(404, "Listing not found")
    with db.connect() as con:
        con.execute("UPDATE listings SET available = ? WHERE id = ?", (int(a.available), listing_id))
    return {"available": a.available}


# ---------- scam checker, reports, assistant ----------

@app.post("/api/check")
async def check_listing(
    text: str = Form(""), city: str = Form(""), locality: str = Form(""),
    bhk: int | None = Form(None), sqft: int | None = Form(None), furnishing: str = Form("semi-furnished"),
    rent: int | None = Form(None), phone: str = Form(""), photos: list[UploadFile] | None = File(None),
):
    if city and locality:
        check_city(city, locality)
    images = await read_photos(photos)
    if not (text.strip() or images or rent):
        raise HTTPException(400, "Give at least the listing text, a photo or the rent")
    return analyze(ListingInput(text=text, city=city, locality=locality, bhk=bhk, sqft=sqft,
                                furnishing=furnishing if furnishing in FURNISHING else "semi-furnished",
                                rent=rent, phone=phone, images=images), STATE["text"], STATE["rent"])


class ReportIn(BaseModel):
    phone: str
    reason: str = Field(min_length=5, max_length=500)
    listing_id: str | None = None


@app.post("/api/report")
def report(r: ReportIn):
    db.add_report(valid_phone(r.phone), r.reason.strip(), r.listing_id)
    return {"ok": True, "total_reports": db.count_reports(r.phone)}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/ask")
def ask(q: AskIn):
    return STATE["assistant"].ask(q.question)
