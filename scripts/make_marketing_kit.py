"""Make a ready-to-share marketing kit for GharSure.

Run:  .venv/bin/python -m scripts.make_marketing_kit https://your-live-link.onrender.com
Creates marketing/: poster.png (A4, print for notice boards), qr.png, whatsapp.txt, linkedin.txt, instagram.txt
"""
import sys
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "marketing"
INK, VIOLET, GOLD, WHITE, SOFT = (18, 13, 51, 255), (109, 74, 255, 255), (245, 181, 68, 255), (255, 255, 255, 255), (207, 200, 245, 255)

FONT_FILE = OUT / "fonts" / "PlusJakartaSans.ttf"   # Google Fonts, SIL Open Font License
FALLBACKS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
S = 2  # draw at 2x (2480x3508 = A4 at 300 dpi, print quality)


def font(size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(str(FONT_FILE), size * S)
        f.set_variation_by_axes([weight])
        return f
    except OSError:
        for name in FALLBACKS:
            try:
                return ImageFont.truetype(name, size * S)
            except OSError:
                continue
    return ImageFont.load_default()


def glow(img: Image.Image, box, color, alpha: int, blur: int) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([v * S for v in box], fill=(*color[:3], alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * S)))


def glass(img: Image.Image, box, radius: int, fill_alpha: int = 20, line_alpha: int = 45) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([v * S for v in box], radius=radius * S, fill=(255, 255, 255, fill_alpha),
                                            outline=(255, 255, 255, line_alpha), width=2 * S)
    img.alpha_composite(layer)


def text(d: ImageDraw.ImageDraw, xy, t: str, f, fill) -> int:
    """Draw text at design coordinates; returns the right edge (design units)."""
    d.text((xy[0] * S, xy[1] * S), t, font=f, fill=fill)
    return xy[0] + d.textlength(t, font=f) / S


