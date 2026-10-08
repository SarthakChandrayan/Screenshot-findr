"""Where screenshots live and where we keep our own data."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

# Known-folder IDs as they appear under "User Shell Folders" in the registry.
_SCREENSHOTS_FOLDER_ID = "{B7BEDE81-DF94-4682-A7D8-57A52620B86F}"
_PICTURES_FOLDER_ID = "My Pictures"


def data_dir() -> Path:
    """Folder holding the index database and thumbnail cache."""
    override = os.environ.get("SCREENSHOT_FINDR_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        path = Path(os.environ["LOCALAPPDATA"]) / "ScreenshotFindr"
    else:
        path = Path.home() / ".screenshot-findr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _windows_shell_folder(value_name: str) -> Path | None:
    """Read a (possibly redirected, e.g. to OneDrive) shell folder from the registry."""
    try:
        import winreg
    except ImportError:
        return None
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            raw, _ = winreg.QueryValueEx(key, value_name)
    except OSError:
        return None
    return Path(os.path.expandvars(raw))


# macOS names screenshots like "Screenshot 2026-10-08 at 10.42.07.png" (older: "Screen Shot ...").
_MAC_SCREENSHOT_NAME = re.compile(r"^(Screenshot|Screen Shot|Screen Recording)\b", re.IGNORECASE)


def mac_screenshot_folder() -> Path:
    """Where macOS saves screenshots: the user's custom location, else the Desktop."""
    try:
        out = subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if out and Path(out).expanduser().is_dir():
            return Path(out).expanduser()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def is_screenshot_name(name: str) -> bool:
    return bool(_MAC_SCREENSHOT_NAME.match(name))


def only_screenshot_names(folder: Path) -> bool:
    """On a Mac the screenshot folder is often the Desktop: index only files named like screenshots."""
    return sys.platform == "darwin" and folder.resolve() == mac_screenshot_folder().resolve()


def default_screenshot_folders() -> list[Path]:
    """Folders where Windows (Win+PrtScn, Snipping Tool) or macOS usually save screenshots."""
    home = Path.home()
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(mac_screenshot_folder())

    screenshots = _windows_shell_folder(_SCREENSHOTS_FOLDER_ID)
    if screenshots:
        candidates.append(screenshots)
    pictures = _windows_shell_folder(_PICTURES_FOLDER_ID)
    if pictures:
        candidates.append(pictures / "Screenshots")

    candidates.append(home / "Pictures" / "Screenshots")
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / "Pictures" / "Screenshots")
    candidates.append(home / "OneDrive" / "Pictures" / "Screenshots")
    # Xbox Game Bar captures
    candidates.append(home / "Videos" / "Captures")

    seen: set[str] = set()
    found: list[Path] = []
    for path in candidates:
        key = os.path.normcase(str(path.resolve())) if path.exists() else None
        if key and key not in seen and path.is_dir():
            seen.add(key)
            found.append(path)
    return found
