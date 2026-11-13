"""Nine Instagram feed posts (1080x1350) explaining GharSure, plus captions and a grid preview.

Run:  .venv/bin/python -m scripts.make_instagram_posts https://your-live-link.onrender.com
Output: marketing/instagram/01.png ... 09.png, captions.txt, grid-preview.png
Post them in order 09 -> 01 (Instagram shows the newest first), so 01 sits top-left of the grid.
"""
import sys
import textwrap

import qrcode
from PIL import Image, ImageDraw


def draw(img):
    d = ImageDraw.Draw(img)
    d._image = img
    return d

from scripts.make_marketing_kit import GOLD, INK, OUT, S, SOFT, VIOLET, WHITE, font, glass, glow, house_icon, text
from scripts.seed_demo import room_photo, stolen_edit

W, H = 1080, 1350
DIR = OUT / "instagram"
LIGHT_BG, LIGHT_INK, LIGHT_MUTED = (247, 246, 251, 255), (22, 18, 46, 255), (110, 106, 133, 255)
GREEN, RED, LINE = (22, 163, 94, 255), (217, 48, 37, 255), (235, 232, 244, 255)


# ---------- canvas helpers ----------

def dark_canvas() -> Image.Image:
    img = Image.new("RGBA", (W * S, H * S))
    d = draw(img)
    for y in range(H * S):
        t = y / (H * S)
        d.line([(0, y), (W * S, y)], fill=(int(13 + 22 * t), int(9 + 15 * t), int(38 + 66 * t), 255))
    glow(img, (-240, -200, 640, 620), (124, 92, 255), 140, 150)
    glow(img, (720, -220, 1300, 300), (255, 196, 92), 60, 160)
    glow(img, (520, 1000, 1400, 1700), (124, 92, 255), 110, 170)
    return img


def light_canvas() -> Image.Image:
    img = Image.new("RGBA", (W * S, H * S), LIGHT_BG)
    glow(img, (600, -260, 1360, 420), (124, 92, 255), 45, 170)
    glow(img, (-300, 980, 520, 1700), (255, 196, 92), 55, 170)
    return img


def box(d, xy, r, fill, outline=None, width=2):
    if fill is not None and len(fill) == 4 and fill[3] < 255 and hasattr(d, "_image"):
        layer = Image.new("RGBA", d._image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle([v * S for v in xy], radius=r * S, fill=fill)
        d._image.alpha_composite(layer)
        fill = None
    if fill is not None or outline is not None:
        d.rounded_rectangle([v * S for v in xy], radius=r * S, fill=fill, outline=outline, width=width * S if outline else 0)


def shadow_card(img, xy, r, fill=WHITE):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = xy
    ImageDraw.Draw(sh).rounded_rectangle([x0 * S, (y0 + 14) * S, x1 * S, (y1 + 14) * S], radius=r * S, fill=(30, 20, 80, 46))
    from PIL import ImageFilter
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22 * S)))
    box(draw(img), xy, r, fill, LINE, 2)


def wrap(d, xy, t, f, fill, width_chars, line_h):
    x, y = xy
    for line in textwrap.wrap(t, width_chars):
        text(d, (x, y), line, f, fill)
        y += line_h
    return y


def header(d, dark: bool, n: int):
    house_icon(d, 70, 64, 52)
    x = text(d, (136, 69), "Ghar", font(34), WHITE if dark else LIGHT_INK)
    text(d, (x, 69), "Sure", font(34), GOLD)
    text(d, (W - 150, 76), f"{n:02d} / 09", font(22, 700), SOFT if dark else LIGHT_MUTED)


SITE = "gharsure.onrender.com"


def footer(d, dark: bool, label: str = "Link in bio"):
    col = SOFT if dark else LIGHT_MUTED
    text(d, (70, H - 92), label, font(22, 700), col)
    f = font(22, 700)
    text(d, (W - 70 - d.textlength(SITE, font=f) / S, H - 92), SITE, f, GOLD if dark else (109, 74, 255, 255))


