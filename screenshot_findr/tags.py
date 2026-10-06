"""Guess what a screenshot is about from its text, so it can be filtered by tag.

Simple keyword/pattern rules: fast, private, and good enough for most screenshots.
Each tag needs a minimum score, so one stray word doesn't tag an image.
"""

from __future__ import annotations

import re
from typing import Optional

# tag -> (emoji, list of (regex, weight)); a tag is applied when the total weight >= its threshold
RULES: dict[str, tuple[str, list[tuple[str, int]]]] = {
    "receipt": ("🧾", [
        (r"\b(receipt|invoice|order (?:total|summary|confirm\w*)|subtotal|grand total|amount paid|"
         r"payment (?:successful|received|confirm\w*)|transaction id|txn id|gst|vat|tax invoice)\b", 2),
        (r"\b(total|paid|payment|order|qty|quantity|price|refund|upi|debited|credited)\b", 1),
        (r"(₹|\$|€|£|\bINR\b|\bUSD\b|\bEUR\b|\bRs\.?)\s?\d", 1),
    ]),
    "travel": ("✈️", [
        (r"\b(boarding pass|flight|pnr|e-?ticket|itinerary|check-?in|departure|arrival|gate \w+|"
         r"seat \d+\w?|booking (?:reference|id|confirm\w*)|train|platform \d+|hotel|reservation)\b", 2),
        (r"\b(terminal|airport|airlines?|passenger|journey|trip|coach|berth)\b", 1),
    ]),
    "code": ("💻", [
        (r"(\bdef \w+\(|\bfunction\s*\w*\(|=>|\bconst \w+ =|\bimport \w+|#include|\bpublic static\b|"
         r"\bclass \w+[:({]|\breturn\b.*;|console\.log|print\(|</?\w+>|\{\s*$)", 2),
        (r"\b(npm|pip|git|sudo|docker|python|javascript|java|sql|select \* from)\b", 1),
        (r"[{}();]{3,}", 1),
    ]),
    "error": ("⚠️", [
        (r"\b(traceback|exception|stack ?trace|segmentation fault|fatal error|"
         r"error code|errno|failed to|could not|cannot find|not found|404|500 internal)\b", 2),
        (r"\b\w+(?:Error|Exception):", 2),
        (r"\b(error|failed|failure|warning|crash\w*)\b", 1),
    ]),
    "chat": ("💬", [
        (r"\b(whatsapp|telegram|messenger|imessage|typing…|typing\.\.\.|online|last seen|"
         r"delivered|seen \d|reply|forwarded)\b", 2),
        (r"\b\d{1,2}:\d{2}\s?(?:am|pm)?\b", 1),
        (r"\b(lol|haha|ok+|thanks|thx|bro|hey|hi)\b", 1),
    ]),
    "shopping": ("🛍️", [
        (r"\b(add to (?:cart|bag|basket)|buy now|in stock|out of stock|free delivery|"
         r"wishlist|size guide|deal of the day|\d+% off|mrp)\b", 2),
        (r"\b(amazon|flipkart|myntra|ebay|etsy|price|ratings?|reviews?|delivery|sold by)\b", 1),
    ]),
    "recipe": ("🍳", [
        (r"\b(ingredients|instructions|preheat|tablespoons?|teaspoons?|tbsp|tsp|"
         r"cups? of|bake|simmer|prep time|cook time|servings)\b", 2),
        (r"\b(recipe|minutes|grams?|salt|sugar|flour|oil|garlic|onion)\b", 1),
    ]),
    "contact": ("📇", [
        (r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", 2),
        (r"(\+\d{1,3}[\s-]?)?\(?\d{3,5}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}\b", 1),
        (r"\b(phone|mobile|email|address|contact)\b", 1),
    ]),
    "link": ("🔗", [
        (r"\bhttps?://\S+|\bwww\.\S+\.\w{2,}", 2),
    ]),
    "meeting": ("📅", [
        (r"\b(meeting|zoom|google meet|teams|calendar|agenda|invite|rsvp|"
         r"join (?:the )?call|reschedul\w*)\b", 2),
        (r"\b(mon|tue|wed|thu|fri|sat|sun)\w*\b", 1),
        (r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", 1),
    ]),
    "password": ("🔑", [
        (r"\b(password|passcode|wi-?fi|ssid|otp|one[- ]time password|verification code|"
         r"recovery code|backup code|api key|secret)\b", 2),
    ]),
}

EMOJI = {tag: emoji for tag, (emoji, _) in RULES.items()}
EMOJI["phone"] = "📱"
_COMPILED = {
    tag: [(re.compile(rx, re.IGNORECASE | re.MULTILINE), w) for rx, w in rules]
    for tag, (_, rules) in RULES.items()
}
THRESHOLD = 2
# Tags whose weak signals (times, "thanks") show up everywhere need more evidence.
THRESHOLDS = {"chat": 3}


def classify(text: str, filename: str = "", width: Optional[int] = None,
             height: Optional[int] = None) -> list[str]:
    """Return the tags that fit this screenshot, best match first."""
    haystack = f"{filename}\n{text}"
    scores: dict[str, int] = {}
    for tag, rules in _COMPILED.items():
        score = 0
        for rx, weight in rules:
            hits = len(rx.findall(haystack))
            score += weight * min(hits, 3)  # cap so one repeated word can't dominate
        if score >= THRESHOLDS.get(tag, THRESHOLD):
            scores[tag] = score
    # Tall, narrow images are almost always phone screenshots.
    if width and height and height > width * 1.6:
        scores.setdefault("phone", THRESHOLD)
    return sorted(scores, key=lambda t: -scores[t])



def encode(tags: list[str]) -> str:
    """Stored as ',a,b,' so a tag can be matched with LIKE '%,a,%'."""
    return f",{','.join(tags)}," if tags else ""


def decode(stored: Optional[str]) -> list[str]:
    return [t for t in (stored or "").split(",") if t]
