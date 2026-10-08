"""Command line entry point.

    screenshot-findr                 # index + open the search page in your browser
    screenshot-findr index           # just (re)index, then exit
    screenshot-findr search invoice  # search from the terminal
    screenshot-findr folders         # show which folders are scanned
    screenshot-findr dupes           # list look-alike screenshots
    screenshot-findr remind          # open the 'forgotten screenshots' digest
    screenshot-findr reminder install   # ...every Sunday at 10:00 (Windows)
"""

from __future__ import annotations

import argparse
import logging
import os
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
from .semantic import get_embedder, search_by_meaning


def _folders(args: argparse.Namespace) -> list[Path]:
    if args.folder:
        return [Path(f).expanduser() for f in args.folder]
    return default_screenshot_folders()


def _print_progress(done: int, total: int, name: str) -> None:
    sys.stdout.write(f"\r  reading {done}/{total}: {name[:60]:<60}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


def _load_embedder(args):
    if args.no_smart:
        return None
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return None
    print("Loading meaning search (the first time, this downloads a ~70 MB model)…", flush=True)
    return get_embedder(True)


def cmd_index(args, db: Database) -> int:
    folders = _folders(args)
    if not folders:
        print("No screenshot folders found. Pass one with --folder.")
        return 1
    # Load meaning search before OCR: onnxruntime can crash if imported after WinRT.
    embedder = _load_embedder(args)
    print(f"Meaning search: {'on' if embedder else 'off'}")
    backend, ocr = get_ocr(args.ocr, with_embedder=embedder is not None)
    print(f"OCR engine: {backend}")
    if ocr is None:
        print("  (no OCR available: only file names will be searchable)")
    for f in folders:
        print(f"Scanning {f}")
    res = scan(db, folders, backend, ocr, _print_progress, embedder)
    print(f"Done: {res.added} new, {res.updated} updated, {res.removed} removed, "
          f"{res.unchanged} unchanged, {len(res.failed)} failed. Total: {db.count()}")
    return 0


def cmd_search(args, db: Database) -> int:
    if sys.platform == "win32":
        os.system("")  # switches the Windows console into colour (VT) mode
    query = " ".join(args.query)
    results = db.search(query, limit=args.limit, tag=args.tag)
    embedder = _load_embedder(args)
    if embedder is not None:
        results += search_by_meaning(db, embedder, query, tag=args.tag,
                                     exclude=[s.id for s in results], limit=args.limit)
    if not results:
        print("No matches.")
        return 1
    for s in results:
        when = datetime.fromtimestamp(s.mtime).strftime("%Y-%m-%d %H:%M")
        bold, reset = ("\033[1m", "\033[0m") if sys.stdout.isatty() else ("", "")
        snippet = (s.snippet or "").replace("[[", bold).replace("]]", reset).replace("\n", " ")
        label = "  (related)" if s.match == "meaning" else ""
        tags = f"  [{', '.join(s.tags)}]" if s.tags else ""
        print(f"{when}  {s.path}{tags}{label}")
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


def cmd_dupes(args, db: Database) -> int:
    from .web import find_duplicate_groups

    groups = find_duplicate_groups(db)
    if not groups:
        print("No duplicates found.")
        return 0
    for g in groups:
        print(f"keep    {g[0].path}")
        for s in g[1:]:
            print(f"  dupe  {s.path}")
        print()
    extra = sum(len(g) - 1 for g in groups)
    print(f"{len(groups)} group(s), {extra} screenshot(s) you could delete. "
          "Use the Duplicates tab in the app to move them to the Recycle Bin.")
    return 0


def cmd_remind(args, db: Database) -> int:
    from .digest import write_digest

    folders = _folders(args)
    if folders:  # pick up this week's screenshots first
        backend, ocr = get_ocr(args.ocr)
        scan(db, folders, backend, ocr)
    target = data_dir() / "digest.html"
    shown = write_digest(db, target)
    print(f"Digest written to {target} ({shown} forgotten screenshots)")
    if shown and not args.no_browser:
        webbrowser.open(target.as_uri())
    return 0


def cmd_reminder(args, db: Database) -> int:
    import subprocess

    from .digest import TASK_NAME, install_task, remove_task

    try:
        if args.action == "install":
            extra = []
            if args.folder:
                for f in args.folder:
                    extra += ["--folder", str(Path(f).resolve())]
            if args.db:
                extra += ["--db", str(Path(args.db).resolve())]
            install_task(args.day.upper(), args.time, extra)
            print(f"Done. Every {args.day.capitalize()} at {args.time} your forgotten screenshots "
                  f"will open in the browser.\n(Task Scheduler entry: \"{TASK_NAME}\")")
        else:
            remove_task()
            print("Weekly reminder removed.")
    except RuntimeError as exc:
        print(exc)
        return 1
    except subprocess.CalledProcessError as exc:
        print("Task Scheduler said: " + (exc.stderr or exc.stdout or str(exc)).strip())
        return 1
    return 0


def cmd_serve(args, db: Database) -> int:
    import flask.cli

    from .web import create_app

    # Keep the console tidy: no Flask banner or per-request log lines.
    flask.cli.show_server_banner = lambda *a, **k: None
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    print(f"Starting Screenshot Findr {__version__}…", flush=True)
    folders = _folders(args)
    # Load meaning search before OCR: onnxruntime can crash if imported after WinRT.
    embedder = _load_embedder(args)
    print("Checking the text reader (OCR)…", flush=True)
    backend, ocr = get_ocr(args.ocr, with_embedder=embedder is not None)
    indexer = BackgroundIndexer(db, folders, backend, ocr, interval=args.interval, embedder=embedder)
    indexer.start()
    app = create_app(db, indexer, data_dir() / "thumbs", backend, embedder)

    url = f"http://127.0.0.1:{args.port}/"
    print(f"Screenshot Findr is running at {url}  (Ctrl+C to stop)")
    print(f"OCR engine: {backend}")
    if embedder:
        print("Meaning search: on")
    elif not args.no_smart:
        print('Meaning search: off (install with: pip install -e ".[smart]")')
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
    parser.add_argument("--no-smart", action="store_true", default=d(False),
                        help="turn off search by meaning")


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
    p.add_argument("--tag", help="only screenshots with this tag (e.g. receipt, code)")
    p = sub.add_parser("folders", help="list the folders that get scanned")
    _add_common(p, top_level=False)
    p = sub.add_parser("dupes", help="list look-alike screenshots")
    _add_common(p, top_level=False)
    p = sub.add_parser("remind", help="open the 'forgotten screenshots' digest")
    _add_common(p, top_level=False)
    p.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS)
    p = sub.add_parser("reminder", help="set up the weekly digest in Windows Task Scheduler")
    _add_common(p, top_level=False)
    p.add_argument("action", choices=["install", "remove"])
    p.add_argument("--day", default="SUN", choices=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                   type=str.upper)
    p.add_argument("--time", default="10:00", help="HH:MM, 24-hour clock (default 10:00)")
    return parser


def main(argv: list[str] | None = None) -> int:
    import faulthandler

    faulthandler.enable()  # if native code ever crashes Python, at least say where
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    db = Database(args.db or data_dir() / "index.sqlite3")
    commands = {"index": cmd_index, "search": cmd_search, "folders": cmd_folders,
                "dupes": cmd_dupes, "remind": cmd_remind, "reminder": cmd_reminder}
    try:
        return commands.get(args.command, cmd_serve)(args, db)
    except KeyboardInterrupt:
        return 130
    finally:
        db.close()
