# 🏡 GharSure AI: Rent safe. Live happy.

**An AI-powered rental platform that catches fake listings and broker scams**, lets owners list flats directly (no broker),
lets tenants book visits like a hotel, and manages rent, bills and deposits after move-in.

> Final year B.Tech project · C++ (performance core) + Python (AI + backend) + JavaScript (installable app)

---

## The problem
Students and job-seekers moving to a new city get scammed by fake PG/flat listings: stolen photos, rent that is
"too good to be true", the *"I'm an army officer, I'll courier the keys, just pay the token"* story, and fake brokers
who disappear with the deposit. After moving in, rent, water and electricity bills and the deposit are tracked on paper or WhatsApp.

## What GharSure does
| Feature | How it works |
|---|---|
| 🛡️ **AI scam detector** | Every listing gets a 0–100 risk score with clear reasons, built from 4 signals (below) |
| 🖼️ **Stolen photo detection** | C++ perceptual-hash engine finds the same photo even after crop, filter, mirror or watermark |
| 💰 **Fair rent predictor** | Gradient Boosting model flags rents far below the area's fair price |
| 📝 **Scam text classifier** | TF-IDF + Logistic Regression on English/Hinglish, plus explainable red-flag rules |
| 🚩 **Community reports** | Users report scam numbers (stored only as salted hashes) |
| 🏠 **Owner listings** | Owners post flats with photos and pin the location on a map; high-risk listings are auto-blocked |
| 🗺️ **Map + hotel-style booking** | Browse vacant flats on a map, open the details, and *request a visit* with dates |
| 🤝 **Direct connect** | The owner's phone/WhatsApp is revealed only after they accept, which protects both sides |
| 🧾 **Rent & bills** | Owner raises rent/water/electricity bills; tenant pays the owner's UPI directly (QR / UPI link), enters the UTR, owner confirms |
| 💵 **Deposit tracking** | Deposit held, refunds and full payment history in one ledger |
| 👤 **Owner & Renter accounts** | Sign up with phone + password (salted scrypt). One account switches between Owner mode and Renter mode |
| 📊 **Owner dashboard** | Overview (flats, vacant, new requests, rent collected, dues, deposits) → My flats → Visit requests → Tenants & bills → Add flat |
| 👥 **Roommate matching** | Students set habits (sleep time, smoking, drinking, food, cleanliness, guests, noise, budget, interests); AI gives a compatibility % with reasons; contact unlocks only when both agree; suggests flats that fit the combined budget |
| 💬 **Safety assistant** | Retrieval (RAG) over a verified knowledge base; answers include their source |
| 📱 **Installable app (PWA)** | Bottom tab bar, bottom-sheet details, "Add to Home Screen", works offline for the app shell |

> **GharSure never holds money.** Payments go straight from tenant to owner via UPI. That keeps it legal (no payment
> licence needed) and is the core safety message of the app.

## Architecture
```
 Installable web app (HTML/CSS/JS + Leaflet map, PWA)
                 │ REST (JSON / multipart)
 ┌───────────────▼──────────────────────────────────────────┐
 │ FastAPI backend (Python)                                 │
 │  listings · bookings · owner dashboard · tenancy & bills │
 │  Risk Fusion Engine → score + reasons                    │
 └──┬──────────────┬──────────────┬──────────────┬──────────┘
    │              │              │              │
 ⚡ C++ core     Scam text      Fair-rent      Safety assistant
 (pybind11)     classifier     regressor      (TF-IDF retrieval)
 pHash + dHash  TF-IDF + LR    Gradient       over knowledge.md
 Hamming index  + rules        Boosting
                 SQLite: listings · fingerprints · bookings · tenancies · bills · reports
```

### The C++ engine (`cpp/rentshield_core.cpp`)
- **pHash**: separable 2-D DCT of a 32×32 grayscale image, keeping the 8×8 low-frequency block → 64-bit fingerprint
- **dHash**: gradient-direction fingerprint used as a second check
- **ImageIndex**: thread-safe in-memory index searched with hardware `popcount` Hamming distance; releases the Python GIL during queries
- Each stored photo also keeps center-crop (90/80/70%) and mirrored variants, so edited re-uploads still match

