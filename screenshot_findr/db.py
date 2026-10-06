"""SQLite storage with full-text search over the text found in screenshots."""

from __future__ import annotations

import functools
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .tags import decode as decode_tags
from .tags import encode as encode_tags

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenshots (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    width       INTEGER,
    height      INTEGER,
    text        TEXT NOT NULL DEFAULT '',
    ocr_backend TEXT NOT NULL DEFAULT 'none',
    indexed_at  REAL NOT NULL,
    view_count  INTEGER NOT NULL DEFAULT 0,
    last_viewed REAL
);
CREATE INDEX IF NOT EXISTS idx_screenshots_mtime ON screenshots(mtime);

CREATE VIRTUAL TABLE IF NOT EXISTS screenshots_fts USING fts5(
    filename, text,
    content='screenshots', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS screenshots_ai AFTER INSERT ON screenshots BEGIN
    INSERT INTO screenshots_fts(rowid, filename, text) VALUES (new.id, new.filename, new.text);
END;
CREATE TRIGGER IF NOT EXISTS screenshots_ad AFTER DELETE ON screenshots BEGIN
    INSERT INTO screenshots_fts(screenshots_fts, rowid, filename, text)
    VALUES ('delete', old.id, old.filename, old.text);
END;
CREATE TRIGGER IF NOT EXISTS screenshots_au AFTER UPDATE OF filename, text ON screenshots BEGIN
    INSERT INTO screenshots_fts(screenshots_fts, rowid, filename, text)
    VALUES ('delete', old.id, old.filename, old.text);
    INSERT INTO screenshots_fts(rowid, filename, text) VALUES (new.id, new.filename, new.text);
END;
"""

# Columns added after the first release; added to existing databases on open.
MIGRATIONS = {
    "tags": "ALTER TABLE screenshots ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
    "phash": "ALTER TABLE screenshots ADD COLUMN phash TEXT",
    "embedding": "ALTER TABLE screenshots ADD COLUMN embedding BLOB",
    "embed_model": "ALTER TABLE screenshots ADD COLUMN embed_model TEXT",
}


@dataclass
class Screenshot:
    id: int
    path: str
    filename: str
    size: int
    mtime: float
    width: Optional[int]
    height: Optional[int]
    text: str
    view_count: int
    last_viewed: Optional[float]
    tags: list[str] = field(default_factory=list)
    snippet: str = ""
    match: str = "text"  # "text" (words matched) or "meaning" (semantic match)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Screenshot":
        keys = row.keys()
        return cls(
            id=row["id"],
            path=row["path"],
            filename=row["filename"],
            size=row["size"],
            mtime=row["mtime"],
            width=row["width"],
            height=row["height"],
            text=row["text"],
            view_count=row["view_count"],
            last_viewed=row["last_viewed"],
            tags=decode_tags(row["tags"]),
            snippet=row["snippet"] if "snippet" in keys else "",
        )


_COLUMNS = ("s.id, s.path, s.filename, s.size, s.mtime, s.width, s.height, s.text, "
            "s.view_count, s.last_viewed, s.tags")


def build_fts_query(user_query: str) -> str:
    """Turn free text into a safe FTS5 query: every word must match, as a prefix."""
    words = re.findall(r"\w+", user_query, flags=re.UNICODE)
    return " ".join(f'"{w}"*' for w in words)


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # The web server and the background indexer share this connection.
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(screenshots)")}
        for column, ddl in MIGRATIONS.items():
            if column not in existing:
                self.conn.execute(ddl)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_phash ON screenshots(phash)")
        self.conn.commit()

    @_locked
    def close(self) -> None:
        self.conn.close()

    # --- writes -----------------------------------------------------------

    @_locked
    def upsert(self, *, path: str, filename: str, size: int, mtime: float,
               width: Optional[int], height: Optional[int], text: str, ocr_backend: str,
               tags: Optional[list[str]] = None, phash: Optional[str] = None) -> None:
        self.conn.execute(
            """
            INSERT INTO screenshots (path, filename, size, mtime, width, height, text, ocr_backend,
                                     indexed_at, tags, phash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename, size=excluded.size, mtime=excluded.mtime,
                width=excluded.width, height=excluded.height, text=excluded.text,
                ocr_backend=excluded.ocr_backend, indexed_at=excluded.indexed_at,
                tags=excluded.tags, phash=excluded.phash,
                embedding=CASE WHEN screenshots.text = excluded.text THEN screenshots.embedding END,
                embed_model=CASE WHEN screenshots.text = excluded.text THEN screenshots.embed_model END
            """,
            (path, filename, size, mtime, width, height, text, ocr_backend, time.time(),
             encode_tags(tags or []), phash),
        )
        self.conn.commit()

    @_locked
    def remove_paths(self, paths: list[str]) -> None:
        self.conn.executemany("DELETE FROM screenshots WHERE path = ?", [(p,) for p in paths])
        self.conn.commit()

    @_locked
    def set_meta(self, screenshot_id: int, tags: list[str], phash: Optional[str]) -> None:
        self.conn.execute("UPDATE screenshots SET tags = ?, phash = ? WHERE id = ?",
                          (encode_tags(tags), phash, screenshot_id))
        self.conn.commit()

    @_locked
    def set_embeddings(self, items: list[tuple[int, bytes]], model: str) -> None:
        self.conn.executemany("UPDATE screenshots SET embedding = ?, embed_model = ? WHERE id = ?",
                              [(blob, model, sid) for sid, blob in items])
        self.conn.commit()

    @_locked
    def remove_ids(self, ids: list[int]) -> None:
        self.conn.executemany("DELETE FROM screenshots WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    @_locked
    def mark_viewed(self, screenshot_id: int) -> None:
        self.conn.execute(
            "UPDATE screenshots SET view_count = view_count + 1, last_viewed = ? WHERE id = ?",
            (time.time(), screenshot_id),
        )
        self.conn.commit()

    # --- reads ------------------------------------------------------------

    @_locked
    def known_files(self) -> dict[str, tuple[int, float, str, bool]]:
        """path -> (size, mtime, ocr_backend, has_meta) for change detection."""
        rows = self.conn.execute("SELECT path, size, mtime, ocr_backend, phash FROM screenshots")
        return {r["path"]: (r["size"], r["mtime"], r["ocr_backend"], r["phash"] is not None)
                for r in rows}

    @_locked
    def get_by_path(self, path: str) -> Optional[Screenshot]:
        row = self.conn.execute(f"SELECT {_COLUMNS} FROM screenshots s WHERE s.path = ?",
                                (path,)).fetchone()
        return Screenshot.from_row(row) if row else None

    @_locked
    def get_many(self, ids: list[int]) -> list[Screenshot]:
        """Screenshots for these ids, in the same order."""
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT {_COLUMNS} FROM screenshots s WHERE s.id IN ({marks})",
                                 ids).fetchall()
        by_id = {r["id"]: Screenshot.from_row(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    @_locked
    def needing_embedding(self, model: str, limit: int = 64) -> list[tuple[int, str]]:
        rows = self.conn.execute(
            """SELECT id, text FROM screenshots
               WHERE text != '' AND (embedding IS NULL OR embed_model IS NOT ?)
               LIMIT ?""",
            (model, limit),
        ).fetchall()
        return [(r["id"], r["text"]) for r in rows]

    @_locked
    def embeddings(self, model: str, tag: Optional[str] = None) -> list[tuple[int, bytes]]:
        sql = "SELECT id, embedding FROM screenshots WHERE embedding IS NOT NULL AND embed_model = ?"
        params: list = [model]
        if tag:
            sql += " AND tags LIKE ?"
            params.append(f"%,{tag},%")
        return [(r["id"], r["embedding"]) for r in self.conn.execute(sql, params)]

    @_locked
    def hashes(self) -> list[tuple[int, str, str]]:
        rows = self.conn.execute(
            "SELECT id, phash, text FROM screenshots WHERE phash IS NOT NULL AND phash != ''")
        return [(r["id"], r["phash"], r["text"]) for r in rows]

    @_locked
    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for (stored,) in self.conn.execute("SELECT tags FROM screenshots WHERE tags != ''"):
            for t in decode_tags(stored):
                counts[t] = counts.get(t, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @_locked
    def get(self, screenshot_id: int) -> Optional[Screenshot]:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM screenshots s WHERE s.id = ?", (screenshot_id,)
        ).fetchone()
        return Screenshot.from_row(row) if row else None

    @_locked
    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]

    @_locked
    def search(self, query: str, limit: int = 60, offset: int = 0,
               tag: Optional[str] = None) -> list[Screenshot]:
        fts_query = build_fts_query(query)
        if not fts_query:
            return self.recent(limit, offset, tag)
        rows = self.conn.execute(
            f"""
            SELECT {_COLUMNS},
                   snippet(screenshots_fts, 1, '[[', ']]', ' … ', 16) AS snippet
            FROM screenshots_fts
            JOIN screenshots s ON s.id = screenshots_fts.rowid
            WHERE screenshots_fts MATCH ? AND (? IS NULL OR s.tags LIKE ?)
            ORDER BY bm25(screenshots_fts, 2.0, 1.0), s.mtime DESC
            LIMIT ? OFFSET ?
            """,
            (fts_query, tag, f"%,{tag},%", limit, offset),
        ).fetchall()
        return [Screenshot.from_row(r) for r in rows]

    @_locked
    def recent(self, limit: int = 60, offset: int = 0, tag: Optional[str] = None) -> list[Screenshot]:
        rows = self.conn.execute(
            f"""SELECT {_COLUMNS} FROM screenshots s
                WHERE (? IS NULL OR s.tags LIKE ?)
                ORDER BY s.mtime DESC LIMIT ? OFFSET ?""",
            (tag, f"%,{tag},%", limit, offset),
        ).fetchall()
        return [Screenshot.from_row(r) for r in rows]

    @_locked
    @_locked
    def count_since(self, timestamp: float) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM screenshots WHERE mtime >= ?",
                                 (timestamp,)).fetchone()[0]

    @_locked
    def forgotten_count(self, min_age_days: float = 3) -> int:
        cutoff = time.time() - min_age_days * 86400
        return self.conn.execute(
            "SELECT COUNT(*) FROM screenshots WHERE view_count = 0 AND mtime < ?", (cutoff,)
        ).fetchone()[0]

    @_locked
    def forgotten(self, limit: int = 12, min_age_days: float = 3) -> list[Screenshot]:
        """Screenshots never opened through the app and at least a few days old, picked at random."""
        cutoff = time.time() - min_age_days * 86400
        rows = self.conn.execute(
            f"""
            SELECT {_COLUMNS} FROM screenshots s
            WHERE s.view_count = 0 AND s.mtime < ?
            ORDER BY RANDOM() LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [Screenshot.from_row(r) for r in rows]
