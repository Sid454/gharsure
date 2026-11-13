"""Roommate matching: lifestyle profiles, compatibility score with reasons, mutual connect.

Contact details are shared only after BOTH people agree (one sends a request, the other accepts).
"""
import json
import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from . import auth, db
from .rent_model import LOCALITIES

router = APIRouter()

Freq = Literal["never", "occasionally", "regularly"]
LEVEL3 = {"never": 0, "occasionally": 1, "regularly": 2, "rarely": 0, "sometimes": 1, "often": 2,
          "quiet": 0, "moderate": 1, "lively": 2, "early": 0, "normal": 1, "late": 2}

# Weights add up to 100
WEIGHTS = {"budget": 14, "sleep": 14, "smoking": 14, "food": 10, "cleanliness": 12, "drinking": 8,
           "guests": 7, "noise": 7, "move_in": 5, "interests": 5, "college": 4}


class Profile(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    phone: str
    age: int = Field(ge=16, le=60)
    gender: Literal["male", "female", "other"]
    pref_gender: Literal["male", "female", "any"]
    college: str = Field(default="", max_length=120)
    occupation: Literal["student", "working", "intern"] = "student"
    city: str
    localities: list[str] = Field(default_factory=list, max_length=5)
    budget_min: int = Field(ge=1000, le=500000)
    budget_max: int = Field(ge=1000, le=500000)
    move_in: str = Field(pattern=r"^\d{4}-\d{2}$")        # YYYY-MM
    sleep: Literal["early", "normal", "late"]               # before 11pm / 11pm-1am / after 1am
    smoking: Freq
    smoke_ok: bool                                          # fine living with a smoker?
    drinking: Freq
    drink_ok: bool
    food: Literal["veg", "egg", "nonveg"]
    cleanliness: int = Field(ge=1, le=5)
    guests: Literal["rarely", "sometimes", "often"]
    noise: Literal["quiet", "moderate", "lively"]
    pets: bool = False
    interests: list[str] = Field(default_factory=list, max_length=12)
    languages: list[str] = Field(default_factory=list, max_length=6)
    bio: str = Field(default="", max_length=400)

    @field_validator("city")
    @classmethod
    def known_city(cls, v):
        if v not in LOCALITIES:
            raise ValueError(f"City must be one of {', '.join(LOCALITIES)}")
        return v

    @field_validator("interests", "languages")
    @classmethod
    def clean_tags(cls, v):
        return sorted({t.strip().lower()[:30] for t in v if t.strip()})

    @model_validator(mode="after")
    def check(self):
        if self.budget_max < self.budget_min:
            raise ValueError("Max budget must be at least the min budget")
        bad = [l for l in self.localities if l not in LOCALITIES[self.city]]
        if bad:
            raise ValueError(f"Unknown localities for {self.city}: {', '.join(bad)}")
        if len("".join(c for c in self.phone if c.isdigit())[-10:]) != 10:
            raise ValueError("Enter a valid 10-digit phone number")
        return self


def gender_ok(a: dict, b: dict) -> bool:
    return (a["pref_gender"] in ("any", b["gender"])) and (b["pref_gender"] in ("any", a["gender"]))


def _habit(me: dict, them: dict, habit: str, ok_key: str, label: str, good: list, bad: list) -> float:
    """Mutual tolerance check for smoking / drinking."""
    i_do, they_do = me[habit] != "never", them[habit] != "never"
    if they_do and not me[ok_key]:
        bad.append(f"They {label} {them[habit]}, you prefer someone who doesn't")
        return 0.0
    if i_do and not them[ok_key]:
        bad.append(f"You {label}, they prefer someone who doesn't")
        return 0.0
    if not i_do and not they_do:
        good.append(f"Neither of you {label}s" if label != "smoke" else "Both non-smokers")
        return 1.0
    return 0.75 if me[habit] != them[habit] else 1.0


def compatibility(me: dict, them: dict) -> dict:
    good, bad, s = [], [], {}

    lo, hi = max(me["budget_min"], them["budget_min"]), min(me["budget_max"], them["budget_max"])
    if hi >= lo:
        s["budget"] = 1.0
        good.append(f"Budgets overlap (₹{lo:,}–₹{hi:,} each)")
    else:
        gap = lo - hi
        s["budget"] = max(0.0, 1 - gap / max(me["budget_max"], 1))
        bad.append(f"Budgets don't overlap (₹{gap:,} apart)")

    d = abs(LEVEL3[me["sleep"]] - LEVEL3[them["sleep"]])
    s["sleep"] = [1, 0.5, 0][d]
    sleep_name = {"early": "early sleepers", "normal": "sleep around midnight", "late": "night owls"}
    if d == 0:
        good.append(f"Both {sleep_name[me['sleep']]}")
    elif d == 2:
        bad.append("Very different sleep schedules")

    s["smoking"] = _habit(me, them, "smoking", "smoke_ok", "smoke", good, bad)
    s["drinking"] = _habit(me, them, "drinking", "drink_ok", "drink", good, bad)

    if me["food"] == them["food"]:
        s["food"] = 1.0
        good.append({"veg": "Both vegetarian", "egg": "Both eggetarian", "nonveg": "Both non-veg"}[me["food"]])
    elif "veg" in (me["food"], them["food"]) and "nonveg" in (me["food"], them["food"]):
        s["food"] = 0.3
        bad.append("Veg and non-veg: discuss kitchen rules")
    else:
        s["food"] = 0.7

    cd = abs(me["cleanliness"] - them["cleanliness"])
    s["cleanliness"] = 1 - cd / 4
    if cd == 0:
        good.append("Same cleanliness level")
    elif cd >= 2:
        bad.append("Different cleanliness standards")

    for key, label in (("guests", "guests"), ("noise", "noise level")):
        diff = abs(LEVEL3[me[key]] - LEVEL3[them[key]])
        s[key] = [1, 0.6, 0.1][diff]
        if diff == 0:
            good.append(f"Same preference for {label}")
        elif diff == 2:
            bad.append(f"Very different about {label}")

    my, mm = map(int, me["move_in"].split("-"))
    ty, tm = map(int, them["move_in"].split("-"))
    months = abs((my * 12 + mm) - (ty * 12 + tm))
    s["move_in"] = [1, 0.6, 0.2][min(months, 2)]
    if months == 0:
        good.append("Moving in the same month")

    common = set(me["interests"]) & set(them["interests"])
    union = set(me["interests"]) | set(them["interests"])
    s["interests"] = min(1.0, len(common) / max(3, len(union) / 2)) if union else 0.5
    if common:
        good.append("Common interests: " + ", ".join(sorted(common)[:4]))

    same_college = bool(me["college"]) and me["college"].strip().lower() == them["college"].strip().lower()
    s["college"] = 1.0 if same_college else 0.5
    if same_college:
        good.append(f"Same college: {them['college']}")

    if me["pets"] != them["pets"]:
        bad.append("One of you has / wants pets")

    score = round(sum(WEIGHTS[k] * v for k, v in s.items()))
    if any("prefer someone who doesn't" in b for b in bad):
        score = min(score, 45)  # a deal-breaker caps the score
    return {"score": score, "good": good, "bad": bad, "breakdown": {k: round(v, 2) for k, v in s.items()}}


# ---------- storage helpers ----------

def _load(row) -> dict:
    return {**json.loads(row["data"]), "id": row["id"]}


def me_or_404(token: str):
    with db.connect() as con:
        row = con.execute("SELECT * FROM roommates WHERE token = ?", (token,)).fetchone()
    if not row:
        raise HTTPException(404, "Profile not found")
    return row


PUBLIC = ["id", "name", "age", "gender", "college", "occupation", "city", "localities", "budget_min", "budget_max",
          "move_in", "sleep", "smoking", "drinking", "food", "cleanliness", "guests", "noise", "pets", "interests",
          "languages", "bio"]


def public(p: dict) -> dict:
    return {k: p.get(k) for k in PUBLIC}


def flats_for_pair(a: dict, b: dict, limit: int = 3) -> list[dict]:
    """Vacant 2BHK+ flats in the city that fit both budgets together."""
    total = a["budget_max"] + b["budget_max"]
    with db.connect() as con:
        rows = con.execute(
            "SELECT id, title, locality, rent, bhk FROM listings WHERE city = ? AND available = 1 AND bhk >= 2"
            " AND risk_level != 'high' AND rent <= ? ORDER BY rent", (a["city"], total)).fetchall()
    prefs = set(a["localities"]) | set(b["localities"])
    flats = sorted((dict(r) for r in rows), key=lambda r: (r["locality"] not in prefs, r["rent"]))
    return [{**f, "each_pays": f["rent"] // 2} for f in flats[:limit]]


# ---------- API ----------

@router.post("/api/roommates")
def create_profile(p: Profile, authorization: str | None = Header(None)):
    pid, token = secrets.token_hex(5), secrets.token_urlsafe(16)
    data = p.model_dump()
    phone = db.normalize_phone(data.pop("phone"))
    with db.connect() as con:
        con.execute("INSERT INTO roommates (id, token, data, phone, city) VALUES (?,?,?,?,?)",
                    (pid, token, json.dumps(data), phone, p.city))
    account = auth.current_account(authorization)
    if account:
        auth.set_roommate_token(account["id"], token)
    return {"id": pid, "token": token}


@router.put("/api/roommates/{token}")
def update_profile(token: str, p: Profile):
    row = me_or_404(token)
    data = p.model_dump()
    phone = db.normalize_phone(data.pop("phone"))
    with db.connect() as con:
        con.execute("UPDATE roommates SET data = ?, phone = ?, city = ? WHERE id = ?",
                    (json.dumps(data), phone, p.city, row["id"]))
    return {"ok": True}


@router.post("/api/roommates/{token}/active")
def set_active(token: str, body: dict):
    row = me_or_404(token)
    with db.connect() as con:
        con.execute("UPDATE roommates SET active = ? WHERE id = ?", (int(bool(body.get("active"))), row["id"]))
    return {"active": bool(body.get("active"))}


@router.get("/api/roommates/{token}")
def my_dashboard(token: str):
    row = me_or_404(token)
    me = _load(row)
    with db.connect() as con:
        others = con.execute("SELECT * FROM roommates WHERE city = ? AND id != ? AND active = 1",
                             (row["city"], row["id"])).fetchall()
        reqs = con.execute("SELECT * FROM roommate_requests WHERE from_id = ? OR to_id = ?",
                           (row["id"], row["id"])).fetchall()
        phones = {r["id"]: r["phone"] for r in con.execute("SELECT id, phone FROM roommates").fetchall()}
        everyone = {r["id"]: _load(r) for r in con.execute("SELECT * FROM roommates").fetchall()}

    by_other = {}
    for r in reqs:
        other = r["to_id"] if r["from_id"] == row["id"] else r["from_id"]
        by_other[other] = {"id": r["id"], "status": r["status"], "message": r["message"],
                           "direction": "sent" if r["from_id"] == row["id"] else "received"}

    def card(o: dict) -> dict:
        c = {**public(o), "match": compatibility(me, o), "request": by_other.get(o["id"])}
        if c["request"] and c["request"]["status"] == "accepted":
            c["contact"] = {"phone": phones[o["id"]], "whatsapp": f"https://wa.me/91{phones[o['id']]}"}
            c["flats"] = flats_for_pair(me, o)
        return c

    matches = [card(_load(o)) for o in others if gender_ok(me, _load(o))]
    matches.sort(key=lambda c: c["match"]["score"], reverse=True)
    incoming = [card(everyone[oid]) for oid, r in by_other.items()
                if r["direction"] == "received" and r["status"] == "pending" and oid in everyone]
    return {"me": {**public(me), "phone": phones[row["id"]], "active": bool(row["active"])},
            "matches": matches, "incoming": incoming}


class ConnectIn(BaseModel):
    to_id: str
    message: str = Field(default="", max_length=300)


@router.post("/api/roommates/{token}/connect")
def connect(token: str, c: ConnectIn):
    row = me_or_404(token)
    if c.to_id == row["id"]:
        raise HTTPException(400, "You can't connect with yourself")
    with db.connect() as con:
        target = con.execute("SELECT * FROM roommates WHERE id = ? AND active = 1", (c.to_id,)).fetchone()
        if not target or not gender_ok(_load(row), _load(target)):
            raise HTTPException(404, "Profile not found")
        reverse = con.execute("SELECT id FROM roommate_requests WHERE from_id = ? AND to_id = ? AND status = 'pending'",
                              (c.to_id, row["id"])).fetchone()
        if reverse:  # they already asked you, so this counts as accepting
            con.execute("UPDATE roommate_requests SET status = 'accepted' WHERE id = ?", (reverse["id"],))
            return {"status": "accepted"}
        if con.execute("SELECT 1 FROM roommate_requests WHERE from_id = ? AND to_id = ?",
                       (row["id"], c.to_id)).fetchone():
            raise HTTPException(409, "Request already sent")
        con.execute("INSERT INTO roommate_requests (id, from_id, to_id, message) VALUES (?,?,?,?)",
                    (secrets.token_hex(5), row["id"], c.to_id, c.message.strip()))
    return {"status": "pending"}


class Decision(BaseModel):
    status: Literal["accepted", "declined"]


@router.post("/api/roommates/{token}/requests/{request_id}")
def respond(token: str, request_id: str, d: Decision):
    row = me_or_404(token)
    with db.connect() as con:
        cur = con.execute("UPDATE roommate_requests SET status = ? WHERE id = ? AND to_id = ? AND status = 'pending'",
                          (d.status, request_id, row["id"]))
    if not cur.rowcount:
        raise HTTPException(404, "Request not found")
    return {"status": d.status}
