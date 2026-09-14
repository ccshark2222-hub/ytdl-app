"""
Local YouTube downloader backend.
Runs on localhost only. Uses yt-dlp for extraction/download and ffmpeg for merging.

Endpoints:
  GET  /                    -> serves the frontend
  POST /api/info            -> {url} returns video metadata + available formats
  POST /api/download        -> {url, format_id, mode} starts a download, returns job_id
  GET  /api/progress/{job}  -> current progress for a job (polled by the frontend)
  GET  /api/file/{job}      -> serves the finished file for the browser to save
"""

import os
import re
import uuid
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp

APP_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = APP_DIR / "frontend"
DOWNLOAD_DIR = APP_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Local YouTube Downloader")

# In-memory job store: job_id -> {status, percent, speed, eta, filepath, filename, error}
JOBS: dict[str, dict] = {}


# ---------- request models ----------
class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str | None = None   # specific format the user picked
    mode: str = "video"            # "video" or "audio"


# ---------- helpers ----------
def _human_size(num_bytes):
    if not num_bytes:
        return None
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < step:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= step
    return f"{num_bytes:.1f} PB"


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip()[:180] or "video"


def _looks_like_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url, re.I))


# ---------- endpoints ----------
@app.post("/api/info")
def get_info(req: InfoRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Paste a link first.")
    if not _looks_like_youtube(url):
        raise HTTPException(400, "That doesn't look like a YouTube link.")

    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that video: {e}")

    # Build a clean, de-duplicated list of video quality options.
    # We prefer mp4 progressive/adaptive video streams and show estimated size.
    seen_heights = {}
    for f in info.get("formats", []):
        if f.get("vcodec") == "none":
            continue  # audio-only, handled separately
        height = f.get("height")
        if not height:
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        ext = f.get("ext")
        # keep the best (largest known size / mp4-preferred) per resolution
        prev = seen_heights.get(height)
        score = (1 if ext == "mp4" else 0, size or 0)
        if prev is None or score > prev["_score"]:
            seen_heights[height] = {
                "format_id": f.get("format_id"),
                "height": height,
                "label": f"{height}p",
                "ext": ext,
                "fps": f.get("fps"),
                "filesize": size,
                "filesize_human": _human_size(size),
                "note": f.get("format_note", ""),
                "_score": score,
            }

    video_options = sorted(seen_heights.values(), key=lambda x: x["height"], reverse=True)
    for v in video_options:
        v.pop("_score", None)

    # Best audio-only option for MP3 mode
    audio_sizes = [
        (f.get("filesize") or f.get("filesize_approx") or 0)
        for f in info.get("formats", [])
        if f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    best_audio = max(audio_sizes) if audio_sizes else None

    return {
        "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "duration_string": info.get("duration_string"),
        "thumbnail": info.get("thumbnail"),
        "view_count": info.get("view_count"),
        "webpage_url": info.get("webpage_url", url),
        "video_options": video_options,
        "audio_size_human": _human_size(best_audio),
    }


def _run_download(job_id: str, url: str, format_id: str | None, mode: str, title: str):
    outtmpl = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0
            JOBS[job_id].update(
                status="downloading",
                percent=round(pct, 1),
                speed=_human_size(d.get("speed")) + "/s" if d.get("speed") else None,
                eta=d.get("eta"),
            )
        elif d["status"] == "finished":
            JOBS[job_id].update(status="processing", percent=100.0)

    if mode == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ],
        }
    else:
        # If a specific video format was chosen, pair it with best audio and let
        # ffmpeg merge into mp4. Fallback to best overall.
        if format_id:
            fmt = f"{format_id}+bestaudio/best"
        else:
            fmt = "bestvideo+bestaudio/best"
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "merge_output_format": "mp4",
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        # find the produced file
        produced = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
        if not produced:
            raise RuntimeError("Download finished but no file was found.")
        filepath = produced[0]
        ext = filepath.suffix.lstrip(".")
        nice_name = f"{_safe_filename(title)}.{ext}"
        JOBS[job_id].update(
            status="done",
            percent=100.0,
            filepath=str(filepath),
            filename=nice_name,
        )
    except Exception as e:
        JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/download")
def start_download(req: DownloadRequest):
    url = req.url.strip()
    if not _looks_like_youtube(url):
        raise HTTPException(400, "That doesn't look like a YouTube link.")

    # grab title for the eventual filename
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video")
    except Exception:
        title = "video"

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "starting", "percent": 0.0}
    t = threading.Thread(
        target=_run_download,
        args=(job_id, url, req.format_id, req.mode, title),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
def progress(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    # don't leak the absolute path to the client
    return {k: v for k, v in job.items() if k != "filepath"}


@app.get("/api/file/{job_id}")
def get_file(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "File not ready.")
    return FileResponse(
        job["filepath"],
        filename=job["filename"],
        media_type="application/octet-stream",
    )


# serve frontend (mounted last so /api routes take priority)
@app.get("/", response_class=HTMLResponse)
def index():
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
