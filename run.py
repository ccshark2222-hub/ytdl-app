#!/usr/bin/env python3
"""
Stash launcher — starts the local server and opens your browser.
Usage:  python3 run.py
"""
import subprocess
import sys
import shutil
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8000
ROOT = Path(__file__).resolve().parent


def check_deps():
    missing = []
    for mod in ("yt_dlp", "fastapi", "uvicorn"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod.replace("_", "-"))
    if missing:
        print("Missing Python packages:", ", ".join(missing))
        print("Install them with:\n  pip install " + " ".join(missing))
        sys.exit(1)
    if shutil.which("ffmpeg") is None:
        print("WARNING: ffmpeg is not installed.")
        print("  Downloads above 1080p (and MP3 conversion) need it.")
        print("  macOS:  brew install ffmpeg")
        print("  Windows: winget install ffmpeg   (or download from ffmpeg.org)")
        print("  Linux:  sudo apt install ffmpeg\n")


def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


if __name__ == "__main__":
    check_deps()
    print(f"\n  Stash is running at  http://127.0.0.1:{PORT}/")
    print("  Press Ctrl+C to stop.\n")
    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn
    uvicorn.run("backend.server:app", host="127.0.0.1", port=PORT, log_level="warning")
