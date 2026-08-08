# YouTube Content Downloader & Transcript Generator 🚀

A modern, fast, and responsive single-page web application to generate YouTube transcripts, download high-quality videos (up to 4K), and extract video thumbnails with 1-click simplicity.

---

## Features ✨

- **📜 YouTube Transcript Generator**:
  - Extract full transcripts in seconds (Plain text or Timestamps view).
  - Built-in live search within transcripts.
  - 1-click **Copy to Clipboard** and **Download as .txt**.
  - Supports auto-generated and manual captions.

- **🎥 YouTube Video Downloader**:
  - Download videos in various qualities (4K, 2K, 1080p HD, 720p, etc.) or **Audio Only (M4A/MP3)** using FFmpeg.
  - Includes **Video Preview** with an embedded YouTube player.

- **🖼️ High-Res Thumbnail Downloader**:
  - Instantly extract the highest resolution thumbnail image (`1280x720`).
  - 1-click download directly to your computer.

- **📱 Fully Responsive**:
  - Seamless modern dark UI built with fluid typography and CSS design tokens.
  - Fully responsive across mobile, tablet, laptop, and desktop screens.

---

## Setup & Running Locally 🛠️

### Prerequisites
- Python 3.9+
- [FFmpeg](https://www.ffmpeg.org/) (for 1080p / 4K video merging)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Add YouTube Cookies (Required for YouTube Auth)
YouTube blocks automated requests. Export your YouTube cookies once:
1. Install a browser extension like **Get cookies.txt LOCALLY** ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) / [Firefox](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)).
2. Log into `youtube.com` and export your cookies as `cookies.txt`.
3. Place `cookies.txt` in the root folder of this project.

### 3. Start the Server
```bash
python server.py
```

Open **http://localhost:5000** in your web browser.
