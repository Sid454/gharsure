"""Reset the database and fill it with demo flats, a booking, a tenancy with bills,
and edited 'stolen' photos you can upload to see the scam detector work.

Run:  .venv/bin/python -m scripts.seed_demo
"""
import io
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app import db

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo"
# Test-only demo credentials (local development data, not real accounts)
DEMO_OWNER_PHONE = "9000000100"
DEMO_RENTER_PHONE = "9000000200"
DEMO_PASSWORD = "demo1234"


def room_photo(seed: int) -> Image.Image:
    """Draw a simple synthetic room (wall, floor, window, bed, cupboard) so the demo needs no real photos."""
    rnd = random.Random(seed)
    w, h = 960, 640
    wall = tuple(rnd.randint(150, 240) for _ in range(3))
    floor = tuple(rnd.randint(70, 160) for _ in range(3))
    img = Image.new("RGB", (w, h), wall)
    d = ImageDraw.Draw(img)
    horizon = rnd.randint(380, 450)
    d.polygon([(0, h), (w, h), (w, horizon), (0, horizon)], fill=floor)
    for x in range(0, w, rnd.randint(50, 90)):  # floor tiles
        d.line([(x, horizon), (x - 80, h)], fill=tuple(max(c - 25, 0) for c in floor), width=2)
    wx, wy = rnd.randint(60, 500), rnd.randint(60, 120)
    d.rectangle([wx, wy, wx + 260, wy + 200], fill=(170, 210, 245), outline=(90, 70, 50), width=10)
    d.line([wx + 130, wy, wx + 130, wy + 200], fill=(90, 70, 50), width=8)
    bx = rnd.randint(40, 520)
    bed = tuple(rnd.randint(40, 220) for _ in range(3))
    d.rectangle([bx, horizon - 90, bx + 380, horizon + 80], fill=bed)
    d.rectangle([bx, horizon - 160, bx + 40, horizon + 80], fill=(110, 80, 55))
    d.ellipse([bx + 60, horizon - 110, bx + 170, horizon - 60], fill=(250, 250, 250))
    cx = rnd.choice([20, w - 220])
    d.rectangle([cx, 120, cx + 190, horizon + 40], fill=(120, 85, 60), outline=(70, 50, 35), width=6)
    d.line([cx + 95, 120, cx + 95, horizon + 40], fill=(70, 50, 35), width=4)
    lamp = rnd.randint(300, 800)
    d.polygon([(lamp - 40, 40), (lamp + 40, 40), (lamp + 25, 0), (lamp - 25, 0)], fill=(255, 235, 160))
    # Decor: posters, rugs, plants, shelves at random spots so every room looks different
    for _ in range(rnd.randint(8, 14)):
        x, y = rnd.randint(0, w - 60), rnd.randint(0, h - 60)
        sw, sh = rnd.randint(40, 260), rnd.randint(40, 200)
        col = tuple(rnd.randint(0, 255) for _ in range(3))
        shape = rnd.choice(["rect", "ellipse", "rect"])
        (d.rectangle if shape == "rect" else d.ellipse)([x, y, x + sw, y + sh], fill=col)
    # Large-scale lighting gradient (changes the low-frequency content pHash looks at)
    shade = Image.linear_gradient("L").resize((w, h)).rotate(rnd.choice([0, 90, 180, 270]), expand=False)
    img = Image.composite(img, Image.new("RGB", (w, h), (20, 20, 20)), shade.point(lambda v: 110 + v * 145 // 255))
    return img


def jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def stolen_edit(img: Image.Image) -> Image.Image:
    """What scammers do: crop, change brightness/colour and add their own watermark."""
    w, h = img.size
    out = img.crop((int(w * 0.07), int(h * 0.06), int(w * 0.94), int(h * 0.95)))
    out = ImageEnhance.Brightness(out).enhance(1.15)
    out = ImageEnhance.Color(out).enhance(1.3)
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("Arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    d.text((out.width - 330, out.height - 60), "Call 98xxxxxx01", fill=(255, 255, 255), font=font)
    return out.resize((800, int(800 * out.height / out.width)))


LISTINGS = [
    # title, city, locality, bhk, sqft, furnishing, rent, description, owner, dlat, dlng
    ("Sunny 2BHK near Koramangala 5th Block", "Bengaluru", "Koramangala", 2, 1100, "semi-furnished", 46000,
     "East facing 2BHK with balcony, 2 bathrooms and covered parking. Owner lives on the ground floor, visit any "
     "evening. Agreement registered, police verification as per society rules.", "Ramesh Kumar", 0.035, 0.03),
    ("Furnished 1BHK for working professionals, HSR", "Bengaluru", "HSR Layout", 1, 650, "furnished", 31000,
     "Fully furnished 1BHK with AC, fridge and washing machine. Walking distance to 27th Main. Come and see the "
     "flat on weekends, deposit after agreement signing.", "Anita Rao", -0.06, 0.07),
    ("Family 3BHK in gated society, Whitefield", "Bengaluru", "Whitefield", 3, 1650, "unfurnished", 43000,
     "Spacious 3BHK with clubhouse, pool and power backup. Family preferred. Visit with ID proof, 11 month "
     "agreement.", "Suresh Iyer", 0.02, 0.15),
    ("Student friendly 1BHK near Kothrud depot", "Pune", "Kothrud", 1, 600, "semi-furnished", 17000,
     "Quiet 1BHK, students welcome. Rent includes water. Visit anytime between 10am and 6pm, owner contact "
     "directly, no brokerage.", "Meera Joshi", -0.01, -0.04),
    ("2BHK for students sharing, near COEP", "Pune", "Kothrud", 2, 950, "semi-furnished", 23000,
     "Two bedrooms, perfect for two students sharing. 10 minutes to college, kitchen with gas line, WiFi ready. "
     "Visit on weekends, agreement for 11 months.", "Sunita Deshpande", 0.012, -0.05),
    ("2BHK close to Hinjewadi Phase 1", "Pune", "Hinjewadi", 2, 1050, "furnished", 31500,
     "Furnished 2BHK near IT park with gym and parking. Can show the flat on Saturday morning, deposit two "
     "months, refundable as per agreement.", "Vikram Patil", 0.07, -0.1),
    ("Compact 1RK in Laxmi Nagar near metro", "Delhi", "Laxmi Nagar", 1, 420, "semi-furnished", 12000,
     "1RK with attached bathroom, two minutes from metro. Electricity as per meter. Visit and meet the family "
     "before deciding.", "Pooja Sharma", 0.02, 0.07),
    ("Bright 2BHK in Gachibowli near DLF", "Hyderabad", "Gachibowli", 2, 1150, "semi-furnished", 40000,
     "Well maintained 2BHK, 24 hour water, lift and parking. Owner stays nearby, call to schedule a visit.",
     "Kiran Reddy", 0.05, -0.08),
]


def main() -> None:
    if db.DATA_DIR.exists():
        for p in [db.DB_PATH, db.UPLOAD_DIR]:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    shutil.rmtree(DEMO_DIR, ignore_errors=True)
    DEMO_DIR.mkdir()

    from app.main import app
    from app.rent_model import CITY_CENTERS

    with TestClient(app) as client:
        owner_links = []
        for i, (title, city, loc, bhk, sqft, furn, rent, desc, owner, dlat, dlng) in enumerate(LISTINGS):
            photos = [jpeg(room_photo(i * 10 + k)) for k in range(2)]
            lat, lng = CITY_CENTERS[city]
            r = client.post("/api/listings", data={
                "title": title, "city": city, "locality": loc, "bhk": bhk, "sqft": sqft, "furnishing": furn,
                "rent": rent, "description": desc, "owner_name": owner, "owner_phone": f"98765{43210 + i}",
                "lat": lat + dlat, "lng": lng + dlng,
            }, files=[("photos", (f"{k}.jpg", p, "image/jpeg")) for k, p in enumerate(photos)])
            r.raise_for_status()
            body = r.json()
            owner_links.append((title, body["owner_token"], body["risk"]["score"]))
            if i == 0:
                first_photo = room_photo(0)

        # Demo files for the scam checker / fake listing
        stolen_edit(first_photo).save(DEMO_DIR / "stolen_photo_edited.jpg", quality=88)
        room_photo(999).save(DEMO_DIR / "original_new_photo.jpg", quality=88)
        (DEMO_DIR / "scam_message.txt").write_text(
            "Hello, I am Army officer posted at border, transferred suddenly. 2BHK fully furnished in Andheri "
            "only 9000 per month. Visit not possible, I will courier the keys. Pay 10000 token on UPI today "
            "otherwise many people waiting.\n")

        # A report on the scam number, so the demo shows the community signal too
        client.post("/api/report", json={"phone": "9000000001", "reason": "Took token money and blocked me"})
        client.post("/api/report", json={"phone": "9000000001", "reason": "Fake army officer story"})

        # Booking -> accepted -> moved in -> bills, so the Rent & Bills screen has data
        token = next(t for title, t, _ in owner_links if "Kothrud" in title or "Hinjewadi" in title)
        dash = client.get(f"/api/owner/{token}").json()
        listing_id = dash["listings"][0]["id"]
        today = date.today()
        b = client.post("/api/bookings", json={
            "listing_id": listing_id, "name": "Demo Tenant", "phone": "9123456780",
            "visit_date": today.isoformat(), "move_in_date": (today + timedelta(days=3)).isoformat(),
            "occupants": 1, "message": "Final year student, need it for 11 months"}).json()
        client.post(f"/api/owner/{token}/bookings/{b['booking_id']}", json={"status": "accepted",
                                                                          "note": "Come at 6pm"})
        t = client.post(f"/api/owner/{token}/tenancies", json={
            "booking_id": b["booking_id"], "deposit": 34000, "owner_upi": "demo.owner@okaxis",
            "start_date": (today - timedelta(days=35)).isoformat()}).json()
        first_bill = client.get(f"/api/tenancy/{b['booking_id']}").json()["bills"][0]["id"]
        client.post(f"/api/tenancy/{b['booking_id']}/bills/{first_bill}/paid", json={"utr": "412345678901"})
        client.post(f"/api/owner/{token}/bills/{first_bill}/confirm")
        for kind, amt, days in [("rent", 17000, -5), ("electricity", 1240, 7), ("water", 300, 7)]:
            client.post(f"/api/owner/{token}/tenancies/{t['tenancy_id']}/bills", json={
                "kind": kind, "period": today.strftime("%b %Y"), "amount": amt,
                "due_date": (today + timedelta(days=days)).isoformat()})

        # Roommate profiles (Pune students) for the roommate-matching demo
        nm = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        base = dict(gender="male", pref_gender="male", city="Pune", occupation="student", move_in=nm,
                    budget_min=7000, budget_max=12000, sleep="late", smoking="never", smoke_ok=False,
                    drinking="occasionally", drink_ok=True, food="nonveg", cleanliness=4, guests="sometimes",
                    noise="moderate", pets=False, languages=["hindi", "english"])
        people = [
            dict(name="Aarav Mehta", age=21, college="COEP Technological University", localities=["Kothrud"],
                 interests=["coding", "cricket", "gaming", "music"], bio="Final year CSE. Night coder, keeps the room tidy."),
            dict(name="Rohan Kulkarni", age=22, college="COEP Technological University", localities=["Kothrud", "Baner"],
                 interests=["coding", "gaming", "anime"], bio="Placement prep mode. Chill, clean, late-night Maggi expert."),
            dict(name="Ishaan Verma", age=21, college="MIT-WPU", localities=["Kothrud"], sleep="normal",
                 interests=["cricket", "gym", "music"], budget_min=8000, budget_max=12000, bio="Gym at 7am, cricket on weekends."),
            dict(name="Kabir Singh", age=23, college="Symbiosis", localities=["Viman Nagar"], smoking="regularly",
                 smoke_ok=True, drinking="regularly", guests="often", noise="lively", cleanliness=2,
                 interests=["parties", "football"], budget_min=12000, budget_max=18000, bio="Love hosting friends."),
            dict(name="Dev Patil", age=20, college="MIT-WPU", localities=["Kothrud", "Hinjewadi"], sleep="early",
                 drinking="never", drink_ok=False, food="veg", noise="quiet", guests="rarely", cleanliness=5,
                 interests=["reading", "chess", "coding"], bio="Early riser, vegetarian, quiet study vibes."),
            dict(name="Neha Joshi", age=21, gender="female", pref_gender="female", college="COEP Technological University",
                 localities=["Kothrud"], interests=["coding", "music"], bio="Looking for a female flatmate near college."),
        ]
        roommate_tokens = []
        for p in people:
            r = client.post("/api/roommates", json={**base, **p, "phone": f"91234{50000 + len(roommate_tokens)}"})
            r.raise_for_status()
            roommate_tokens.append((p["name"], r.json()["token"]))
        # Rohan already sent Aarav a request, so the demo shows an incoming request
        aarav_id = client.get(f"/api/roommates/{roommate_tokens[0][1]}").json()["me"]["id"]
        client.post(f"/api/roommates/{roommate_tokens[1][1]}/connect",
                    json={"to_id": aarav_id, "message": "Same college, same schedule. Want to share a 2BHK in Kothrud?"})

        # Demo accounts (test-only passwords) so you can sign in right away
        owner = client.post("/api/auth/signup", json={"name": "Sunita Deshpande", "phone": DEMO_OWNER_PHONE,
                                                       "password": DEMO_PASSWORD, "mode": "owner"}).json()["session"]
        renter = client.post("/api/auth/signup", json={"name": "Aarav Mehta", "phone": DEMO_RENTER_PHONE,
                                                        "password": DEMO_PASSWORD, "mode": "renter"}).json()["session"]
        owner_acc = client.get("/api/auth/me", headers={"Authorization": f"Bearer {owner}"}).json()
        renter_acc = client.get("/api/auth/me", headers={"Authorization": f"Bearer {renter}"}).json()
    with db.connect() as con:
        # Sunita owns every Pune flat (incl. the one with a tenant + bills); Aarav has the booking + roommate profile
        con.execute("UPDATE listings SET owner_token = ? WHERE city = 'Pune'", (owner_acc["owner_token"],))
        con.execute("INSERT INTO account_bookings VALUES (?, ?)", (renter_acc["id"], b["booking_id"]))
        con.execute("UPDATE accounts SET roommate_token = ? WHERE id = ?", (roommate_tokens[0][1], renter_acc["id"]))

    print("\nDemo data ready.\n")
    print(f"Demo sign-in  Owner: {DEMO_OWNER_PHONE} / {DEMO_PASSWORD}    Renter: {DEMO_RENTER_PHONE} / {DEMO_PASSWORD}\n")
    print("Owner dashboards (open after starting the server):")
    for title, tok, score in owner_links:
        print(f"  [{score:>3} risk] {title}\n          http://127.0.0.1:8000/#owner={tok}")
    print(f"\nTenant (booking + Rent & Bills): http://127.0.0.1:8000/#booking={b['booking_id']}")
    print(f"Roommate profile (Aarav, Pune): http://127.0.0.1:8000/#roommates={roommate_tokens[0][1]}")
    print(f"Demo files to try in 'Check a Listing': {DEMO_DIR}")


if __name__ == "__main__":
    main()
