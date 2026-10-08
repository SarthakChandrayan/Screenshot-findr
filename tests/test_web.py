import pytest

from screenshot_findr.indexer import BackgroundIndexer, scan
from screenshot_findr.web import create_app

from .conftest import make_screenshot

AJAX = {"X-Requested-With": "screenshot-findr"}


@pytest.fixture
def client(tmp_path, db, fake_ocr):
    folder = tmp_path / "Screenshots"
    make_screenshot(folder / "a.png", "x")
    (folder / "a.txt").write_text("pizza order receipt")
    scan(db, [folder], "fake", fake_ocr)
    indexer = BackgroundIndexer(db, [folder], "fake", fake_ocr)
    app = create_app(db, indexer, tmp_path / "thumbs", "fake")
    return app.test_client()


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Screenshot Findr" in r.data


def test_search_api(client):
    data = client.get("/api/search?q=pizza").get_json()
    assert [r["filename"] for r in data["results"]] == ["a.png"]
    assert "[[pizza]]" in data["results"][0]["snippet"]
    assert client.get("/api/search?q=sushi").get_json()["results"] == []
    assert len(client.get("/api/search").get_json()["results"]) == 1


def test_thumb_image_and_text(client):
    sid = client.get("/api/search").get_json()["results"][0]["id"]
    r = client.get(f"/thumb/{sid}")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    assert client.get(f"/image/{sid}").status_code == 200
    assert client.get(f"/api/text/{sid}").get_json()["text"] == "pizza order receipt"
    assert client.get("/image/9999").status_code == 404
    # opening the image counts as a view
    assert client.get("/api/search").get_json()["results"][0]["views"] == 1


def test_actions_require_custom_header(client):
    sid = client.get("/api/search").get_json()["results"][0]["id"]
    assert client.post(f"/api/open/{sid}").status_code == 403
    assert client.post("/api/rescan").status_code == 403
    assert client.post("/api/rescan", headers=AJAX).status_code == 200


def test_status(client):
    st = client.get("/api/status").get_json()
    assert st["count"] == 1 and st["ocr_backend"] == "fake"


def test_tags_api_and_filter(client):
    tags = client.get("/api/tags").get_json()["tags"]
    assert any(t["tag"] == "receipt" for t in tags)
    assert len(client.get("/api/search?tag=receipt").get_json()["results"]) == 1
    assert client.get("/api/search?tag=code").get_json()["results"] == []
    assert len(client.get("/api/search?q=pizza&tag=receipt").get_json()["results"]) == 1


def test_duplicates_and_delete(tmp_path, db, fake_ocr, monkeypatch):
    import shutil

    from screenshot_findr import web

    folder = tmp_path / "Shots"
    a = make_screenshot(folder / "a.png", "Your order has shipped")
    shutil.copy(a, folder / "a-copy.png")
    make_screenshot(folder / "b.png", "Totally different picture here")
    scan(db, [folder], "fake", fake_ocr)
    trashed = []
    monkeypatch.setattr(web, "send2trash", lambda p: trashed.append(p))
    app = web.create_app(db, BackgroundIndexer(db, [folder], "fake", fake_ocr), tmp_path / "t", "fake")
    c = app.test_client()

    data = c.get("/api/duplicates").get_json()
    assert data["extra"] == 1
    (group,) = data["groups"]
    assert {s["filename"] for s in group} == {"a.png", "a-copy.png"}

    assert c.post("/api/delete", json={"ids": [group[1]["id"]]}).status_code == 403
    r = c.post("/api/delete", json={"ids": [group[1]["id"]]}, headers=AJAX).get_json()
    assert r["deleted"] == [group[1]["id"]] and len(trashed) == 1
    assert c.get("/api/duplicates").get_json()["groups"] == []


def test_stats_and_forgotten_limit(client):
    st = client.get("/api/stats").get_json()
    assert st == {"total": 1, "this_week": 1, "forgotten": 0, "duplicates": 0}
    assert client.get("/api/forgotten?limit=3").status_code == 200
