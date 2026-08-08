from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import re
import os
import json
import glob
import tempfile
import threading
import urllib.request

app = Flask(__name__, static_folder=".", static_url_path="")

# ── FFmpeg location detection (Windows & Linux Cloud Servers) ────
import shutil
FFMPEG_PATH = shutil.which("ffmpeg")
if FFMPEG_PATH:
    FFMPEG_PATH = os.path.dirname(FFMPEG_PATH)
else:
    _FFMPEG_CANDIDATES = [
        r"C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0-full_build\bin",
        r"C:\ffmpeg\bin",
        r"C:\Program Files\FFmpeg\bin",
        "/usr/bin",
        "/usr/local/bin",
    ]
    for _p in _FFMPEG_CANDIDATES:
        if os.path.isfile(os.path.join(_p, "ffmpeg.exe")) or os.path.isfile(os.path.join(_p, "ffmpeg")):
            FFMPEG_PATH = _p
            break

CORS(app)

COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Support Environment Variable for Cloud Deployment (Render, Railway, Heroku, VPS)
def ensure_cookies_env():
    env_cookies = os.environ.get("YOUTUBE_COOKIES") or os.environ.get("COOKIES_TXT")
    if env_cookies:
        try:
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                f.write(env_cookies)
            print("[OK] Updated cookies.txt from environment variable")
        except Exception as e:
            print(f"[!] Failed to write cookies from env var: {e}")

ensure_cookies_env()


def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url.strip())
        if m:
            return m.group(1)
    return None


def parse_json3(data: dict) -> list[dict]:
    snippets = []
    for event in data.get("events", []):
        text = "".join(s.get("utf8", "") for s in event.get("segs", [])).strip()
        if text and text != "\n":
            snippets.append({
                "text": text.replace("\n", " "),
                "start": event.get("tStartMs", 0) / 1000.0,
            })
    return snippets


def fetch_subtitle_url(sub_url: str) -> list[dict]:
    # Ensure we request json3 format
    sep = "&" if "?" in sub_url else "?"
    if "fmt=json3" not in sub_url and "json3" not in sub_url:
        sub_url = sub_url + sep + "fmt=json3"
    req = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    return parse_json3(data)


def build_ydl_opts(use_cookies: bool) -> dict:
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB", "en-CA", "en-AU", "en.*"],
        "subtitlesformat": "json3/vtt/srv1",
    }
    if use_cookies and os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def pick_subtitle_track(info: dict):
    """Return (formats_list, lang_code, is_generated) for the best English track."""
    manual = info.get("subtitles") or {}
    auto   = info.get("automatic_captions") or {}

    for lang in ["en", "en-US", "en-GB", "en-CA", "en-AU"]:
        if lang in manual:
            return manual[lang], lang, False
    for lang in ["en", "en-US", "en-GB"]:
        if lang in auto:
            return auto[lang], lang, True

    # Any available language
    for src, gen in [(manual, False), (auto, True)]:
        if src:
            lang = next(iter(src))
            return src[lang], lang, gen

    return None, None, False


def get_transcript_yt_dlp(video_url: str) -> dict:
    import yt_dlp

    cookies_present = os.path.isfile(COOKIES_FILE)

    # Try with cookies first, then without
    attempts = []
    if cookies_present:
        attempts.append(build_ydl_opts(use_cookies=True))
    attempts.append(build_ydl_opts(use_cookies=False))

    info = None
    last_err = None
    for opts in attempts:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            break
        except Exception as e:
            last_err = e

    if info is None:
        raise Exception(str(last_err))

    formats, lang, is_generated = pick_subtitle_track(info)

    if not formats:
        raise Exception(
            "No subtitles or captions found. "
            "This video may not have captions enabled."
        )

    # Pick best download URL (prefer json3)
    sub_url = None
    for ext in ["json3", "vtt", "srv1", "ttml"]:
        for fmt in formats:
            if fmt.get("ext") == ext:
                sub_url = fmt["url"]
                break
        if sub_url:
            break
    if not sub_url:
        sub_url = formats[0]["url"]

    snippets = fetch_subtitle_url(sub_url)
    if not snippets:
        raise Exception("Subtitle file was empty.")

    plain = " ".join(s["text"] for s in snippets)

    ts_lines = []
    for s in snippets:
        total = int(s["start"])
        m, sec = divmod(total, 60)
        h, m   = divmod(m, 60)
        ts = f"[{h:02d}:{m:02d}:{sec:02d}]" if h else f"[{m:02d}:{sec:02d}]"
        ts_lines.append(f"{ts} {s['text']}")

    return {
        "videoId":     info.get("id", ""),
        "title":       info.get("title", ""),
        "language":    lang or "Unknown",
        "isGenerated": is_generated,
        "plain":       plain,
        "timestamped": "\n".join(ts_lines),
        "cookiesUsed": cookies_present,
    }


