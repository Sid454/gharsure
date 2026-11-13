"""Risk fusion: combine photo, price, text and community signals into one 0-100 score."""
from dataclasses import dataclass, field

from . import db, imaging
from .rent_model import RentModel
from .text_model import ScamTextModel, red_flags


@dataclass
class ListingInput:
    text: str = ""
    city: str = ""
    locality: str = ""
    bhk: int | None = None
    sqft: int | None = None
    furnishing: str = "semi-furnished"
    rent: int | None = None
    phone: str = ""
    images: list[bytes] = field(default_factory=list)
    listing_id: str = ""  # when checking our own listing, ignore its own photos


def level_for(score: int) -> str:
    return "high" if score >= 60 else "medium" if score >= 30 else "low"


def analyze(inp: ListingInput, text_model: ScamTextModel, rent_model: RentModel) -> dict:
    reasons: list[dict] = []
    parts: dict[str, int] = {}

    # 1. Reused photos (C++ perceptual-hash index)
    photo_matches = []
    for i, data in enumerate(inp.images):
        for m in imaging.index_query(data, exclude_listing=inp.listing_id)[:3]:
            meta = db.fingerprint_meta(m.image_id)
            photo_matches.append({
                "uploaded_photo": i + 1,
                "similarity": round(m.similarity * 100),
                "matched_city": meta["city"] if meta else None,
                "matched_listing": (meta["title"] if meta and meta["title"] else m.listing_id),
                "source": meta["source"] if meta else None,
            })
    if photo_matches:
        other_cities = {p["matched_city"] for p in photo_matches
                        if p["matched_city"] and inp.city and p["matched_city"] != inp.city}
        parts["photos"] = 35 if other_cities else 25
        detail = f"{len(photo_matches)} photo match(es) found in other listings"
        if other_cities:
            detail += f", including other cities: {', '.join(sorted(other_cities))}"
        reasons.append({"signal": "Reused photos", "severity": "high", "detail": detail})

    # 2. Price far below market (Gradient Boosting fair-rent model)
    price = None
    if inp.rent and inp.city and inp.locality and inp.bhk and inp.sqft:
        fair = rent_model.predict(inp.city, inp.locality, inp.bhk, inp.sqft, inp.furnishing)
        gap = (inp.rent - fair) / fair
        price = {"fair_rent": fair, "listed_rent": inp.rent, "gap_percent": round(gap * 100)}
        if gap <= -0.45:
            parts["price"] = 25
            reasons.append({"signal": "Too cheap", "severity": "high",
                            "detail": f"Rent is {abs(round(gap * 100))}% below the estimated fair rent of ₹{fair:,}"})
        elif gap <= -0.25:
            parts["price"] = 12
            reasons.append({"signal": "Below market", "severity": "medium",
                            "detail": f"Rent is {abs(round(gap * 100))}% below the estimated fair rent of ₹{fair:,}"})

    # 3. Scam language (ML probability + explainable rules)
    text = text_model.predict(inp.text)
    flags = red_flags(inp.text)
    text_score = round(text["probability"] * 25) + min(len(flags) * 5, 15)
    if text_score >= 8:
        parts["text"] = min(text_score, 35)
        reasons.append({"signal": "Scam-like wording", "severity": "high" if text["probability"] > 0.7 else "medium",
                        "detail": f"AI scam probability {round(text['probability'] * 100)}%"
                                  + (f"; trigger words: {', '.join(text['top_terms'])}" if text["top_terms"] else "")})
    for flag in flags:
        reasons.append({"signal": "Red flag", "severity": "medium", "detail": flag})

    # 4. Community reports on the phone number (stored hashed)
    reports = db.count_reports(inp.phone) if inp.phone else 0
    if reports:
        parts["reports"] = min(10 + reports * 5, 25)
        reasons.append({"signal": "Reported number", "severity": "high",
                        "detail": f"This phone number was reported {reports} time(s) by other users"})

    score = min(sum(parts.values()), 100)
    if not reasons:
        reasons.append({"signal": "No red flags", "severity": "low",
                        "detail": "Nothing suspicious found. Still visit in person before paying anything."})
    return {
        "score": score,
        "level": level_for(score),
        "breakdown": parts,
        "reasons": reasons,
        "price": price,
        "photo_matches": photo_matches,
        "text": {**text, "red_flags": flags},
        "reports": reports,
        "disclaimer": "AI risk estimate, not a verdict. Never pay before visiting and signing an agreement.",
    }
