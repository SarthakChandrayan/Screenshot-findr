from PIL import Image, ImageDraw

from screenshot_findr.dupes import dhash, distance, group, similar_text

from .conftest import make_screenshot


def test_dhash_matches_resaved_and_resized_copies(tmp_path):
    a = make_screenshot(tmp_path / "a.png", "Meeting notes for Monday")
    with Image.open(a) as img:
        img.resize((450, 100)).save(tmp_path / "small.jpg", quality=70)
    other = make_screenshot(tmp_path / "other.png", "x")
    with Image.open(other) as img:
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 450, 200), fill="navy")
        img.save(other)

    ha, hs, ho = dhash(str(a)), dhash(str(tmp_path / "small.jpg")), dhash(str(other))
    assert distance(ha, hs) <= 10
    assert distance(ha, ho) > 10


def test_dhash_unreadable_returns_none(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"nope")
    assert dhash(str(bad)) is None


def test_group_with_veto():
    h = "f" * 64
    near = "e" + "f" * 63  # 1 bit different
    far = "0" * 64
    assert group([(1, h), (2, near), (3, far)]) == [[1, 2]]
    assert group([(1, h), (2, near)], same=lambda a, b: False) == []


def test_similar_text():
    assert similar_text("Your order 123 has shipped", "your order 123 has shipped!")
    assert not similar_text("Your order 123 has shipped", "Meeting at 4pm with Riya")
    assert similar_text("", "")
    assert not similar_text("", "something")