# ── Download helpers ─────────────────────────────────────────────

def get_video_info_for_download(url: str) -> dict:
    """Extract video metadata and list of quality options (no-ffmpeg compatible)."""
    import yt_dlp

    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }
    if os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats_raw = info.get("formats", [])

    # Collect all video heights available (ffmpeg is now installed so we
    # can merge separate video+audio streams for full quality).
    all_heights = set()
    for f in formats_raw:
        h = f.get("height")
        if h and f.get("vcodec", "none") not in ("none", None):
            all_heights.add(h)

    if FFMPEG_PATH:
        # High-quality merged formats - requires ffmpeg
        quality_opts = [
            {
                "label": "Best Quality (Auto)",
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                "badge": "4K",
            },
        ]
        for h in [2160, 1440, 1080, 720, 480, 360, 240]:
            if any(height <= h for height in all_heights):
                quality_opts.append({
                    "label": f"{h}p {'(4K)' if h==2160 else '(2K)' if h==1440 else ''}".strip(),
                    "format": (
                        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                        f"/bestvideo[height<={h}]+bestaudio"
                        f"/best[height<={h}]"
                    ),
                    "badge": "HD" if h >= 1080 else None,
                })
    else:
        # No ffmpeg - use pre-merged progressive streams only
        progressive_heights = set()
        for f in formats_raw:
            has_video = f.get("vcodec", "none") not in ("none", None)
            has_audio = f.get("acodec", "none") not in ("none", None)
            h = f.get("height")
            if has_video and has_audio and h:
                progressive_heights.add(h)
        if not progressive_heights:
            progressive_heights = all_heights
        quality_opts = [
            {"label": "Best Quality (Auto)", "format": "best[ext=mp4]/best", "badge": "HD"},
        ]
        for h in [720, 480, 360, 240]:
            if any(height <= h for height in progressive_heights):
                quality_opts.append({
                    "label": f"{h}p",
                    "format": f"best[height<={h}][ext=mp4]/best[height<={h}]/best",
                    "badge": None,
                })

    quality_opts.append({
        "label": "Audio Only",
        "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio",
        "badge": "M4A",
    })

    dur = info.get("duration") or 0
    mins, secs = divmod(int(dur), 60)
    hrs, mins  = divmod(mins, 60)
    dur_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"

    views = info.get("view_count")
    views_str = f"{views:,}" if views else None

    return {
        "title":     info.get("title", "Unknown Video"),
        "thumbnail": info.get("thumbnail", ""),
        "duration":  dur_str,
        "channel":   info.get("uploader", "Unknown Channel"),
        "views":     views_str,
        "video_id":  info.get("id", ""),
        "formats":   quality_opts,
    }


def download_video_to_tempfile(url: str, fmt: str) -> tuple[str, str, str]:
    """Download video to a temp dir, using ffmpeg for high-quality merging if available."""
    import yt_dlp

    tmpdir = tempfile.mkdtemp(prefix="ytdl_")
    is_audio_only = "bestaudio" in fmt and "bestvideo" not in fmt

    opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": os.path.join(tmpdir, "download.%(ext)s"),
        "format": fmt,
        "no_color": True,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    if not is_audio_only:
        opts["merge_output_format"] = "mp4"
    if os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        msg = str(e)
        if "ffmpeg" in msg.lower() or "merging" in msg.lower():
            # ffmpeg unavailable - fall back to best single-file progressive stream
            opts["format"] = "best[ext=mp4]/best"
            opts.pop("merge_output_format", None)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        else:
            raise

    files = glob.glob(os.path.join(tmpdir, "download.*"))
    if not files:
        raise Exception("Download produced no file.")

    filepath   = files[0]
    ext        = os.path.splitext(filepath)[1]
    raw_title  = info.get("title", "video")
    safe_title = re.sub(r'[\/*?:"<>|]', "", raw_title)[:80].strip() or "video"
    filename   = f"{safe_title}{ext}"
    return filepath, filename, tmpdir


