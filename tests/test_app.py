"""End-to-end tests: C++ engine, scam detection, owner listing, booking, tenancy, bills."""
import io
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["RENTSHIELD_DATA"] = tempfile.mkdtemp(prefix="rentshield-test-")

import pytest  # noqa: E402
import rentshield_core as core  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from scripts.seed_demo import jpeg, room_photo, stolen_edit  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def post_listing(client, seed, city="Pune", locality="Kothrud", rent=17000, phone="9876500001", text=None, photo=None):
    return client.post("/api/listings", data={
        "title": "Quiet 1BHK near the market", "city": city, "locality": locality, "bhk": 1, "sqft": 600,
        "furnishing": "semi-furnished", "rent": rent, "owner_name": "Test Owner", "owner_phone": phone,
        "description": text or "Owner lives nearby. Visit any evening, agreement registered.",
        "lat": 18.5, "lng": 73.8,
    }, files=[("photos", ("a.jpg", photo or jpeg(room_photo(seed)), "image/jpeg"))])


def test_cpp_hashing_is_robust_to_edits():
    from app import imaging
    orig = room_photo(1)
    ph, dh = imaging.fingerprint(jpeg(orig))
    qp, qd = imaging._hash_pair(imaging._load(jpeg(stolen_edit(orig))))
    other_p, _ = imaging._hash_pair(imaging._load(jpeg(room_photo(2))))
    assert min(core.hamming(qp, p) for p in ph) <= imaging.MAX_DISTANCE
    assert min(core.hamming(other_p, p) for p in ph) > imaging.MAX_DISTANCE


