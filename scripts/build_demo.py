"""Build the data for the website demo.

Renders a set of fictional screenshots, runs them through the real pipeline
(OCR, tags, titles, duplicate detection) and writes everything the static demo
needs into site/demo/:

    site/demo/data.json      index: text, tags, sizes, ages, duplicate groups, tag rules
    site/demo/img/<id>.jpg   full-size images
    site/demo/thumb/<id>.jpg thumbnails

Usage:  python scripts/build_demo.py   (needs an OCR engine: Windows OCR or Tesseract)
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from screenshot_findr import dupes, tags  # noqa: E402
from screenshot_findr.db import Screenshot  # noqa: E402
from screenshot_findr.ocr import get_ocr  # noqa: E402
from screenshot_findr.web import _title  # noqa: E402

OUT = ROOT / "site" / "demo"

# (kind, app name, accent colour, lines, age in days). All names and brands are fictional.
SHOTS = [
    ("phone", "Messages", "#2f7d4f", ["Riya", "are we still on for dinner tonight?", "yes! 8:30 at the usual place", "bring the board game", "last seen today at 10:45"], 0.1),
    ("desk", "Trailhead Store", "#1f6feb", ["Trailrunner 270 sneakers", "Size 9 - Midnight Blue", "In stock - 40% off", "Add to Cart    Buy Now", "Free delivery by Friday"], 2),
    ("desk", "Terminal", "#30363d", ["$ python app.py", "Traceback (most recent call last):", '  File "app.py", line 42, in load', "ValueError: invalid literal for int()"], 1),
    ("phone", "SkyJet Airlines", "#c2410c", ["Boarding Pass", "Flight SJ 2041", "DEL to BLR", "Gate B12   Seat 14C", "Departure 06:40", "Boarding closes 06:20"], 4),
    ("desk", "Editor - main.py", "#3b3b4f", ["def find_screenshots(folder):", "    for name in os.listdir(folder):", "        if name.endswith('.png'):", "            yield name", "    return None"], 9),
    ("phone", "Foodie", "#b91c1c", ["Order Summary", "Margherita pizza x2", "Garlic bread x1", "Subtotal 598", "GST 30", "Grand Total Rs 628", "Paid via UPI"], 12),
    ("desk", "Wi-Fi settings", "#4b5563", ["Network: HomeNet-5G", "Wi-Fi password: maple-river-42", "Security: WPA2 Personal", "Connected devices: 7"], 40),
    ("phone", "Recipes", "#a16207", ["Lemon Garlic Pasta", "Ingredients", "200 g spaghetti", "2 tbsp olive oil", "3 cloves garlic", "Cook time 15 minutes"], 33),
    ("desk", "Calendar", "#7c3aed", ["Design review meeting", "Thursday 4:00 pm - 5:00 pm", "Join video call", "meet.example.com/abc-defg", "Agenda: onboarding flow"], 3),
    ("desk", "Notes", "#0f766e", ["Quarterly goals", "1. Ship screenshot search", "2. Improve onboarding", "3. Hire two engineers", "4. Cut page load time in half"], 70),
    ("phone", "Bank", "#1d4ed8", ["Payment successful", "Transaction ID 88291022", "Amount paid INR 12,499", "To: City Electricity Board", "Debited from XX4821"], 20),
    ("phone", "Maps", "#15803d", ["Blue Door Coffee", "4.6 stars - 1.2 km", "Open until 11 pm", "Cafe - Indiranagar", "Directions    Call"], 0.3),
    ("desk", "Browser", "#374151", ["https://github.com/SarthakChandrayan/Screenshot-findr", "Find any screenshot in seconds", "Python  MIT licence", "Star   Fork   Watch"], 95),
    ("phone", "Notes", "#0f766e", ["Gift ideas for Mom", "- noise cancelling headphones", "- e-reader", "- coffee grinder", "- photo book"], 1),
    ("desk", "Browser", "#374151", ["404 Not Found", "The page you are looking for", "could not be found.", "Go back home"], 6),
    ("phone", "RailGo", "#9333ea", ["Train ticket confirmed", "PNR 4521873390", "12627 Karnataka Express", "Coach B2   Berth 34", "Platform 5 - 21:15"], 48),
    ("phone", "Messages", "#2f7d4f", ["Your verification code is 482913", "Do not share this OTP with anyone", "Valid for 10 minutes"], 0.2),
    ("desk", "Contacts", "#be185d", ["Dr. Mehta Clinic", "Phone +91 98765 43210", "Email clinic@example.com", "Address: 12 MG Road, Pune"], 130),
    ("phone", "StayWell Hotels", "#0369a1", ["Reservation confirmed", "Booking ID SW-55102", "Check-in Fri 2 pm", "Deluxe room, 2 nights", "Total paid 9,400"], 55),
    ("desk", "Slides", "#b45309", ["Big-O cheat sheet", "Array access O(1)", "Binary search O(log n)", "Merge sort O(n log n)", "Bubble sort O(n^2)"], 160),
    ("phone", "Music", "#db2777", ["Now playing", "Late Night Drive", "Lo-fi Collective", "Playlist: Focus Mode", "2:14 / 3:58"], 2),
    ("desk", "Docs", "#0f766e", ["Meeting notes - Sprint 14", "Decided to move the launch to May", "Owner: Arjun", "Follow up with design on icons"], 26),
    ("phone", "Weather", "#0284c7", ["Bengaluru", "24 C Partly cloudy", "High 28  Low 19", "Rain expected after 5 pm"], 7),
    ("desk", "Mail", "#4f46e5", ["Invoice INV-2207 from Pixel Studio", "Amount due: USD 450.00", "Due date: 30 June", "Pay online or reply to this email"], 85),
    ("phone", "Shop", "#1f6feb", ["Wishlist", "Mechanical keyboard - 75%", "Price 6,999  MRP 8,999", "Ratings 4.5 (2,310 reviews)", "Add to Cart"], 18),
    ("desk", "Terminal", "#30363d", ["$ npm run build", "error TS2322: Type 'string' is not", "assignable to type 'number'.", "Build failed in 3.2s"], 14),
    ("phone", "Fitness", "#16a34a", ["Morning run", "5.2 km   28:41", "Avg pace 5:31 /km", "Calories 341"], 5),
    ("desk", "Spreadsheet", "#15803d", ["Monthly budget", "Rent 18,000", "Groceries 6,500", "Transport 2,200", "Savings 10,000"], 62),
]
DUPLICATE_OF = {3: 1, 10: 1}  # index -> number of extra copies


def font(size: int, bold: bool = False):
    for name in (("DejaVuSans-Bold.ttf", "arialbd.ttf") if bold else ("DejaVuSans.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(kind: str, app: str, accent: str, lines: list[str], dark: bool) -> Image.Image:
    bg, fg, card = ((24, 24, 27), (236, 236, 240), (39, 39, 45)) if dark else ((250, 250, 250), (24, 24, 27), (238, 238, 242))
    if kind == "phone":
        w, h, s = 1080, 2340, 1.0
    else:
        w, h = random.choice([(1920, 1080), (1600, 1000), (1440, 900)])
        s = w / 1600
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 0
    if kind == "phone":  # status bar
        d.text((int(60 * s), int(40 * s)), "9:41", fill=fg, font=font(int(40 * s), True))
        d.text((w - int(200 * s), int(40 * s)), "5G 82%", fill=fg, font=font(int(36 * s)))
        y = int(130 * s)
    else:  # window title bar
        d.rectangle((0, 0, w, int(56 * s)), fill=card)
        for i, c in enumerate(("#ef4444", "#f59e0b", "#22c55e")):
            d.ellipse((int((24 + i * 34) * s), int(18 * s), int((44 + i * 34) * s), int(38 * s)), fill=c)
        y = int(56 * s)
    d.rectangle((0, y, w, y + int(130 * s)), fill=accent)
    d.text((int(48 * s), y + int(38 * s)), app, fill="white", font=font(int(52 * s), True))
    y += int(200 * s)
    body = font(int(46 * s))
    for line in lines:
        for part in textwrap.wrap(line, 40 if kind == "phone" else 60) or [""]:
            d.rounded_rectangle((int(36 * s), y - int(20 * s), w - int(36 * s), y + int(78 * s)), radius=int(18 * s), fill=card)
            d.text((int(64 * s), y), part, fill=fg, font=body)
            y += int(118 * s)
    return img


def main() -> int:
    backend, ocr = get_ocr()
    if ocr is None:
        print("No OCR engine available (need Windows OCR or Tesseract).")
        return 1
    print(f"OCR engine: {backend}")
    random.seed(11)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "img").mkdir(parents=True)
    (OUT / "thumb").mkdir()

    items, hashes = [], []
    with tempfile.TemporaryDirectory() as tmp:
        sources = []
        for i, (kind, app, accent, lines, age) in enumerate(SHOTS):
            img = render(kind, app, accent, lines, dark=random.random() < 0.4)
            sources.append((img, age))
            for k in range(DUPLICATE_OF.get(i, 0)):
                sources.append((img.copy(), age - 0.01 * (k + 1)))
        for n, (img, age) in enumerate(sources, start=1):
            path = Path(tmp) / f"{n}.png"
            img.save(path)
            text = ocr(str(path)).strip()
            w, h = img.size
            stamp = f"Screenshot {n:03d}.png"
            shot = Screenshot(id=n, path=str(path), filename=stamp, size=0, mtime=0, width=w,
                              height=h, text=text, view_count=0, last_viewed=None)
            full = img.copy()
            full.thumbnail((1600, 1600))
            full.save(OUT / "img" / f"{n}.jpg", quality=82, optimize=True)
            thumb = img.copy()
            thumb.thumbnail((560, 560))
            thumb.save(OUT / "thumb" / f"{n}.jpg", quality=80, optimize=True)
            hashes.append((n, dupes.dhash(str(path)), text))
            items.append({
                "id": n, "filename": stamp, "title": _title(shot), "text": text,
                "tags": tags.classify(text, stamp, w, h), "width": w, "height": h,
                "age_days": round(age, 3),
            })
            print(f"  {n:3d}  {items[-1]['title'][:50]:<50} {', '.join(items[-1]['tags'])}")

    texts = {i: t for i, _, t in hashes}
    groups = dupes.group([(i, h) for i, h, _ in hashes if h],
                         same=lambda a, b: dupes.similar_text(texts[a], texts[b]))
    rules = [
        {"tag": tag, "threshold": tags.THRESHOLDS.get(tag, tags.THRESHOLD),
         "rules": [[r[0], r[1], r[2] if len(r) > 2 else 3] for r in spec]}
        for tag, (_, spec) in tags.RULES.items()
    ]
    data = {"items": items, "duplicates": sorted(sorted(g) for g in groups), "tag_rules": rules,
            "ocr_backend": backend}
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(items)} screenshots, {len(groups)} duplicate groups to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