def schedule_cleanup(path: str, directory: str, delay: int = 120):
    """Delete temp file and dir after a delay (seconds) in a background thread."""
    def _clean():
        import time
        time.sleep(delay)
        try:
            os.remove(path)
        except Exception:
            pass
        try:
            os.rmdir(directory)
        except Exception:
            pass
    threading.Thread(target=_clean, daemon=True).start()


# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/status", methods=["GET"])
def status():
    """Let the frontend know whether cookies.txt is present."""
    has_cookies = False
    if os.path.isfile(COOKIES_FILE):
        try:
            has_cookies = os.path.getsize(COOKIES_FILE) > 50
        except:
            has_cookies = False
    return jsonify({"cookiesReady": has_cookies})


@app.route("/api/update-cookies", methods=["POST"])
def update_cookies():
    """Update cookies.txt directly from web interface."""
    data = request.get_json(silent=True) or {}
    cookie_content = data.get("cookies", "").strip()

    if not cookie_content:
        return jsonify({"error": "No cookie content provided."}), 400

    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(cookie_content)
        print("[OK] Cookies updated directly via Web UI")
        return jsonify({"success": True, "message": "Cookies saved successfully! You can now generate transcripts and download videos."})
    except Exception as e:
        return jsonify({"error": f"Failed to save cookies: {str(e)}"}), 500



@app.route("/api/transcript", methods=["GET"])
def get_transcript():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided."}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL. Please check the URL and try again."}), 400

    try:
        result = get_transcript_yt_dlp(url)
        return jsonify(result)
    except Exception as e:
        msg = str(e)
        if "Sign in" in msg or "bot" in msg.lower() or "cookies" in msg.lower():
            return jsonify({
                "error": "NEEDS_COOKIES",
                "detail": "YouTube requires authentication. Please follow the setup instructions on the page."
            }), 403
        if "private" in msg.lower() or "unavailable" in msg.lower():
            return jsonify({"error": "This video is private or unavailable."}), 404
        if "subtitles" in msg.lower() or "captions" in msg.lower() or "No subtitles" in msg:
            return jsonify({"error": msg}), 404
        return jsonify({"error": f"Failed to retrieve transcript: {msg}"}), 500


@app.route("/api/video-info", methods=["GET"])
def api_video_info():
    """Return video metadata + available quality options (no download)."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided."}), 400
    if not extract_video_id(url):
        return jsonify({"error": "Invalid YouTube URL. Please check and try again."}), 400

    try:
        data = get_video_info_for_download(url)
        return jsonify(data)
    except Exception as e:
        msg = str(e)
        if "private" in msg.lower() or "unavailable" in msg.lower():
            return jsonify({"error": "This video is private or unavailable."}), 404
        if "Sign in" in msg or "bot" in msg.lower():
            return jsonify({"error": "YouTube blocked this request. Your cookies.txt may be expired."}), 403
        return jsonify({"error": f"Could not fetch video info: {msg}"}), 500


@app.route("/api/download", methods=["GET"])
def api_download_video():
    """Download video and stream as file attachment to browser."""
    url = request.args.get("url", "").strip()
    fmt = request.args.get("format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best")

    if not url:
        return jsonify({"error": "No URL provided."}), 400
    if not extract_video_id(url):
        return jsonify({"error": "Invalid YouTube URL."}), 400

    try:
        filepath, filename, tmpdir = download_video_to_tempfile(url, fmt)
        schedule_cleanup(filepath, tmpdir, delay=120)
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        msg = str(e)
        if "private" in msg.lower() or "unavailable" in msg.lower():
            return jsonify({"error": "This video is private or unavailable."}), 404
        if "Sign in" in msg or "bot" in msg.lower():
            return jsonify({"error": "YouTube blocked the request. Try refreshing your cookies.txt."}), 403
        return jsonify({"error": f"Download failed: {msg}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[OK] Transcript server running at http://localhost:{port}")
    if os.path.isfile(COOKIES_FILE):
        print("[OK] cookies.txt found - YouTube auth enabled")
    else:
        print("[!]  cookies.txt not found - set YOUTUBE_COOKIES env var or place cookies.txt next to server.py")
    if FFMPEG_PATH:
        print(f"[OK] FFmpeg found at: {FFMPEG_PATH} - HD/4K downloads enabled")
    else:
        print("[!]  FFmpeg not found - downloads limited to 720p progressive streams")
    app.run(host="0.0.0.0", port=port, debug=False)