def test_genuine_listing_is_published_low_risk(client):
    r = post_listing(client, 10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["published"] and body["risk"]["level"] == "low"
    listings = client.get("/api/listings").json()
    assert any(l["id"] == body["id"] for l in listings)
    assert "owner_phone" not in listings[0]  # phone hidden from the public


def test_stolen_photo_and_scam_text_are_blocked(client):
    original = room_photo(20)
    post_listing(client, 0, photo=jpeg(original))  # genuine owner in Pune
    scam = post_listing(client, 0, city="Mumbai", locality="Andheri", rent=5000, phone="9000000009",
                        photo=jpeg(stolen_edit(original)),
                        text="I am army officer, visit not possible. Pay token today, I will courier the keys.")
    risk = scam.json()["risk"]
    assert risk["level"] == "high" and not scam.json()["published"]
    signals = {r["signal"] for r in risk["reasons"]}
    assert {"Reused photos", "Too cheap", "Scam-like wording"} <= signals
    assert scam.json()["id"] not in [l["id"] for l in client.get("/api/listings").json()]


def test_booking_tenancy_and_bills_flow(client):
    created = post_listing(client, 30).json()
    token, lid = created["owner_token"], created["id"]
    today = date.today()

    b = client.post("/api/bookings", json={"listing_id": lid, "name": "Asha", "phone": "9123400000",
                                           "visit_date": today.isoformat(),
                                           "move_in_date": (today + timedelta(days=5)).isoformat(),
                                           "occupants": 2, "message": "Student"}).json()
    bid = b["booking_id"]
    assert "owner" not in client.get(f"/api/bookings/{bid}").json()  # no phone before acceptance

    # someone else's owner token cannot touch this booking
    other = post_listing(client, 31).json()["owner_token"]
    assert client.post(f"/api/owner/{other}/bookings/{bid}", json={"status": "accepted"}).status_code == 404

    assert client.post(f"/api/owner/{token}/bookings/{bid}", json={"status": "accepted"}).status_code == 200
    assert client.get(f"/api/bookings/{bid}").json()["owner"]["phone"] == "9876500001"

    bad_upi = client.post(f"/api/owner/{token}/tenancies", json={"booking_id": bid, "deposit": 34000,
                                                                "owner_upi": "not a upi", "start_date": today.isoformat()})
    assert bad_upi.status_code == 422
    t = client.post(f"/api/owner/{token}/tenancies", json={"booking_id": bid, "deposit": 34000,
                                                           "owner_upi": "owner@okaxis", "start_date": today.isoformat()})
    assert t.status_code == 200, t.text
    assert not client.get(f"/api/listings/{lid}").json()["available"]  # now rented

    client.post(f"/api/owner/{token}/tenancies/{t.json()['tenancy_id']}/bills",
                json={"kind": "water", "period": "Nov 2026", "amount": 300, "due_date": today.isoformat()})
    led = client.get(f"/api/tenancy/{bid}").json()
    assert led["summary"]["deposit_held"] == 34000
    assert led["summary"]["total_due"] == 17000 + 300
    water = next(x for x in led["bills"] if x["kind"] == "water")
    assert water["upi_link"].startswith("upi://pay?pa=owner%40okaxis") and "am=300.00" in water["upi_link"]

    qr = client.get(f"/api/tenancy/{bid}/bills/{water['id']}/qr.png")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/png"

    assert client.post(f"/api/tenancy/{bid}/bills/{water['id']}/paid", json={"utr": "12"}).status_code == 422
    assert client.post(f"/api/tenancy/{bid}/bills/{water['id']}/paid", json={"utr": "412345678901"}).status_code == 200
    assert client.post(f"/api/owner/{token}/bills/{water['id']}/confirm").status_code == 200
    s = client.get(f"/api/tenancy/{bid}").json()["summary"]
    assert s["total_paid"] == 300 and s["total_due"] == 17000

    client.post(f"/api/owner/{token}/tenancies/{t.json()['tenancy_id']}/deposit-refund", json={"amount": 30000})
    assert client.get(f"/api/tenancy/{bid}").json()["summary"]["deposit_held"] == 4000
    assert client.get(f"/api/listings/{lid}").json()["available"]  # vacant again


def test_validation_and_assistant(client):
    assert client.post("/api/bookings", json={"listing_id": "x", "name": "A b", "phone": "123",
                                              "visit_date": "2001-01-01", "move_in_date": "2001-01-02",
                                              "occupants": 1}).status_code == 422
    bad = client.post("/api/listings", data={"title": "Hello there", "city": "Pune", "locality": "Kothrud",
                                             "bhk": 1, "sqft": 500, "furnishing": "furnished", "rent": 9000,
                                             "description": "nice flat for rent", "owner_name": "Xy",
                                             "owner_phone": "9876500001", "lat": 18.5, "lng": 73.8},
                      files=[("photos", ("x.jpg", io.BytesIO(b"not an image"), "image/jpeg"))])
    assert bad.status_code == 400
    ans = client.post("/api/ask", json={"question": "should I scan a QR code to get my refund?"}).json()
    assert "QR" in ans["sources"][0]["title"]


def roommate(**over):
    base = dict(name="Test Person", phone="9111100000", age=21, gender="male", pref_gender="any", college="COEP",
                city="Pune", localities=["Kothrud"], budget_min=7000, budget_max=12000, move_in="2026-12",
                sleep="late", smoking="never", smoke_ok=False, drinking="never", drink_ok=True, food="veg",
                cleanliness=4, guests="sometimes", noise="moderate", interests=["coding", "music"])
    return {**base, **over}


def test_roommate_matching_and_mutual_connect(client):
    a = client.post("/api/roommates", json=roommate(name="Asha", phone="9111100001")).json()
    twin = client.post("/api/roommates", json=roommate(name="Twin", phone="9111100002")).json()
    client.post("/api/roommates", json=roommate(name="Smoker", phone="9111100003", smoking="regularly", smoke_ok=True,
                                                sleep="early", food="nonveg", cleanliness=1, noise="lively"))
    client.post("/api/roommates", json=roommate(name="OnlyFemale", phone="9111100004", gender="female", pref_gender="female"))

    d = client.get(f"/api/roommates/{a['token']}").json()
    names = [m["name"] for m in d["matches"]]
    assert names[0] == "Twin" and d["matches"][0]["match"]["score"] >= 90
    smoker = next(m for m in d["matches"] if m["name"] == "Smoker")
    assert smoker["match"]["score"] <= 45 and any("smoke" in b for b in smoker["match"]["bad"])
    assert "OnlyFemale" not in names                       # gender preference respected
    assert "contact" not in d["matches"][0]                 # no phone before both agree

    client.post(f"/api/roommates/{a['token']}/connect", json={"to_id": twin["id"], "message": "hi"})
    incoming = client.get(f"/api/roommates/{twin['token']}").json()["incoming"]
    assert incoming and incoming[0]["name"] == "Asha"
    client.post(f"/api/roommates/{twin['token']}/requests/{incoming[0]['request']['id']}", json={"status": "accepted"})
    top = client.get(f"/api/roommates/{a['token']}").json()["matches"][0]
    assert top["contact"]["phone"] == "9111100002"


def test_accounts_owner_and_renter_modes(client):
    r = client.post("/api/auth/signup", json={"name": "Owner One", "phone": "9222200001", "password": "secret12", "mode": "owner"})
    assert r.status_code == 200
    assert client.post("/api/auth/signup", json={"name": "Dup", "phone": "9222200001", "password": "secret12",
                                                 "mode": "renter"}).status_code == 409
    assert client.post("/api/auth/login", json={"phone": "9222200001", "password": "wrong"}).status_code == 401
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"phone": "9222200001", "password": "secret12"}).json()["session"]}
    me = client.get("/api/auth/me", headers=h).json()
    assert me["default_mode"] == "owner" and me["listings"] == 0
    assert client.get(f"/api/owner/{me['owner_token']}").json()["listings"] == []   # empty dashboard works

    # two flats posted while signed in land in the same owner dashboard
    for seed in (40, 41):
        client.post("/api/listings", headers=h, data={
            "title": "Signed in owner flat", "city": "Pune", "locality": "Baner", "bhk": 2, "sqft": 1000,
            "furnishing": "semi-furnished", "rent": 30000, "owner_name": "Owner One", "owner_phone": "9222200001",
            "description": "Visit anytime, agreement registered.", "lat": 18.56, "lng": 73.78,
        }, files=[("photos", ("a.jpg", jpeg(room_photo(seed)), "image/jpeg"))])
    assert len(client.get(f"/api/owner/{me['owner_token']}").json()["listings"]) == 2

    # the same account can book a visit as a renter, and it shows in "My bookings"
    lid = client.get("/api/listings", params={"city": "Pune"}).json()[0]["id"]
    client.post("/api/bookings", headers=h, json={"listing_id": lid, "name": "Owner One", "phone": "9222200001",
                                                  "visit_date": date.today().isoformat(),
                                                  "move_in_date": date.today().isoformat(), "occupants": 1})
    assert len(client.get("/api/auth/me", headers=h).json()["bookings"]) == 1
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401
