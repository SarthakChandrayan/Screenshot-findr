"""Scan screenshot folders and keep the database in sync with them."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image

from .config import IMAGE_EXTENSIONS
from .db import Database
from .ocr import OcrFunc

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)


def iter_images(folders: Iterable[Path]) -> Iterable[Path]:
    for folder in folders:
        if not folder.is_dir():
            continue
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                    yield Path(root) / name


def _image_size(path: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None, None


def scan(
    db: Database,
    folders: Iterable[Path],
    ocr_backend: str,
    ocr: Optional[OcrFunc],
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> ScanResult:
    """Index new/changed images, drop deleted ones. Returns counts."""
    folders = list(folders)
    result = ScanResult()
    known = db.known_files()
    on_disk = list(iter_images(folders))
    seen: set[str] = set()

    todo: list[tuple[Path, os.stat_result, bool]] = []
    for path in on_disk:
        key = str(path)
        seen.add(key)
        try:
            st = path.stat()
        except OSError:
            continue
        prev = known.get(key)
        if prev is None:
            todo.append((path, st, True))
            continue
        size, mtime, prev_backend = prev
        changed = size != st.st_size or abs(mtime - st.st_mtime) > 1e-6
        # Retry OCR for files indexed while no OCR engine was available.
        needs_ocr = prev_backend == "none" and ocr is not None
        if changed or needs_ocr:
            todo.append((path, st, False))
        else:
            result.unchanged += 1

    for i, (path, st, is_new) in enumerate(todo, start=1):
        if progress:
            progress(i, len(todo), path.name)
        text = ""
        if ocr is not None:
            try:
                text = ocr(str(path)).strip()
            except Exception as exc:  # one broken image shouldn't stop the scan
                log.warning("OCR failed for %s: %s", path, exc)
                result.failed.append(str(path))
        width, height = _image_size(path)
        db.upsert(
            path=str(path),
            filename=path.name,
            size=st.st_size,
            mtime=st.st_mtime,
            width=width,
            height=height,
            text=text,
            ocr_backend=ocr_backend if ocr is not None else "none",
        )
        if is_new:
            result.added += 1
        else:
            result.updated += 1

    # Only forget files that lived inside a folder we just scanned.
    roots = [os.path.normcase(str(f)) for f in folders if f.is_dir()]
    gone = [
        p for p in known
        if p not in seen and any(os.path.normcase(p).startswith(r + os.sep) for r in roots)
    ]
    if gone:
        db.remove_paths(gone)
        result.removed = len(gone)
    return result


class BackgroundIndexer:
    """Runs `scan` in a thread, now and then every `interval` seconds."""

    def __init__(self, db: Database, folders: list[Path], ocr_backend: str,
                 ocr: Optional[OcrFunc], interval: float = 60.0):
        self.db = db
        self.folders = folders
        self.ocr_backend = ocr_backend
        self.ocr = ocr
        self.interval = interval
        self.status = {"running": False, "done": 0, "total": 0, "current": "", "last": None}
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _progress(self, done: int, total: int, name: str) -> None:
        self.status.update(done=done, total=total, current=name)

    def run_once(self) -> ScanResult:
        with self._lock:
            self.status.update(running=True, done=0, total=0, current="")
            try:
                res = scan(self.db, self.folders, self.ocr_backend, self.ocr, self._progress)
                self.status["last"] = res.__dict__ | {"failed": len(res.failed)}
                return res
            finally:
                self.status.update(running=False, current="")

    def _loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Background scan failed")
            self._wake.wait(self.interval)
            self._wake.clear()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="indexer")
            self._thread.start()

    def trigger(self) -> None:
        self._wake.set()
