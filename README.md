# Stash — local YouTube downloader

A clean, ad-free video downloader that runs entirely on your own machine.
Paste a link, pick the quality (up to whatever the source actually offers — 4K/8K
included), and save it. No paywalled resolutions, no fake download buttons.

Built with `yt-dlp` (extraction + download) and `ffmpeg` (merging high-res
video/audio streams and MP3 conversion), wrapped in a small FastAPI server with a
single-page frontend.

---

## Setup (one time)

You need **Python 3.9+** and **ffmpeg** installed.

1. Install ffmpeg:
   - **macOS:** `brew install ffmpeg`
   - **Windows:** `winget install ffmpeg` (or grab it from ffmpeg.org and add to PATH)
   - **Linux:** `sudo apt install ffmpeg`

2. Install the Python packages:
   ```
   pip install -r requirements.txt
   ```

## Run it

```
python3 run.py
```

This starts the server and opens `http://127.0.0.1:8000/` in your browser.
Downloads are saved through your browser's normal "Save file" flow. Press
Ctrl+C in the terminal to stop.

---

## How it works

- **`backend/server.py`** — FastAPI app. `/api/info` reads a video's metadata and
  available formats (with estimated file sizes); `/api/download` runs the download
  in a background thread; `/api/progress/{job}` reports live progress; `/api/file/{job}`
  hands the finished file to the browser.
- **`frontend/index.html`** — the whole UI in one file (HTML/CSS/JS, no build step).
- **`downloads/`** — where files land on the server side before being served to you.

### On quality
Above 1080p, YouTube serves video and audio as *separate* streams. The app grabs
both and merges them into a single MP4 with ffmpeg automatically — that's why
ffmpeg is required for the highest resolutions.

---

## Sharing it later

The code is structured so you can grow it without a rewrite:

- **Package as a desktop app:** wrap `run.py` with [PyInstaller](https://pyinstaller.org)
  to produce a double-click executable, or use [pywebview](https://pywebview.flowlib.org/)
  to run the frontend in a native window instead of a browser tab.
- **Bundle ffmpeg** so users don't have to install it separately (ship a static
  ffmpeg binary and point yt-dlp at it via the `ffmpeg_location` option).
- **Deploy for others (web):** possible, but note that a *public* downloader
  service carries more legal/ToS exposure than a personal tool, and you'd want
  rate limiting, queueing, and abuse protection. Keep it personal/local unless
  you've thought that through.

---

## Note on use
This is for personal use — your own uploads, Creative Commons / public-domain
content, or material you otherwise have the right to download. Downloading
copyrighted content you don't have rights to generally violates YouTube's Terms
of Service.
