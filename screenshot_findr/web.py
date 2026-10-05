"""Local web UI: search box, results grid, and a 'forgotten screenshots' shelf."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image

from .db import Database, Screenshot
from .indexer import BackgroundIndexer

THUMB_SIZE = (480, 480)


def _serialize(s: Screenshot) -> dict:
    return {
        "id": s.id,
        "filename": s.filename,
        "folder": os.path.dirname(s.path),
        "taken": datetime.fromtimestamp(s.mtime).strftime("%d %b %Y, %H:%M"),
        "mtime": s.mtime,
        "width": s.width,
        "height": s.height,
        "snippet": s.snippet or s.text[:200],
        "has_text": bool(s.text),
        "views": s.view_count,
    }


def create_app(db: Database, indexer: BackgroundIndexer, thumbs_dir: Path, ocr_backend: str) -> Flask:
    app = Flask(__name__)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    def get_or_404(screenshot_id: int) -> Screenshot:
        shot = db.get(screenshot_id)
        if shot is None or not os.path.exists(shot.path):
            abort(404)
        return shot

    def require_local_ajax() -> None:
        # Custom header => browsers block cross-site requests (no CORS), so other
        # websites can't make this app open files on your machine.
        if request.headers.get("X-Requested-With") != "screenshot-findr":
            abort(403)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            folders=[str(f) for f in indexer.folders],
            ocr_backend=ocr_backend,
        )

    @app.get("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        offset = max(int(request.args.get("offset", 0) or 0), 0)
        results = db.search(q, limit=60, offset=offset) if q else db.recent(limit=60, offset=offset)
        return jsonify({"query": q, "results": [_serialize(s) for s in results]})

    @app.get("/api/forgotten")
    def api_forgotten():
        return jsonify({"results": [_serialize(s) for s in db.forgotten(limit=8)]})

    @app.get("/api/status")
    def api_status():
        return jsonify({**indexer.status, "count": db.count(), "ocr_backend": ocr_backend})

    @app.post("/api/rescan")
    def api_rescan():
        require_local_ajax()
        indexer.trigger()
        return jsonify({"ok": True})

    @app.get("/thumb/<int:screenshot_id>")
    def thumb(screenshot_id: int):
        shot = get_or_404(screenshot_id)
        target = thumbs_dir / f"{shot.id}-{int(shot.mtime)}.jpg"
        if not target.exists():
            try:
                with Image.open(shot.path) as img:
                    img.thumbnail(THUMB_SIZE)
                    img.convert("RGB").save(target, "JPEG", quality=82)
            except Exception:
                return send_file(shot.path)
        return send_file(target, max_age=86400)

    @app.get("/image/<int:screenshot_id>")
    def image(screenshot_id: int):
        shot = get_or_404(screenshot_id)
        db.mark_viewed(shot.id)
        return send_file(shot.path)

    @app.get("/api/text/<int:screenshot_id>")
    def text(screenshot_id: int):
        shot = get_or_404(screenshot_id)
        return jsonify({"text": shot.text, "path": shot.path})

    @app.post("/api/open/<int:screenshot_id>")
    def open_file(screenshot_id: int):
        require_local_ajax()
        shot = get_or_404(screenshot_id)
        db.mark_viewed(shot.id)
        if sys.platform == "win32":
            os.startfile(shot.path)  # opens in Photos / the default viewer
        elif sys.platform == "darwin":
            subprocess.Popen(["open", shot.path])
        else:
            subprocess.Popen(["xdg-open", shot.path])
        return jsonify({"ok": True})

    @app.post("/api/reveal/<int:screenshot_id>")
    def reveal(screenshot_id: int):
        require_local_ajax()
        shot = get_or_404(screenshot_id)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(shot.path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", shot.path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(shot.path)])
        return jsonify({"ok": True})

    return app
