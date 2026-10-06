import pytest

from screenshot_findr.tags import classify, decode, encode


@pytest.mark.parametrize("text,expected", [
    ("Order Summary\nSubtotal ₹1,299\nGST 18%\nGrand Total ₹1,533", "receipt"),
    ("Boarding Pass  Flight AI 302  Gate B12  Seat 14C  Departure 06:40", "travel"),
    ("def main():\n    print('hi')\n    return 0", "code"),
    ("Traceback (most recent call last):\n  File x.py\nValueError: bad value", "error"),
    ("TypeError: undefined is not a function", "error"),
    ("Ingredients: 2 cups of flour, 1 tsp salt. Preheat oven to 180C", "recipe"),
    ("Add to Cart  Buy Now  In stock  40% off  Free delivery", "shopping"),
    ("WiFi password: hunter22  SSID: HomeNet", "password"),
    ("Visit https://example.com/docs for details", "link"),
    ("Riya: are we still on?\nMe: yes! 10:42 pm\nlast seen today at 10:45", "chat"),
])
def test_classify_finds_expected_tag(text, expected):
    assert expected in classify(text)


def test_plain_text_gets_no_tags():
    assert classify("The quick brown fox jumps over the lazy dog") == []


def test_tall_images_are_phone_screenshots():
    assert "phone" in classify("", width=1080, height=2400)
    assert "phone" not in classify("", width=1920, height=1080)


def test_encode_decode_roundtrip():
    assert decode(encode(["a", "b"])) == ["a", "b"]
    assert encode([]) == "" and decode("") == [] and decode(None) == []
