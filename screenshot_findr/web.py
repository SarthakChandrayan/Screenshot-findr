"""Local web UI: search box, results grid, and a 'forgotten screenshots' shelf."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image

from send2trash import send2trash

from . import dupes
from .db import Database, Screenshot
from .indexer import BackgroundIndexer
from .semantic import Embedder, search_by_meaning
from .tags import EMOJI

THUMB_SIZE = (720, 720)  # sharp on high-DPI screens at the largest card size


def _title(s: Screenshot) -> str:
    """A human caption: the first line of text that reads like words, else the file name."""
    for line in s.text.splitlines()[:12]:
        line = " ".join(line.split())
        if len(re.findall(r"[^\W\d_]{2,}", line)) >= 2 and sum(c.isalpha() for c in line) >= 8:
            return line[:90]
    return os.path.splitext(s.filename)[0]


def _serialize(s: Screenshot) -> dict:
    return {
        "id": s.id,
        "title": _title(s),
        "filename": s.filename,
        "folder": os.path.dirname(s.path),
        "taken": datetime.fromtimestamp(s.mtime).strftime("%d %b %Y, %H:%M"),
        "mtime": s.mtime,
        "width": s.width,
        "height": s.height,
        "snippet": s.snippet or s.text[:200],
        "has_text": bool(s.text),
        "views": s.view_count,
        "tags": s.tags,
        "match": s.match,
    }


def find_duplicate_groups(db: Database) -> list[list[Screenshot]]:
    """Groups of look-alike screenshots; the first one in each group is the one to keep
    (largest image, then the oldest, i.e. the original rather than a copy)."""
    rows = db.hashes()
    texts = {sid: text for sid, _, text in rows}
    groups = dupes.group([(sid, h) for sid, h, _ in rows],
                         same=lambda a, b: dupes.similar_text(texts[a], texts[b]))
    result = []
    for ids in groups:
        shots = db.get_many(ids)
        shots.sort(key=lambda s: (-(s.width or 0) * (s.height or 0), s.mtime))
        result.append(shots)
    result.sort(key=lambda g: (-len(g), -g[0].mtime))
    return result


def create_app(db: Database, indexer: BackgroundIndexer, thumbs_dir: Path, ocr_backend: str,
               embedder: Optional[Embedder] = None) -> Flask:
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
            tag_emoji=EMOJI,
        )

    @app.get("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        tag = request.args.get("tag") or None
        offset = max(int(request.args.get("offset", 0) or 0), 0)
        results = db.search(q, limit=60, offset=offset, tag=tag)
        has_more = len(results) == 60
        if q and embedder is not None and offset == 0:
            # Words first, then screenshots that are about the same thing.
            results += search_by_meaning(db, embedder, q, tag=tag, exclude=[s.id for s in results])
        return jsonify({"query": q, "tag": tag, "has_more": has_more,
                        "results": [_serialize(s) for s in results]})

    @app.get("/api/tags")
    def api_tags():
        return jsonify({"tags": [{"tag": t, "count": n, "emoji": EMOJI.get(t, "")}
                                 for t, n in db.tag_counts().items()]})

    @app.get("/api/duplicates")
    def api_duplicates():
        groups = find_duplicate_groups(db)
        return jsonify({"groups": [[_serialize(s) for s in g] for g in groups],
                        "extra": sum(len(g) - 1 for g in groups)})

    @app.post("/api/delete")
    def api_delete():
        """Move screenshots to the Recycle Bin (recoverable) and forget them."""
        require_local_ajax()
        ids = [int(i) for i in (request.get_json(silent=True) or {}).get("ids", [])]
        deleted, failed = [], []
        for shot in db.get_many(ids):
            try:
                if os.path.exists(shot.path):
                    send2trash(shot.path)
                deleted.append(shot.id)
            except Exception as exc:
                failed.append({"id": shot.id, "error": str(exc)})
        db.remove_ids(deleted)
        return jsonify({"deleted": deleted, "failed": failed})

    @app.get("/api/forgotten")
    def api_forgotten():
        limit = min(max(int(request.args.get("limit", 8) or 8), 1), 100)
        return jsonify({"results": [_serialize(s) for s in db.forgotten(limit=limit)]})

    @app.get("/api/stats")
    def api_stats():
        groups = find_duplicate_groups(db)
        return jsonify({
            "total": db.count(),
            "this_week": db.count_since(time.time() - 7 * 86400),
            "forgotten": db.forgotten_count(),
            "duplicates": sum(len(g) - 1 for g in groups),
        })

    @app.get("/api/status")
    def api_status():
        return jsonify({**indexer.status, "count": db.count(), "ocr_backend": ocr_backend,
                        "smart": embedder is not None})

    @app.post("/api/rescan")
    def api_rescan():
        require_local_ajax()
        indexer.trigger()
        return jsonify({"ok": True})

    @app.get("/thumb/<int:screenshot_id>")
    def thumb(screenshot_id: int):
        shot = get_or_404(screenshot_id)
        target = thumbs_dir / f"{shot.id}-{int(shot.mtime)}-{THUMB_SIZE[0]}.jpg"
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
