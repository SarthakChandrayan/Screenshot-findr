import os

import pytest

from screenshot_findr.indexer import scan
from screenshot_findr.ocr import get_ocr

from .conftest import make_screenshot


def test_scan_adds_updates_and_removes(tmp_path, db, fake_ocr):
    folder = tmp_path / "Screenshots"
    a = make_screenshot(folder / "a.png", "x")
    (folder / "a.txt").write_text("hello world")
    make_screenshot(folder / "sub" / "b.jpg", "x")
    (folder / "notes.docx").write_text("not an image")

    res = scan(db, [folder], "fake", fake_ocr)
    assert (res.added, res.updated, res.removed) == (2, 0, 0)
    assert [s.filename for s in db.search("hello")] == ["a.png"]
    s = db.search("hello")[0]
    assert (s.width, s.height) == (900, 200)

    # Nothing changed -> nothing re-read
    res = scan(db, [folder], "fake", fake_ocr)
    assert (res.added, res.updated, res.unchanged) == (0, 0, 2)

    # Changed file is re-read
    (folder / "a.txt").write_text("goodbye")
    make_screenshot(a, "different")
    os.utime(a, (1, 1))
    res = scan(db, [folder], "fake", fake_ocr)
    assert res.updated == 1
    assert db.search("hello") == [] and len(db.search("goodbye")) == 1

    # Deleted file is dropped
    a.unlink()
    res = scan(db, [folder], "fake", fake_ocr)
    assert res.removed == 1 and db.count() == 1


def test_scan_without_ocr_then_with_ocr_retries(tmp_path, db, fake_ocr):
    folder = tmp_path / "Screenshots"
    make_screenshot(folder / "a.png", "x")
    (folder / "a.txt").write_text("late text")
    scan(db, [folder], "none", None)
    assert db.search("late") == []
    res = scan(db, [folder], "fake", fake_ocr)
    assert res.updated == 1 and len(db.search("late")) == 1


def test_scan_survives_broken_images(tmp_path, db):
    folder = tmp_path / "Screenshots"
    (folder).mkdir()
    (folder / "broken.png").write_bytes(b"not really a png")

    def boom(path):
        raise RuntimeError("bad image")

    res = scan(db, [folder], "fake", boom)
    assert res.added == 1 and len(res.failed) == 1


def test_scan_does_not_forget_files_from_other_folders(tmp_path, db, fake_ocr):
    one, two = tmp_path / "one", tmp_path / "two"
    make_screenshot(one / "a.png", "x")
    make_screenshot(two / "b.png", "x")
    scan(db, [one, two], "fake", fake_ocr)
    scan(db, [one], "fake", fake_ocr)
    assert db.count() == 2


def test_real_ocr_end_to_end(tmp_path, db):
    backend, ocr = get_ocr("auto")
    if ocr is None:
        pytest.skip("no OCR engine installed")
    folder = tmp_path / "Screenshots"
    make_screenshot(folder / "Screenshot 2026-10-05 101010.png", "Flight booking reference QX7")
    scan(db, [folder], backend, ocr)
    assert [s.filename for s in db.search("booking")] == ["Screenshot 2026-10-05 101010.png"]
