
import threading
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

import os

DOWNLOAD_DIR = Path(
    os.environ.get("DOWNLOAD_DIR", "/tmp/tubeflow-downloads")
)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

lock = threading.Lock()

state = {
    "running": False,
    "status": "Ready",
    "progress": 0,
    "speed": "",
    "filename": "",
    "error": "",
}


def update(**values):
    with lock:
        state.update(values)


def download_media(url, mode, quality, audio_format, thumbnail):
    try:
        def progress_hook(data):
            if data["status"] == "downloading":
                total = (
                    data.get("total_bytes")
                    or data.get("total_bytes_estimate")
                    or 0
                )
                downloaded = data.get("downloaded_bytes", 0)
                percent = downloaded / total * 100 if total else 0
                speed = data.get("speed")

                update(
                    status="Downloading audio..." if mode == "audio"
                    else "Downloading video...",
                    progress=round(percent, 1),
                    speed=(
                        f"{speed / 1024 / 1024:.2f} MB/s"
                        if speed else ""
                    ),
                    filename=data.get("filename", ""),
                )

            elif data["status"] == "finished":
                update(
                    status="Converting audio..." if mode == "audio"
                    else "Processing video...",
                    progress=99,
                    speed="",
                    filename=data.get("filename", ""),
                )

        options = {
            "outtmpl": str(DOWNLOAD_DIR / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "retries": 5,
            "progress_hooks": [progress_hook],
        }

        if mode == "audio":
            options["format"] = "bestaudio/best"
            options["writethumbnail"] = bool(thumbnail)
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "192",
                }
            ]

            if thumbnail:
                options["postprocessors"].extend([
                    {
                        "key": "FFmpegThumbnailsConvertor",
                        "format": "jpg",
                    },
                    {
                        "key": "EmbedThumbnail",
                    },
                ])

        else:
            options["format"] = (
                f"bestvideo[height<={quality}]+bestaudio/"
                f"best[height<={quality}]"
            )
            options["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        update(
            running=False,
            status="Download completed!",
            progress=100,
            speed="",
        )

    except Exception as exc:
        update(
            running=False,
            status="Download failed",
            error=str(exc),
            speed="",
        )


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/progress")
def progress():
    with lock:
        return jsonify(state.copy())


@app.post("/api/download")
def start_download():
    data = request.get_json(silent=True) or {}

    url = str(data.get("url", "")).strip()
    mode = data.get("mode", "video")
    quality = data.get("quality", 720)
    audio_format = data.get("audio_format", "mp3")
    thumbnail = data.get("thumbnail", True)

    if mode not in ("video", "audio"):
        return jsonify(error="Choose video or audio mode."), 400

    if mode == "video" and quality not in (360, 480, 720, 1080):
        return jsonify(error="Choose a valid video quality."), 400

    if mode == "audio" and audio_format not in ("mp3", "m4a"):
        return jsonify(error="Choose MP3 or M4A audio."), 400

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        host = ""

    if parsed.scheme not in ("http", "https") or not (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
    ):
        return jsonify(error="Please enter a valid YouTube URL."), 400

    with lock:
        if state["running"]:
            return jsonify(error="A download is already running."), 409

        state.update({
            "running": True,
            "status": "Preparing download...",
            "progress": 0,
            "speed": "",
            "filename": "",
            "error": "",
        })

    threading.Thread(
        target=download_media,
        args=(url, mode, quality, audio_format, thumbnail),
        daemon=True,
    ).start()

    return jsonify(message="Download started."), 202


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
    )
