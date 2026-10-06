# 📸 Screenshot Findr

You take a screenshot to remember something, and then you never see it again.
Screenshot Findr reads the text **inside** every screenshot and lets you search
it, like "flight", "invoice", "error 404" or "wifi password". It can also search
by *meaning*, tags screenshots automatically, finds duplicates, and reminds you
every week about the ones you saved but never came back to.

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
- **Search by meaning** (✨ optional): "shoes I wanted to buy" finds a shopping
  page that says *sneakers, add to cart*, even though the word "shoes" isn't in it.
  Uses a small AI model that runs on your computer (about 70 MB, downloaded once).
- **Automatic tags**: 🧾 receipt, ✈️ travel, 💻 code, ⚠️ error, 💬 chat,
  🛍️ shopping, 🍳 recipe, 📇 contact, 🔗 link, 📅 meeting, 🔑 password, 📱 phone.
  Click a tag to see only those screenshots.
- **Duplicates tab**: groups look-alike screenshots (same screen captured
  twice, resized or re-saved copies) and moves the extras to the **Recycle Bin**
  in one click, so nothing is deleted permanently.
- **"Forgotten" shelf**: a random pick of older screenshots you've never opened.
- **Weekly reminder**: once a week, a page opens with screenshots you forgot about.
- **Open / Show in folder / Copy text / Delete** right from the results.

## Quick start (Windows)

1. Install **Python 3.9+** from <https://www.python.org/downloads/>
   (tick *"Add python.exe to PATH"* during setup).
2. Download or clone this repository.
3. Double-click **`start.bat`**.

The first run installs what's needed, including meaning search. Your browser then opens
<http://127.0.0.1:8765>. The first scan takes a moment if you have
thousands of screenshots, and results appear while it runs.

### Manual install

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[smart]"     # or just: pip install -e .   (without meaning search)
screenshot-findr
```

### Weekly reminder

```powershell
screenshot-findr reminder install                      # every Sunday at 10:00
screenshot-findr reminder install --day FRI --time 18:30
screenshot-findr reminder remove
```

This adds a task called *"Screenshot Findr weekly digest"* to Windows Task
Scheduler. It picks up new screenshots and opens a page with ones you've never
opened. The page works even when the app isn't running. Try it now with
`screenshot-findr remind`.

## Usage

```text
screenshot-findr                          # open the search page (default)
screenshot-findr --folder "D:\My Shots"   # use your own folder(s) (repeatable)
screenshot-findr index                    # just index, then exit
screenshot-findr search wifi password     # search from the terminal
screenshot-findr search total --tag receipt
screenshot-findr dupes                    # list look-alike screenshots
screenshot-findr remind                   # open the forgotten-screenshots digest now
screenshot-findr folders                  # which folders get scanned
screenshot-findr --no-smart               # turn off meaning search
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
pip install -e ".[dev,tesseract,smart]"
pytest
```

Code layout (`screenshot_findr/`):

- `config.py`: where screenshots live, where the index is stored
- `ocr.py`: Windows OCR / Tesseract backends
- `db.py`: SQLite + FTS5 full-text index (upgrades older databases automatically)
- `indexer.py`: incremental folder scanning, background re-scans
- `tags.py`: rule-based auto-tagging
- `dupes.py`: perceptual hashing + look-alike grouping
- `semantic.py`: meaning search with local embeddings (fastembed)
- `digest.py`: weekly digest page + Windows Task Scheduler setup
- `web.py` + `templates/index.html`: the local search page
- `cli.py`: command line

## Ideas for later

- Search pictures without text by what they show (CLIP image embeddings)
- Phone screenshots (via OneDrive / Google Photos sync folders)
- System tray icon and start with Windows
