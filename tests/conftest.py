from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from screenshot_findr.db import Database


def make_screenshot(path: Path, text: str) -> Path:
    img = Image.new("RGB", (900, 200), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 70), text, fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "index.sqlite3")
    yield database
    database.close()


@pytest.fixture
def fake_ocr():
    """OCR stand-in: reads the text from a sidecar .txt file next to the image."""
    def run(path: str) -> str:
        sidecar = Path(path).with_suffix(".txt")
        return sidecar.read_text() if sidecar.exists() else ""
    return run
