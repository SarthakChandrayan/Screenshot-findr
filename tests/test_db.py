import time

from screenshot_findr.db import build_fts_query


def add(db, path, text, mtime=None):
    db.upsert(path=path, filename=path.rsplit("/", 1)[-1], size=1, mtime=mtime or time.time(),
              width=10, height=10, text=text, ocr_backend="test")


def test_build_fts_query_is_safe():
    assert build_fts_query('flight "AND" OR (x*') == '"flight"* "AND"* "OR"* "x"*'
    assert build_fts_query("  !!! ") == ""


def test_search_matches_text_prefix_and_all_words(db):
    add(db, "/s/a.png", "Your flight confirmation to Berlin")
    add(db, "/s/b.png", "Invoice #4411 total 23.00 EUR")
    add(db, "/s/c.png", "flight delayed")

    assert {s.path for s in db.search("flight")} == {"/s/a.png", "/s/c.png"}
    assert [s.path for s in db.search("confirm berl")] == ["/s/a.png"]
    assert [s.path for s in db.search("invoice")] == ["/s/b.png"]
    assert db.search("nothing-here") == []


def test_search_snippet_highlights(db):
    add(db, "/s/a.png", "error: connection refused on port 5432")
    (hit,) = db.search("refused")
    assert "[[refused]]" in hit.snippet


def test_search_matches_filename(db):
    add(db, "/s/receipt-amazon.png", "")
    assert [s.path for s in db.search("amazon")] == ["/s/receipt-amazon.png"]


def test_update_and_delete_keep_fts_in_sync(db):
    add(db, "/s/a.png", "old words")
    add(db, "/s/a.png", "new words")
    assert db.search("old") == []
    assert len(db.search("new")) == 1
    db.remove_paths(["/s/a.png"])
    assert db.search("new") == []
    assert db.count() == 0


def test_forgotten_excludes_recent_and_viewed(db):
    old = time.time() - 30 * 86400
    add(db, "/s/old.png", "a", mtime=old)
    add(db, "/s/old-viewed.png", "b", mtime=old)
    add(db, "/s/new.png", "c")
    viewed = next(s for s in db.recent() if s.path == "/s/old-viewed.png")
    db.mark_viewed(viewed.id)
    assert [s.path for s in db.forgotten()] == ["/s/old.png"]


def test_recent_orders_newest_first(db):
    add(db, "/s/1.png", "", mtime=100)
    add(db, "/s/2.png", "", mtime=200)
    assert [s.path for s in db.recent()] == ["/s/2.png", "/s/1.png"]
