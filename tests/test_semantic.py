import numpy as np

from screenshot_findr.indexer import scan
from screenshot_findr.semantic import rank, search_by_meaning, to_blob

from .conftest import make_screenshot

# Tiny stand-in for a real model: a few "concepts", each triggered by related words.
CONCEPTS = [
    {"shoes", "sneakers", "nike", "footwear", "trainers"},
    {"flight", "boarding", "airport", "travel", "trip"},
    {"pizza", "food", "dinner", "restaurant"},
]


class FakeEmbedder:
    name = "fake-model"

    def __init__(self):
        self.calls = 0

    def _vec(self, text):
        words = set(text.lower().split())
        v = np.array([len(words & c) for c in CONCEPTS] + [0.01], dtype=np.float32)
        return v / np.linalg.norm(v)

    def embed_documents(self, texts):
        self.calls += 1
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


def test_rank_orders_by_cosine():
    q = np.array([1, 0], dtype=np.float32)
    rows = [(1, to_blob(np.array([0, 1]))), (2, to_blob(np.array([1, 0]))),
            (3, to_blob(np.array([0.7, 0.7])))]
    assert [i for i, _ in rank(q, rows, 10, 0.5)] == [2, 3]


def test_meaning_search_finds_screenshots_without_the_words(tmp_path, db, fake_ocr):
    folder = tmp_path / "Screenshots"
    for name, text in [("a", "Nike Air Max sneakers add to cart"),
                       ("b", "Boarding pass gate B12"),
                       ("c", "")]:
        make_screenshot(folder / f"{name}.png", "x")
        (folder / f"{name}.txt").write_text(text)

    emb = FakeEmbedder()
    res = scan(db, [folder], "fake", fake_ocr, embedder=emb)
    assert res.embedded == 2  # the empty one is skipped

    assert db.search("shoes") == []  # no exact words...
    hits = search_by_meaning(db, emb, "shoes")  # ...but found by meaning
    assert [s.filename for s in hits] == ["a.png"]
    assert hits[0].match == "meaning"
    assert [s.filename for s in search_by_meaning(db, emb, "trip airport")] == ["b.png"]
    assert search_by_meaning(db, emb, "shoes", exclude=[hits[0].id]) == []

    # Already embedded -> not recomputed
    calls = emb.calls
    scan(db, [folder], "fake", fake_ocr, embedder=emb)
    assert emb.calls == calls

    # Text change -> embedding refreshed
    (folder / "a.txt").write_text("Pizza dinner order")
    import os
    os.utime(folder / "a.png", (5, 5))
    scan(db, [folder], "fake", fake_ocr, embedder=emb)
    assert search_by_meaning(db, emb, "shoes") == []
    assert [s.filename for s in search_by_meaning(db, emb, "food")] == ["a.png"]
