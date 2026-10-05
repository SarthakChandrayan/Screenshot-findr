"""Command line entry point.

    screenshot-findr                 # index + open the search page in your browser
    screenshot-findr index           # just (re)index, then exit
    screenshot-findr search invoice  # search from the terminal
    screenshot-findr folders         # show which folders are scanned
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import data_dir, default_screenshot_folders
from .db import Database
from .indexer import BackgroundIndexer, scan
from .ocr import get_ocr


def _folders(args: argparse.Namespace) -> list[Path]:
    if args.folder:
        return [Path(f).expanduser() for f in args.folder]
    return default_screenshot_folders()


def _print_progress(done: int, total: int, name: str) -> None:
    sys.stdout.write(f"\r  reading {done}/{total}: {name[:60]:<60}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


def cmd_index(args, db: Database) -> int:
    folders = _folders(args)
    if not folders:
        print("No screenshot folders found. Pass one with --folder.")
        return 1
    backend, ocr = get_ocr(args.ocr)
    print(f"OCR engine: {backend}")
    if ocr is None:
        print("  (no OCR available: only file names will be searchable)")
    for f in folders:
        print(f"Scanning {f}")
    res = scan(db, folders, backend, ocr, _print_progress)
    print(f"Done: {res.added} new, {res.updated} updated, {res.removed} removed, "
          f"{res.unchanged} unchanged, {len(res.failed)} failed. Total: {db.count()}")
    return 0


def cmd_search(args, db: Database) -> int:
    results = db.search(" ".join(args.query), limit=args.limit)
    if not results:
        print("No matches.")
        return 1
    for s in results:
        when = datetime.fromtimestamp(s.mtime).strftime("%Y-%m-%d %H:%M")
        snippet = (s.snippet or "").replace("[[", "\033[1m").replace("]]", "\033[0m").replace("\n", " ")
        print(f"{when}  {s.path}")
        if snippet:
            print(f"    {snippet}")
    return 0


def cmd_folders(args, db: Database) -> int:
    folders = _folders(args)
    if not folders:
        print("No screenshot folders found. Pass one with --folder.")
        return 1
    for f in folders:
        print(f)
    return 0


def cmd_serve(args, db: Database) -> int:
    import flask.cli

    from .web import create_app

    # Keep the console tidy: no Flask banner or per-request log lines.
    flask.cli.show_server_banner = lambda *a, **k: None
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    folders = _folders(args)
    backend, ocr = get_ocr(args.ocr)
    indexer = BackgroundIndexer(db, folders, backend, ocr, interval=args.interval)
    indexer.start()
    app = create_app(db, indexer, data_dir() / "thumbs", backend)

    url = f"http://127.0.0.1:{args.port}/"
    print(f"Screenshot Findr is running at {url}  (Ctrl+C to stop)")
    print(f"OCR engine: {backend}")
    print("Watching: " + (", ".join(map(str, folders)) or "no folders found; use --folder"))
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
    return 0


def _add_common(parser: argparse.ArgumentParser, top_level: bool) -> None:
    # Sub-commands use SUPPRESS so options given before the sub-command aren't reset.
    d = (lambda v: v) if top_level else (lambda v: argparse.SUPPRESS)
    parser.add_argument("--folder", action="append", metavar="PATH", default=d(None),
                        help="screenshot folder to scan (repeatable; default: auto-detect)")
    parser.add_argument("--ocr", choices=["auto", "windows", "tesseract", "none"], default=d("auto"),
                        help="OCR engine to use (default: auto)")
    parser.add_argument("--db", metavar="FILE", default=d(None), help="index database file")


def _add_serve_options(parser: argparse.ArgumentParser, top_level: bool) -> None:
    d = (lambda v: v) if top_level else (lambda v: argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=d(8765))
    parser.add_argument("--no-browser", action="store_true", default=d(False))
    parser.add_argument("--interval", type=float, default=d(60), help="seconds between rescans")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="screenshot-findr",
                                     description="Find screenshots by the text inside them.")
    parser.add_argument("--version", action="version", version=__version__)
    _add_common(parser, top_level=True)
    _add_serve_options(parser, top_level=True)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="run the search page (default)")
    _add_common(p, top_level=False)
    _add_serve_options(p, top_level=False)
    p = sub.add_parser("index", help="index screenshots and exit")
    _add_common(p, top_level=False)
    p = sub.add_parser("search", help="search from the terminal")
    _add_common(p, top_level=False)
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("folders", help="list the folders that get scanned")
    _add_common(p, top_level=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    db = Database(args.db or data_dir() / "index.sqlite3")
    commands = {"index": cmd_index, "search": cmd_search, "folders": cmd_folders}
    try:
        return commands.get(args.command, cmd_serve)(args, db)
    except KeyboardInterrupt:
        return 130
    finally:
        db.close()
