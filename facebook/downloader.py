"""
Facebook Video Downloader
==========================
Download video Facebook pakai yt-dlp + cookies.
Fallback ke fb-video-downloader kalau yt-dlp gagal.
"""
import os
import re
import shutil
import subprocess
import threading
import time                          # ← TAMBAH INI
from shared.paths import DOWNLOAD_FACEBOOK, FACEBOOK_COOKIES
from shared.utils import ensure_dirs
from facebook.config import FacebookConfig

YTDLP_AVAILABLE = shutil.which("yt-dlp") is not None

SKIP_PATTERNS = [
    "This content isn't available",
    "not available at the moment",
    "This video is private",
    "HTTP Error 404",
    "Cannot parse data",
    "login required",
]


class FacebookDownloader:

    @staticmethod
    def normalize_url(url):
        """Bersihkan URL Facebook."""
        url = url.strip().split("?")[0].rstrip("/")
        return url

    @staticmethod
    def extract_video_id(url):
        """Extract video ID dari URL."""
        for pattern in [
            r"/videos/(\d+)",
            r"/reel/(\d+)",
            r"[?&]v=(\d+)",
            r"/watch/?\?v=(\d+)",
            r"/share/v/(\w+)",
        ]:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _is_skip_error(line):
        return any(p.lower() in line.lower() for p in SKIP_PATTERNS)

    @staticmethod
    def build_cmd(url, quality="hd"):
        """Build yt-dlp command untuk Facebook."""
        tpl = os.path.join(
            DOWNLOAD_FACEBOOK,
            "%(uploader)s",
            "%(upload_date>%Y)s",
            "%(id)s_%(title).80s.%(ext)s",
        )

        if quality == "hd":
            # ⚡ FIX: handle portrait (Reels) — filter by width ATAU height
            # Portrait 1080x1920: width=1080 ✓, height=1920 (>1080 tapi valid)
            # Landscape 1920x1080: width=1920, height=1080 ✓
            fmt = (
                "bestvideo[height<=1920][width<=1080]+bestaudio/"  # portrait HD
                "bestvideo[height<=1080][width<=1920]+bestaudio/"  # landscape HD
                "bestvideo[height<=1920]+bestaudio/"               # fallback
                "bestvideo+bestaudio/"                              # last resort
                "best"
            )
        elif quality == "sd":
            fmt = (
                "bestvideo[height<=1280][width<=720]+bestaudio/"
                "bestvideo[height<=720][width<=1280]+bestaudio/"
                "bestvideo[height<=1280]+bestaudio/"
                "bestvideo+bestaudio/"
                "best"
            )
        else:
            fmt = "best"

        cmd = [
            "yt-dlp",
            "--impersonate", "chrome-131",   # WAJIB untuk Facebook
            "--format", fmt,
            "--output", tpl,
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "--newline",
            "--progress",
            "--retries", "2",
            "--fragment-retries", "2",
            "--ignore-errors",
            "--no-abort-on-error",
            "--no-overwrites",
            "--socket-timeout", "30",
            # Facebook specific
            "--no-check-certificate",
            "--geo-bypass",
        ]

        if os.path.exists(FACEBOOK_COOKIES):
            cmd.extend(["--cookies", FACEBOOK_COOKIES])

        cmd.append(url)
        return cmd

    @staticmethod
    def download(url, quality="hd",
                 stop_event=None, on_log=None, on_progress=None):
        """
        Download 1 video Facebook.
        Return True/False.
        """
        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda p, m: None)

        if not YTDLP_AVAILABLE:
            on_log("❌ yt-dlp tidak terinstall")
            return False

        ensure_dirs(DOWNLOAD_FACEBOOK)

        # Generate cookies
        config = FacebookConfig()
        if config.is_valid():
            ok, msg = config.generate_netscape()
            on_log(f"🍪 Cookies: {msg}" if ok else f"⚠️  {msg}")
        else:
            on_log("⚠️  Cookies Facebook tidak lengkap — coba tanpa cookies")

        url = FacebookDownloader.normalize_url(url)
        cmd = FacebookDownloader.build_cmd(url, quality)

        p = None
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )

            stats = {"success": 0, "failed": 0, "skipped": 0}

            for line in p.stdout:
                if stop_event.is_set():
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    on_log("⏸️ Dihentikan")
                    return False

                line = line.rstrip()
                if not line:
                    continue
                low = line.lower()

                if "[download]" in line and "%" in line:
                    try:
                        m = re.search(r"(\d+\.?\d*)%", line)
                        if m:
                            on_progress(float(m.group(1)) / 100.0, line[:100])
                    except Exception:
                        pass
                    continue

                if "has already been downloaded" in low:
                    stats["skipped"] += 1
                    on_log("   ⏭️ Sudah ada")
                    continue

                if "[download] 100%" in line:
                    stats["success"] += 1
                    on_log("   ✅ Selesai")
                    continue

                if "error" in low:
                    if FacebookDownloader._is_skip_error(line):
                        stats["skipped"] += 1
                        on_log(f"   ⏭️ SKIP: {line[:100]}")
                    else:
                        stats["failed"] += 1
                        on_log(f"   ❌ ERROR: {line[:150]}")
                    continue

                if "destination" in low:
                    on_log(f"   💾 {line[:150]}")

            p.wait()
            on_progress(1.0, "Selesai")
            return stats["success"] > 0 or stats["skipped"] > 0

        except Exception as e:
            on_log(f"❌ Exception: {str(e)[:150]}")
            return False

    @staticmethod
    def download_multiple(urls, quality="hd", delay=3.0,
                          stop_event=None, on_log=None, on_progress=None):
        """
        Download multiple video URLs.
        Args:
            urls: list of video URLs
            delay: jeda antar video (detik) — Facebook agresif rate limit
        """
        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda p, m: None)

        if not urls:
            on_log("❌ Tidak ada URL")
            return False

        total = len(urls)
        on_log("=" * 55)
        on_log(f"🎯 Facebook: {total} video")
        on_log("=" * 55)

        results = []
        for idx, url in enumerate(urls, 1):
            if stop_event.is_set():
                break

            base = (idx - 1) / total
            span = 1 / total

            def local_progress(p, msg, _base=base, _span=span, _idx=idx, _total=total):
                on_progress(_base + p * _span, f"[{_idx}/{_total}] {msg}")

            on_log("")
            on_log("─" * 55)
            on_log(f"▶️  [{idx}/{total}] {url}")
            on_log("─" * 55)

            ok = FacebookDownloader.download(
                url, quality=quality,
                stop_event=stop_event,
                on_log=on_log,
                on_progress=local_progress,
            )
            results.append((url, ok))

            if idx < total and not stop_event.is_set():
                on_log(f"   ⏸️ Delay {delay:.0f}s...")
                time.sleep(delay)

        ok_count = sum(1 for _, ok in results if ok)
        on_log("")
        on_log("=" * 55)
        on_log(f"📊 Selesai: {ok_count}/{total} berhasil")
        on_log("=" * 55)

        on_progress(1.0, "Facebook selesai")
        return ok_count > 0