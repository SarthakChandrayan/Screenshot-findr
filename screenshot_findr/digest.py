"""Weekly 'you saved these and never looked' digest, plus the Windows scheduled task for it.

The digest is a standalone HTML file (thumbnails embedded), so it opens in the
browser even when the Screenshot Findr app isn't running.
"""

from __future__ import annotations

import base64
import html
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from .db import Database, Screenshot
from .tags import EMOJI

TASK_NAME = "Screenshot Findr weekly digest"
APP_URL = "http://127.0.0.1:8765/"


def _thumb_data_uri(path: str, size: tuple[int, int] = (420, 420)) -> Optional[str]:
    try:
        with Image.open(path) as img:
            img.thumbnail(size)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=78)
    except Exception:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _card(s: Screenshot) -> str:
    thumb = _thumb_data_uri(s.path)
    img = f'<img src="{thumb}" alt="">' if thumb else '<div class="noimg">no preview</div>'
    tags = " ".join(f'<span class="tag">{EMOJI.get(t, "")} {html.escape(t)}</span>' for t in s.tags)
    text = html.escape(" ".join(s.text.split())[:160])
    uri = Path(s.path).as_uri()
    return f"""
    <a class="card" href="{uri}" title="{html.escape(s.path)}">
      {img}
      <div class="meta">
        <div class="name">{html.escape(s.filename)}</div>
        <div class="date">{datetime.fromtimestamp(s.mtime):%d %b %Y}</div>
        {f'<div class="tags">{tags}</div>' if tags else ''}
        {f'<div class="snip">{text}</div>' if text else ''}
      </div>
    </a>"""


def build_digest(db: Database, limit: int = 12) -> tuple[str, int]:
    """Return (html, number_of_forgotten_screenshots_shown)."""
    new_this_week = db.count_since(time.time() - 7 * 86400)
    forgotten = db.forgotten(limit=limit)
    total_forgotten = db.forgotten_count()
    cards = "".join(_card(s) for s in forgotten)
    body = (
        f'<div class="grid">{cards}</div>' if forgotten
        else '<p class="empty">Nothing forgotten. You\'ve looked at all your screenshots. 🎉</p>'
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your weekly screenshots</title>
<style>
  :root {{ --bg:#f6f7f9; --panel:#fff; --text:#1d2330; --muted:#677085; --border:#e1e4ea; --accent:#2f6fed; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161b; --panel:#1d2027; --text:#e7e9ee; --muted:#9aa2b4; --border:#2d313b; --accent:#6b9bff; }}
  }}
  body {{ margin:0; font:15px/1.45 "Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--text); }}
  main {{ max-width:1100px; margin:0 auto; padding:28px 20px 60px; }}
  h1 {{ font-size:24px; margin:0 0 6px; }}
  .lead {{ color:var(--muted); margin:0 0 22px; }}
  .lead a {{ color:var(--accent); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:14px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; overflow:hidden;
          color:inherit; text-decoration:none; display:flex; flex-direction:column; }}
  .card:hover {{ border-color:var(--accent); }}
  .card img, .noimg {{ width:100%; height:150px; object-fit:cover; object-position:top; display:block; background:var(--border); }}
  .noimg {{ display:grid; place-items:center; color:var(--muted); }}
  .meta {{ padding:8px 10px 10px; }}
  .name {{ font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .date, .snip {{ font-size:12px; color:var(--muted); }}
  .snip {{ margin-top:4px; max-height:3.9em; overflow:hidden; }}
  .tags {{ margin-top:4px; display:flex; flex-wrap:wrap; gap:4px; }}
  .tag {{ font-size:11px; padding:1px 7px; border-radius:99px; border:1px solid var(--border); }}
  .empty {{ color:var(--muted); }}
</style></head>
<body><main>
  <h1>🕰️ Screenshots you saved and forgot</h1>
  <p class="lead">You took <b>{new_this_week}</b> screenshot{'s' if new_this_week != 1 else ''} this week.
  <b>{total_forgotten}</b> older one{'s' if total_forgotten != 1 else ''} you've never opened. Here are a few.
  Click one to open it, or search everything in <a href="{APP_URL}">Screenshot Findr</a> (when it's running).</p>
  {body}
</main></body></html>"""
    return page, len(forgotten)


def write_digest(db: Database, target: Path) -> int:
    page, shown = build_digest(db)
    target.write_text(page, encoding="utf-8")
    return shown


def _scheduled_command(extra_args: list[str]) -> str:
    if getattr(sys, "frozen", False):  # packaged .exe
        return subprocess.list2cmdline([sys.executable, *extra_args, "remind"])
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # runs without flashing a console window
    if pythonw.exists():
        exe = pythonw
    return subprocess.list2cmdline([str(exe), "-m", "screenshot_findr", *extra_args, "remind"])


def install_task(day: str = "SUN", at: str = "10:00", extra_args: Optional[list[str]] = None) -> str:
    """Create (or replace) a weekly Windows scheduled task that opens the digest."""
    if sys.platform != "win32":
        raise RuntimeError("Weekly reminders are only set up automatically on Windows.")
    command = _scheduled_command(extra_args or [])
    subprocess.run(
        ["schtasks", "/Create", "/F", "/SC", "WEEKLY", "/D", day, "/ST", at,
         "/TN", TASK_NAME, "/TR", command],
        check=True, capture_output=True, text=True,
    )
    return command


def remove_task() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Weekly reminders are only set up automatically on Windows.")
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                   check=True, capture_output=True, text=True)
