# 📸 Screenshot Findr

You take a screenshot to remember something, and then you never see it again.
Screenshot Findr reads the text **inside** every screenshot and lets you search
it, like "flight", "invoice", "error 404" or "wifi password". It also shows you
the screenshots you saved but never came back to.

Everything runs **on your own computer**. No images or text leave your machine.

## Features

- **Search by text in the image**: uses the OCR engine built into Windows 10/11,
  so there's nothing extra to install. Words match as you type, and partial
  words work too (`confirm` finds *confirmation*).
- **Finds your screenshot folder automatically**: `Pictures\Screenshots`
  (Win+PrtScn, Snipping Tool), OneDrive-redirected folders, and Xbox Game Bar
  captures (`Videos\Captures`).
- **Keeps itself up to date**: re-scans every minute, and only reads new or
  changed files.
- **"Forgotten" shelf**: a random pick of older screenshots you've never opened.
- **Open / Show in folder / Copy text** right from the results.

## Quick start (Windows)

1. Install **Python 3.9+** from <https://www.python.org/downloads/>
   (tick *"Add python.exe to PATH"* during setup).
2. Download or clone this repository.
3. Double-click **`start.bat`**.

The first run installs what's needed. Your browser then opens
<http://127.0.0.1:8765>. The first scan takes a moment if you have
thousands of screenshots, and results appear while it runs.

### Manual install

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e .
screenshot-findr
```

## Usage

```text
screenshot-findr                          # open the search page (default)
screenshot-findr --folder "D:\My Shots"   # use your own folder(s) (repeatable)
screenshot-findr index                    # just index, then exit
screenshot-findr search wifi password     # search from the terminal
screenshot-findr folders                  # which folders get scanned
screenshot-findr --port 9000 --no-browser
```

The index and thumbnails are stored in `%LOCALAPPDATA%\ScreenshotFindr`.
Delete that folder to start fresh.

### OCR engines

| Engine | When it's used |
| --- | --- |
| `windows` | Default on Windows 10/11. Uses the OCR languages of your Windows display language(s). |
| `tesseract` | Fallback on any OS, if [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and `pip install pytesseract` are installed. |
| `none` | No OCR: only file names are searchable. |

Pick one with `--ocr windows|tesseract|none`.

If the Windows engine reports no languages, add one under
*Settings → Time & language → Language & region* (OCR is part of the basic
language pack).

## Development

```bash
pip install -e ".[dev,tesseract]"
pytest
```

Code layout (`screenshot_findr/`):

- `config.py`: where screenshots live, where the index is stored
- `ocr.py`: Windows OCR / Tesseract backends
- `db.py`: SQLite + FTS5 full-text index
- `indexer.py`: incremental folder scanning, background re-scans
- `web.py` + `templates/index.html`: the local search page
- `cli.py`: command line

## Ideas for later

- Search by meaning ("shoes I wanted to buy") with local embeddings
- Auto-tags: receipt, code, chat, ticket, recipe
- Weekly "you saved these and never looked" reminder
- Duplicate / junk screenshot cleanup
- Phone screenshots (via OneDrive / Google Photos sync folders)