Measured on the demo images: different rooms are **≥14 bits** apart, while a cropped + recoloured + watermarked copy is
**6 bits** from the original (threshold = 10).

### Risk score
| Signal | Max points |
|---|---|
| Photo found in another listing (more if in another city) | 35 |
| Rent ≥45% below AI fair rent (12 if ≥25% below) | 25 |
| Scam wording (ML probability + red-flag rules) | 35 |
| Phone number reported by users | 25 |

0–29 **low** · 30–59 **medium** · 60+ **high** (blocked from the public site)

## Run it
Needs Python 3.11+ and a C++20 compiler (Xcode Command Line Tools on Mac, `build-essential` on Linux).

```bash
./run.sh            # creates .venv, builds the C++ engine, seeds demo data, starts the server
./run.sh --reset    # same, but recreates the demo data
```
Open **http://127.0.0.1:8000**. The seed step prints owner-dashboard and tenant links.
On a phone (same Wi-Fi), run uvicorn with `--host 0.0.0.0` and open `http://<laptop-ip>:8000`.

### Try the demo
Demo accounts (test-only, created by the seed script):

| Mode | Phone | Password |
|---|---|---|
| Owner (Sunita, owns the Pune flats, has a tenant with bills) | 9000000100 | demo1234 |
| Renter (Aarav, has a booking + roommate profile + a roommate request) | 9000000200 | demo1234 |

1. **Explore**: flats on the map → open one → *Request to book visit*
2. **Scam check**: paste `demo/scam_message.txt`, choose Mumbai / Andheri, 2 BHK, 950 sq ft, rent 9000,
   phone 9000000001, and upload `demo/stolen_photo_edited.jpg` → **risk 100/100** with every reason
3. **Owner dashboard** (link printed by seed): accept the booking → *Move tenant in* → raise bills → confirm payments
4. **My booking** (tenant link printed by seed): owner contact, rent & bills, pay via UPI QR

### Tests
```bash
.venv/bin/python -m pytest -q
```
Covers the C++ hashing robustness, genuine vs scam listings, the full booking → tenancy → bills → deposit flow,
access control between owners, and input validation.

## Project structure
```
cpp/rentshield_core.cpp   C++ image fingerprint engine (pybind11)
app/main.py               FastAPI app: listings, bookings, owner dashboard, scam check
app/tenancy.py            Rent, bills, deposit, UPI QR
app/risk.py               Risk fusion engine
app/imaging.py            Pillow decoding + C++ hashing/search
app/text_model.py         Scam text classifier + red-flag rules
app/rent_model.py         Fair-rent model
app/assistant.py          Safety assistant (retrieval)
app/auth.py               Accounts, sessions, owner/renter modes
app/roommates.py          Roommate profiles, compatibility scoring, mutual connect
app/db.py                 SQLite storage
static/                   Installable web app (index.html, app.js, style.css, sw.js, manifest)
data/seed/                Scam text dataset + knowledge base
scripts/seed_demo.py      Demo data + demo scam files
tests/test_app.py         End-to-end tests
```

## Honest limitations (and next steps for the report)
- **Datasets are small/sample.** `data/rent_data.csv` is generated sample data, and the scam dataset has ~60 hand-written
  examples. Next: a real rent dataset (e.g. Kaggle "House Rent Prediction"), 1–2k labelled real scam messages, and a fine-tuned
  DistilBERT/IndicBERT model, with precision/recall reported.
- **Image search is a linear scan** (fast up to ~1 lakh photos thanks to popcount). Next: multi-index hashing or HNSW
  over CLIP embeddings for "same room, different photo".
- **Sign-in uses phone + password** (no OTP yet). Next: phone OTP verification, and moving sessions to HttpOnly cookies.
- **No payment gateway, by design.** UPI goes directly to the owner; a Razorpay Route integration could be added later.
- Listing photos come only from owners on the platform. Collect any external reference photos only from public pages,
  following each site's terms and robots.txt.
