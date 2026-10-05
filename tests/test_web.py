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