def ring(d, cx, cy, r, pct, color, track, width=26):
    bbox = [(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S]
    if len(track) == 4 and track[3] < 255 and hasattr(d, "_image"):  # blend a translucent track
        layer = Image.new("RGBA", d._image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).arc(bbox, 0, 360, fill=track, width=width * S)
        d._image.alpha_composite(layer)
    else:
        d.arc(bbox, 0, 360, fill=track, width=width * S)
    d.arc(bbox, -90, -90 + int(360 * pct / 100), fill=color, width=width * S)


def centered(d, cx, y, t, f, fill):
    text(d, (cx - d.textlength(t, font=f) / S / 2, y), t, f, fill)


def pill(d, xy, label, fill, ink, size=22):
    f = font(size, 700)
    w = d.textlength(label, font=f) / S + 36
    box(d, (xy[0], xy[1], xy[0] + w, xy[1] + size + 26), (size + 26) // 2, fill)
    text(d, (xy[0] + 18, xy[1] + 11), label, f, ink)
    return xy[0] + w


def photo(img, xy, seed, r=28, edited=False):
    x0, y0, x1, y1 = xy
    src = stolen_edit(room_photo(seed)) if edited else room_photo(seed)
    p = src.convert("RGBA").resize(((x1 - x0) * S, (y1 - y0) * S))
    mask = Image.new("L", p.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, p.size[0], p.size[1]], radius=r * S, fill=255)
    img.paste(p, (x0 * S, y0 * S), mask)


def finish(img) -> Image.Image:
    return img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")


# ---------- the nine posts ----------

def p1_intro():
    img = dark_canvas(); d = draw(img)
    header(d, True, 1)
    glass(img, (70, 250, 470, 302), 26, 22, 60); d = draw(img)
    d.ellipse([94 * S, 269 * S, 108 * S, 283 * S], fill=(52, 211, 153, 255))
    text(d, (120, 262), "AI-VERIFIED RENTALS", font(20, 700), WHITE)
    text(d, (66, 360), "Find a", font(128), WHITE)
    text(d, (66, 510), "home you", font(128), WHITE)
    x = text(d, (66, 660), "can ", font(128), WHITE)
    text(d, (x, 660), "trust.", font(128), GOLD)
    wrap(d, (72, 860), "Flats straight from owners. Roommates who match your vibe. An AI that spots scams before you pay a rupee.",
         font(34, 500), SOFT, 44, 50)
    for i, t in enumerate(["Zero brokerage", "AI scam check", "Roommate match"]):
        pill(d, (72 + [0, 270, 520][i], 1060), t, (255, 255, 255, 30), WHITE)
    footer(d, True, "Swipe the grid to see how it works")
    return finish(img)


def p2_problem():
    img = light_canvas(); d = draw(img)
    header(d, False, 2)
    text(d, (70, 200), "Sound familiar?", font(30, 700), (109, 74, 255, 255))
    wrap(d, (70, 250), "The flat looked perfect. The rent was a steal.", font(62), LIGHT_INK, 26, 76)
    # fake chat
    shadow_card(img, (110, 470, 970, 1010), 36); d = draw(img)
    d.ellipse([150 * S, 510 * S, 214 * S, 574 * S], fill=(230, 226, 245, 255))
    text(d, (232, 516), "\"Owner\"", font(28), LIGHT_INK)
    text(d, (232, 552), "online", font(20, 500), GREEN)
    msgs = ["I'm an army officer, posted far away.", "Can't show the flat, I'll courier the keys.",
            "Pay ₹10,000 token on UPI today,", "many people are waiting!"]
    y = 620
    box(d, (150, 600, 860, 600 + 52 * len(msgs) + 40), 26, (241, 239, 248, 255))
    for m in msgs:
        text(d, (180, y), m, font(30, 600), LIGHT_INK); y += 52
    box(d, (540, 880, 950, 960), 20, None, RED, 5)
    d = draw(img)
    text(d, (588, 893), "CLASSIC SCAM", font(44), RED)
    wrap(d, (70, 1090), "Students moving to a new city lose their token money to fake listings every day. We built GharSure to stop that.",
         font(32, 500), LIGHT_MUTED, 50, 46)
    footer(d, False)
    return finish(img)


def p3_shield():
    img = dark_canvas(); d = draw(img)
    header(d, True, 3)
    text(d, (70, 190), "AI Scam Shield", font(30, 700), GOLD)
    wrap(d, (70, 236), "Every listing gets a risk score before you pay.", font(60), WHITE, 26, 74)
    glass(img, (70, 430, 1010, 1150), 40, 24, 70); d = draw(img)
    ring(d, 250, 640, 130, 92, (255, 99, 88, 255), (255, 255, 255, 40), 28)
    centered(d, 250, 590, "92", font(86), WHITE)
    centered(d, 250, 690, "/ 100", font(24, 600), SOFT)
    text(d, (440, 540), "High risk", font(52), (255, 120, 108, 255))
    text(d, (440, 606), "Likely a scam. Do not pay.", font(28, 600), SOFT)
    reasons = ["Photo found in 3 other listings, other cities", "Rent 65% below the area's fair price",
               "\"Pay token today\" pressure + army story", "Phone number reported by 2 people"]
    y = 830
    for r in reasons:
        d.ellipse([110 * S, (y + 8) * S, 130 * S, (y + 28) * S], fill=(255, 99, 88, 255))
        text(d, (150, y), r, font(30, 600), WHITE); y += 72
    footer(d, True)
    return finish(img)


def p4_photos_price():
    img = light_canvas(); d = draw(img)
    header(d, False, 4)
    text(d, (70, 190), "How the AI checks", font(30, 700), (109, 74, 255, 255))
    wrap(d, (70, 236), "Stolen photos and too-good prices, caught.", font(60), LIGHT_INK, 26, 74)
    # photo match
    photo(img, (70, 450, 500, 760), 0)
    photo(img, (580, 450, 1010, 760), 0, edited=True)
    d = draw(img)
    pill(d, (90, 470), "Real listing, Pune", (255, 255, 255, 235), LIGHT_INK, 20)
    pill(d, (600, 470), "Copied + cropped, Mumbai", (255, 255, 255, 235), LIGHT_INK, 20)
    box(d, (420, 570, 660, 640), 35, VIOLET)
    centered(d, 540, 584, "96% match", font(30), WHITE)
    # price bars
    shadow_card(img, (70, 820, 1010, 1160), 32); d = draw(img)
    text(d, (110, 852), "2BHK, Andheri, furnished", font(28), LIGHT_INK)
    text(d, (110, 916), "Asked", font(24, 700), LIGHT_MUTED)
    box(d, (260, 912, 360, 950), 19, RED); text(d, (380, 914), "₹9,000", font(28), RED)
    text(d, (110, 990), "Fair rent", font(24, 700), LIGHT_MUTED)
    box(d, (260, 986, 960, 1024), 19, GREEN); text(d, (110, 1060), "AI estimate: ₹75,000. 88% below = red flag", font(26, 600), LIGHT_MUTED)
    footer(d, False)
    return finish(img)


def p5_book():
    img = dark_canvas(); d = draw(img)
    header(d, True, 5)
    text(d, (70, 190), "Zero brokerage", font(30, 700), GOLD)
    wrap(d, (70, 236), "Book a visit like you book a hotel.", font(60), WHITE, 24, 74)
    shadow_card(img, (150, 430, 930, 1170), 40); d = draw(img)
    photo(img, (170, 450, 910, 840), 10, 30); d = draw(img)
    pill(d, (192, 472), "Verified safe", (255, 255, 255, 240), GREEN, 22)
    text(d, (196, 770), "₹31,000 / month", font(40), WHITE)
    text(d, (196, 870), "Furnished 1BHK, HSR Layout", font(34), LIGHT_INK)
    x = 196
    for t in ["1 BHK", "650 sq ft", "Furnished"]:
        x = pill(d, (x, 926), t, (244, 242, 251, 255), (74, 69, 102, 255), 20) + 10
    box(d, (196, 1030, 884, 1120), 22, VIOLET)
    centered(d, 540, 1056, "Request to book visit", font(34), WHITE)
    footer(d, True, "Owner's number unlocks when they accept")
    return finish(img)


def p6_roommate():
    img = light_canvas(); d = draw(img)
    header(d, False, 6)
    text(d, (70, 190), "Roommate match", font(30, 700), (109, 74, 255, 255))
    wrap(d, (70, 236), "Find someone who's actually like you.", font(60), LIGHT_INK, 24, 74)
    shadow_card(img, (70, 440, 1010, 1170), 40); d = draw(img)
    for cx, letter, col in [(330, "A", VIOLET), (750, "R", (26, 115, 232, 255))]:
        d.ellipse([(cx - 80) * S, 500 * S, (cx + 80) * S, 660 * S], fill=col)
        centered(d, cx, 540, letter, font(72), WHITE)
    ring(d, 540, 580, 70, 98, GREEN, LINE, 16)
    centered(d, 540, 556, "98%", font(40), GREEN)
    centered(d, 540, 690, "Aarav  +  Rohan", font(34), LIGHT_INK)
    tags = ["Both night owls", "Both non-smokers", "Same college", "Budgets overlap", "Same cleanliness", "Moving same month"]
    x, y = 110, 770
    for t in tags:
        f = font(24, 700)
        w = d.textlength(t, font=f) / S + 58
        if x + w > 970:
            x, y = 110, y + 70
        box(d, (x, y, x + w, y + 52), 26, (233, 249, 240, 255))
        d.ellipse([(x + 20) * S, (y + 20) * S, (x + 32) * S, (y + 32) * S], fill=(22, 163, 94, 255))
        text(d, (x + 42, y + 12), t, f, (11, 122, 68, 255))
        x += w + 12
    text(d, (110, 1060), "Number shared only when you BOTH say yes.", font(28, 700), LIGHT_MUTED)
    footer(d, False)
    return finish(img)


def p7_leaving():
    img = dark_canvas(); d = draw(img)
    header(d, True, 7)
    text(d, (70, 190), "Students helping students", font(30, 700), GOLD)
    wrap(d, (70, 236), "Leaving your flat? Need a flatmate?", font(60), WHITE, 22, 74)
    cards = [("Moving out", "Post your flat for the next tenant. Share the owner's number only if they agree.", "Free from 4 Dec", GOLD),
             ("Flatmate wanted", "Already living there? Post your spare room with the per-person rent.", "₹12,000 / person", (124, 92, 255, 255))]
    for i, (title, body, tag, col) in enumerate(cards):
        y0 = 470 + i * 340
        glass(img, (70, y0, 1010, y0 + 300), 36, 26, 70); d = draw(img)
        box(d, (110, y0 + 40, 190, y0 + 120), 22, col)
        centered(d, 150, y0 + 62, ["OUT", "2+"][i], font([26, 36][i]), INK if i == 0 else WHITE)
        text(d, (220, y0 + 42), title, font(42), WHITE)
        wrap(d, (220, y0 + 100), body, font(26, 500), SOFT, 50, 36)
        pill(d, (220, y0 + 220), tag, (255, 255, 255, 36), WHITE, 22)
    footer(d, True)
    return finish(img)


def p8_bills():
    img = light_canvas(); d = draw(img)
    header(d, False, 8)
    text(d, (70, 190), "After you move in", font(30, 700), (109, 74, 255, 255))
    wrap(d, (70, 236), "Rent, bills and deposit in one place.", font(60), LIGHT_INK, 24, 74)
    shadow_card(img, (70, 440, 1010, 1170), 40); d = draw(img)
    stats = [("₹34,000", "Deposit held"), ("₹18,540", "Due now"), ("₹17,000", "Paid")]
    for i, (v, l) in enumerate(stats):
        x0 = 110 + i * 300
        box(d, (x0, 480, x0 + 270, 610), 22, (247, 245, 255, 255), LINE, 2)
        text(d, (x0 + 22, 500), v, font(36), LIGHT_INK)
        text(d, (x0 + 22, 556), l, font(22, 600), LIGHT_MUTED)
    rows = [("Rent", "Nov", "₹17,000", "Pay", VIOLET, WHITE), ("Electricity", "Nov", "₹1,240", "Pay", VIOLET, WHITE),
            ("Water", "Nov", "₹300", "Paid", (233, 249, 240, 255), (11, 122, 68, 255))]
    y = 660
    for name, period, amt, status, bg, ink in rows:
        d.line([(110 * S, (y - 14) * S), (970 * S, (y - 14) * S)], fill=LINE, width=2 * S)
        text(d, (120, y + 10), name, font(32), LIGHT_INK)
        text(d, (430, y + 14), period, font(26, 600), LIGHT_MUTED)
        text(d, (560, y + 10), amt, font(32), LIGHT_INK)
        box(d, (820, y, 960, y + 62), 20, bg)
        centered(d, 890, y + 14, status, font(28), ink)
        y += 110
    text(d, (110, 1010), "Pay straight to your owner's UPI.", font(30, 700), LIGHT_INK)
    text(d, (110, 1058), "GharSure never holds your money.", font(28, 600), LIGHT_MUTED)
    footer(d, False)
    return finish(img)


def p9_cta(url: str):
    img = dark_canvas(); d = draw(img)
    header(d, True, 9)
    text(d, (70, 190), "It's free", font(30, 700), GOLD)
    wrap(d, (70, 236), "Find your flat or flatmate today.", font(64), WHITE, 22, 78)
    glass(img, (190, 450, 890, 1150), 44, 26, 80); d = draw(img)
    box(d, (290, 500, 790, 1000), 34, WHITE)
    qr = qrcode.QRCode(box_size=10, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    q = qr.make_image(fill_color=INK, back_color=WHITE).convert("RGBA").resize((440 * S, 440 * S), Image.Resampling.NEAREST)
    img.alpha_composite(q, (320 * S, 530 * S))
    d = draw(img)
    centered(d, 540, 1040, url.replace("https://", ""), font(32), GOLD)
    centered(d, 540, 1088, "Opens like an app. No download.", font(24, 600), SOFT)
    centered(d, 540, 1200, "Never pay before visiting.  Scammed? Call 1930", font(24, 600), SOFT)
    return finish(img)


CAPTIONS = [
    "Find a home you can trust. 🏡 GharSure is a free app for students and young professionals: flats straight from owners, roommates who match your vibe, and an AI that checks every listing before you pay a rupee.",
    "\"I'm an army officer, I'll courier the keys, just pay the token today.\" 😬 If you've heard this, you've met a rental scammer. Save this post and send it to a friend who's flat hunting.",
    "Our AI Scam Shield gives every listing a 0-100 risk score, with the exact reasons: reused photos, fake-cheap rent, pressure messages and reported numbers. 🛡️",
    "Scammers copy photos from real listings and crop or filter them. Our C++ image engine still catches them, and our AI compares the rent with the area's fair price. 🔍",
    "No brokers. 🙅 Browse vacant flats on a map, request a visit, and the owner's number unlocks only when they accept. Booking a flat should feel as easy as booking a hotel. 🗓️",
    "Night owl? Non-smoker? Veg? 🦉🥗 Tell GharSure your habits once and see a compatibility % with every roommate, plus the reasons behind it. Numbers are shared only when you both say yes.",
    "Students helping students. 🤝 Moving out? Post your flat for the next tenant. Have a spare room? Find a flatmate who pays their share.",
    "Rent, electricity, water and your deposit, all in one place. 🧾 Pay straight to your owner's UPI and keep a clean record. GharSure never holds your money.",
    "It's free. Scan the code or tap the link in bio to find your flat or flatmate today. 🏡✨ And remember: never pay before visiting. If you've been scammed, call 1930.",
]
HASHTAGS = "#GharSure #flathunting #pg #roommate #flatmate #studentlife #rentsafe #renting #nobroker #collegelife"


def main() -> None:
    global SITE
    url = (sys.argv[1] if len(sys.argv) > 1 else "https://gharsure.onrender.com").rstrip("/")
    SITE = url.replace("https://", "")
    DIR.mkdir(parents=True, exist_ok=True)
    posts = [p1_intro(), p2_problem(), p3_shield(), p4_photos_price(), p5_book(), p6_roommate(), p7_leaving(), p8_bills(),
             p9_cta(url)]
    for i, img in enumerate(posts, 1):
        img.save(DIR / f"{i:02d}.png", optimize=True)
    with open(DIR / "captions.txt", "w", encoding="utf-8") as f:
        f.write("Post in this order: 09 first, 01 last, so 01 appears top-left of your grid.\n\n")
        for i, cap in enumerate(CAPTIONS, 1):
            extra = f"\n🔗 {url}" if i in (1, 9) else "\n🔗 Link in bio"
            f.write(f"--- Post {i:02d} ---\n{cap}{extra}\n{HASHTAGS}\n\n")
    # 3x3 grid preview, as the profile shows it
    tw, th = 360, 450
    grid = Image.new("RGB", (tw * 3 + 8, th * 3 + 8), (255, 255, 255))
    for i, img in enumerate(posts):
        grid.paste(img.resize((tw, th), Image.Resampling.LANCZOS), ((i % 3) * (tw + 4), (i // 3) * (th + 4)))
    grid.save(DIR / "grid-preview.png")
    print(f"9 posts + captions -> {DIR}")


if __name__ == "__main__":
    main()