def house_icon(d: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    u = size / 64
    d.rounded_rectangle([x * S, y * S, (x + size) * S, (y + size) * S], radius=int(16 * u * S), fill=VIOLET)
    d.polygon([((x + 32 * u) * S, (y + 12 * u) * S), ((x + 54 * u) * S, (y + 30 * u) * S),
               ((x + 10 * u) * S, (y + 30 * u) * S)], fill=GOLD)
    d.rectangle([(x + 17 * u) * S, (y + 29 * u) * S, (x + 47 * u) * S, (y + 52 * u) * S], fill=WHITE)
    d.line([((x + 25 * u) * S, (y + 41 * u) * S), ((x + 30 * u) * S, (y + 46 * u) * S),
            ((x + 40 * u) * S, (y + 35 * u) * S)], fill=VIOLET, width=int(4 * u * S))


def poster(url: str) -> Image.Image:
    w, h = 1240, 1754
    img = Image.new("RGBA", (w * S, h * S))
    d = ImageDraw.Draw(img)
    for y in range(h * S):  # deep night gradient
        t = y / (h * S)
        d.line([(0, y), (w * S, y)], fill=(int(13 + 20 * t), int(9 + 14 * t), int(38 + 62 * t), 255))
    glow(img, (-260, -220, 760, 700), (124, 92, 255), 150, 160)
    glow(img, (880, -260, 1500, 360), (255, 196, 92), 70, 170)
    glow(img, (600, 1250, 1500, 2050), (124, 92, 255), 120, 170)
    d = ImageDraw.Draw(img)
    for gx in range(40, w, 48):  # fine dot grid
        for gy in range(40, h, 48):
            d.ellipse([(gx - 1) * S, (gy - 1) * S, (gx + 1) * S, (gy + 1) * S], fill=(255, 255, 255, 9))

    # brand row
    house_icon(d, 90, 86, 64)
    x = text(d, (172, 92), "Ghar", font(46), WHITE)
    text(d, (x, 92), "Sure", font(46), GOLD)
    glass(img, (850, 92, 1150, 146), 27, 22, 60)
    d = ImageDraw.Draw(img)
    d.ellipse([876 * S, 112 * S, 890 * S, 126 * S], fill=(52, 211, 153))
    text(d, (902, 104), "AI-VERIFIED RENTALS", font(19, 700), WHITE)

    # headline
    text(d, (90, 250), "Find a home", font(116), WHITE)
    x = text(d, (90, 386), "you can ", font(116), WHITE)
    text(d, (x, 386), "trust.", font(116), GOLD)
    text(d, (92, 560), "Flats straight from owners, roommates who match your vibe,", font(31, 500), SOFT)
    text(d, (92, 604), "and an AI that spots scams before you pay a rupee.", font(31, 500), SOFT)

    # feature cards
    feats = [("AI", "Scam shield", "Every photo, price & message checked"),
             ("0%", "Zero brokerage", "Talk to owners directly"),
             ("2+", "Roommate match", "Sleep time, food, smoking, budget"),
             ("\u20b9", "Rent & bills", "Paid straight to your owner's UPI")]
    for i, (badge, title, sub) in enumerate(feats):
        cx, cy = 90 + (i % 2) * 545, 720 + (i // 2) * 215
        glass(img, (cx, cy, cx + 515, cy + 190), 30)
        d = ImageDraw.Draw(img)
        d.ellipse([(cx + 30) * S, (cy + 30) * S, (cx + 100) * S, (cy + 100) * S], fill=VIOLET if i % 3 == 0 else GOLD)
        bw = d.textlength(badge, font=font(28)) / S
        text(d, (cx + 65 - bw / 2, cy + 47), badge, font(28), WHITE if i % 3 == 0 else INK)
        text(d, (cx + 30, cy + 118), title, font(32), WHITE)
        text(d, (cx + 30, cy + 156), sub, font(20, 500), SOFT)

    # QR panel
    glass(img, (90, 1180, 1150, 1590), 40, 26, 70)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([130 * S, 1220 * S, 460 * S, 1550 * S], radius=28 * S, fill=WHITE)
    qr = qrcode.QRCode(box_size=10, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    q = qr.make_image(fill_color=INK, back_color=WHITE).convert("RGBA").resize((290 * S, 290 * S), Image.Resampling.NEAREST)
    img.alpha_composite(q, (150 * S, 1240 * S))
    d = ImageDraw.Draw(img)
    text(d, (510, 1250), "Scan to find your", font(46), WHITE)
    text(d, (510, 1312), "flat or flatmate", font(46), WHITE)
    text(d, (512, 1400), url.replace("https://", ""), font(28, 700), GOLD)
    text(d, (512, 1452), "Opens like an app. No download needed.", font(22, 500), SOFT)
    text(d, (512, 1490), "Owners list free. Students post rooms free.", font(22, 500), SOFT)

    # footer
    d.line([(90 * S, 1650 * S), (1150 * S, 1650 * S)], fill=(255, 255, 255, 40), width=2 * S)
    text(d, (90, 1676), "Never pay before visiting.  Scammed? Call 1930", font(22, 600), SOFT)
    text(d, (1012, 1676), "gharsure", font(22, 800), GOLD)
    return img.convert("RGB")


def texts(url: str) -> dict[str, str]:
    return {
        "whatsapp.txt": f"""🏡 *GharSure: find a home you can trust*

Looking for a flat or PG near college? Or a roommate who's actually like you?

✅ Flats direct from owners, *no brokerage*
🛡️ AI checks every listing for fake photos and scam messages
👥 Roommate matching (sleep time, smoking, food, budget…)
🚪 Leaving your flat? Post it for the next tenant
🧾 Pay rent and bills straight to your owner's UPI

Try it 👉 {url}
(Works like an app: tap "Add to Home Screen")
""",
        "linkedin.txt": f"""I built GharSure, an AI platform that protects students from rental scams. 🏡

The problem: every year, students moving to a new city lose token money to fake flat listings: stolen photos, "too good to be true" rent, and the classic "I'm an army officer, I'll courier the keys" story.

What GharSure does:
🛡️ A C++ perceptual-hashing engine detects stolen listing photos, even after cropping, filters or watermarks
🤖 ML models flag rents far below the area's fair price and scam-style messages (English + Hinglish), with an explainable 0–100 risk score
🏠 Owners list directly (no broker); renters browse a map and book visits like a hotel
👥 Roommate matching with a compatibility score and the reasons behind it
🧾 Rent, bills and deposits tracked in one place, paid directly to the owner's UPI

Tech: C++20 + pybind11, Python, FastAPI, scikit-learn, PostgreSQL, Leaflet maps, installable PWA.

🔗 Live: {url}
💻 Code: https://github.com/Sid454/gharsure

Feedback welcome, and if you're a student hunting for a flat, try it and tell me what's missing!

#FinalYearProject #MachineLearning #Python #CPP #FastAPI #StudentProject #PropTech
""",
        "instagram.txt": f"""Flat hunting shouldn't feel like a scam hunt. 🏡🛡️

GharSure checks every listing with AI, so you only see real flats from real owners. Plus: roommate matching, zero brokerage, and rent paid straight to your owner.

🔗 Link in bio: {url}
#flathunting #pg #roommate #studentlife #rentsafe
""",
    }


def main() -> None:
    url = (sys.argv[1] if len(sys.argv) > 1 else "https://gharsure.onrender.com").rstrip("/")
    OUT.mkdir(exist_ok=True)
    big = poster(url)
    big.save(OUT / "poster-print.png", dpi=(300, 300))   # A4, 300 dpi for printing
    big.resize((1240, 1754), Image.Resampling.LANCZOS).save(OUT / "poster.png", dpi=(150, 150))  # for WhatsApp/Instagram
    qrcode.make(url, box_size=12, border=2).save(OUT / "qr.png")
    for name, body in texts(url).items():
        (OUT / name).write_text(body, encoding="utf-8")
    print(f"Marketing kit for {url} -> {OUT}")


if __name__ == "__main__":
    main()
