import os
import sqlite3
import time

from screenshot_findr.db import Database
from screenshot_findr.digest import build_digest
from screenshot_findr.indexer import scan

from .conftest import make_screenshot


def test_digest_lists_forgotten_screenshots(tmp_path, db, fake_ocr):
    folder = tmp_path / "Screenshots"
    old = make_screenshot(folder / "old.png", "x")
    (folder / "old.txt").write_text("Order total ₹500 receipt")
    week_old = time.time() - 10 * 86400
    os.utime(old, (week_old, week_old))
    make_screenshot(folder / "new.png", "x")
    scan(db, [folder], "fake", fake_ocr)

    page, shown = build_digest(db)
    assert shown == 1
    assert "old.png" in page and "new.png" not in page
    assert "data:image/jpeg;base64," in page
    assert "receipt" in page  # tag badge
    assert "<b>1</b> screenshot this week" in page


def test_digest_when_nothing_forgotten(db):
    page, shown = build_digest(db)
    assert shown == 0 and "Nothing forgotten" in page


def test_old_database_is_upgraded_and_backfilled(tmp_path, fake_ocr):
    """A database from the first version (no tags/phash columns) keeps working."""
    folder = tmp_path / "Screenshots"
    make_screenshot(folder / "a.png", "x")
    (folder / "a.txt").write_text("Traceback ValueError: boom")
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE screenshots (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
          filename TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL, width INTEGER,
          height INTEGER, text TEXT NOT NULL DEFAULT '', ocr_backend TEXT NOT NULL DEFAULT 'none',
          indexed_at REAL NOT NULL, view_count INTEGER NOT NULL DEFAULT 0, last_viewed REAL);
    """)
    st = (folder / "a.png").stat()
    conn.execute("INSERT INTO screenshots (path, filename, size, mtime, width, height, text, "
                 "ocr_backend, indexed_at) VALUES (?, 'a.png', ?, ?, 900, 200, "
                 "'Traceback ValueError: boom', 'fake', 0)",
                 (str(folder / "a.png"), st.st_size, st.st_mtime))
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        calls = []
        res = scan(db, [folder], "fake", lambda p: calls.append(p) or "")
        assert res.unchanged == 1 and calls == []  # no re-OCR needed
        shot = db.get_by_path(str(folder / "a.png"))
        assert "error" in shot.tags
        assert db.hashes()  # perceptual hash filled in
    finally:
        db.close()
