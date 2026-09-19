"""TikTok downloader via yt-dlp (highest resolution + no watermark + thumbnail + multi-user)."""
import os
import re
import shutil
import subprocess
import threading

from shared.paths import DOWNLOAD_TIKTOK, TIKTOK_COOKIES, DATA_TIKTOK
from shared.utils import ensure_dirs
from tiktok.config import TikTokConfig

YTDLP_AVAILABLE = shutil.which("yt-dlp") is not None

ARCHIVE_DIR = os.path.join(DATA_TIKTOK, "archive")

SKIP_PATTERNS = [
    "IP address is blocked",
    "This video is unavailable",
    "Video unavailable",
    "not available in your country",
    "This post is unavailable",
    "HTTP Error 404",
    "Video currently unavailable",
]


class TikTokDownloader:

    # ══════════════════════════════════════════════════════
    # URL NORMALIZATION
    # ══════════════════════════════════════════════════════
    @staticmethod
    def normalize_url(s):
        s = s.strip()
        if not s:
            return s
        # buang query & trailing slash
        s = s.split("?")[0].rstrip("/")
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if s.startswith("@"):
            return f"https://www.tiktok.com/{s}"
        return f"https://www.tiktok.com/@{s}"

    # ══════════════════════════════════════════════════════
    # MULTI-USER PARSING
    # ══════════════════════════════════════════════════════
    @staticmethod
    def parse_multiple(text):
        """
        Parse input multiple user/URL.
        Support separator: newline, koma, titik-koma, spasi, pipe (|)
        Contoh:
            @user1, @user2
            @user1
            @user2
            https://tiktok.com/@user1 ; user2 | user3
        Return: list of unique URLs (normalized).
        """
        if not text:
            return []

        parts = re.split(r"[\n,;|\s]+", text.strip())

        seen = set()
        urls = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            try:
                url = TikTokDownloader.normalize_url(p)
            except Exception:
                continue
            if not url:
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    # ══════════════════════════════════════════════════════
    # ARCHIVE MANAGEMENT
    # ══════════════════════════════════════════════════════
    @staticmethod
    def extract_username(url):
        m = re.search(r"tiktok\.com/@([A-Za-z0-9_.]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/video/(\d+)", url)
        if m:
            return f"_video_{m.group(1)}"
        return "_misc"

    @staticmethod
    def get_archive_path(url):
        ensure_dirs(ARCHIVE_DIR)
        return os.path.join(ARCHIVE_DIR, f"{TikTokDownloader.extract_username(url)}.txt")

    @staticmethod
    def get_archive_info(url):
        path = TikTokDownloader.get_archive_path(url)
        if not os.path.exists(path):
            return False, 0, path
        try:
            with open(path, "r", encoding="utf-8") as f:
                count = len([l for l in f if l.strip()])
            return True, count, path
        except Exception:
            return False, 0, path

    @staticmethod
    def reset_archive(url):
        path = TikTokDownloader.get_archive_path(url)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False

    # ══════════════════════════════════════════════════════
    # BUILD COMMAND
    # ══════════════════════════════════════════════════════
    @staticmethod
    def build_cmd(url, quality="hd", use_archive=True):
        """
        Format priority:
        - NO WATERMARK (h264_*, h265_*, bytevc1_* — bukan download/download_hd)
        - RESOLUSI TERTINGGI dulu (1080p > 720p)
        - Codec apapun (h264/h265/bytevc1) — yang penting no watermark
        """
        tpl = os.path.join(DOWNLOAD_TIKTOK, "%(uploader)s", "%(id)s_%(title).60s.%(ext)s")

        if quality == "hd":
            fmt = (
                "h264_1080p/h265_1080p/bytevc1_1080p/"
                "h264_720p/h265_720p/bytevc1_720p/"
                "h264_540p/h265_540p/bytevc1_540p/"
                "h264_360p/h265_360p/bytevc1_360p/"
                "bestvideo*+bestaudio/"
                "b[height<=1080]/"
                "b"
            )
            fs = "res:1080,fps"

        elif quality == "sd":
            fmt = (
                "h264_720p/h265_720p/bytevc1_720p/"
                "h264_540p/h265_540p/bytevc1_540p/"
                "h264_360p/h265_360p/bytevc1_360p/"
                "b[height<=720]/"
                "b"
            )
            fs = "res:720"

        else:
            fmt, fs = "b", "res"

        cmd = [
            "yt-dlp",
            "--impersonate", "chrome-131",
            "--format", fmt,
            "--format-sort", fs,
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
        ]

        if use_archive:
            cmd.extend(["--download-archive", TikTokDownloader.get_archive_path(url)])

        if os.path.exists(TIKTOK_COOKIES):
            cmd.extend(["--cookies", TIKTOK_COOKIES])

        cmd.append(url)
        return cmd

    @staticmethod
    def _is_skip_error(line):
        return any(p.lower() in line.lower() for p in SKIP_PATTERNS)

    # ══════════════════════════════════════════════════════
    # DOWNLOAD (single URL)
    # ══════════════════════════════════════════════════════
    @staticmethod
    def download(url, quality="hd", use_archive=True,
                 stop_event=None, on_log=None, on_progress=None):
        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda p, m: None)

        if not YTDLP_AVAILABLE:
            on_log("❌ yt-dlp tidak terinstall")
            return False

        ensure_dirs(DOWNLOAD_TIKTOK)

        if use_archive:
            exists, count, _ = TikTokDownloader.get_archive_info(url)
            if exists and count > 0:
                on_log(f"📚 Archive: {count} video sudah pernah didownload")
                on_log(f"   → Video lama akan otomatis di-skip")
            else:
                on_log(f"📚 Archive baru")

        config = TikTokConfig()
        ok, msg = config.generate_netscape()
        on_log(f"🍪 Cookies: {msg}" if ok else f"⚠️  {msg}")

        cmd = TikTokDownloader.build_cmd(url, quality, use_archive=use_archive)
        on_log("🔧 Running yt-dlp...")
        on_log("🔍 Format: highest resolution, no watermark")
        on_log("")

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

            stats = {
                "success": 0,
                "skipped_archive": 0,
                "skipped_error": 0,
                "failed": 0,
                "thumbnails": 0,
            }

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

                m_item = re.search(r"Downloading item (\d+) of (\d+)", line)
                if m_item:
                    on_log(f"\n📹 Video {m_item.group(1)}/{m_item.group(2)}")
                    continue

                if "writing video thumbnail" in low or \
                   "downloading thumbnail" in low or \
                   "[thumbnailsconvertor]" in low:
                    stats["thumbnails"] += 1
                    on_log(f"   🖼️  Thumbnail")
                    continue

                if "has already been recorded in the archive" in low or \
                   "has already been downloaded" in low:
                    stats["skipped_archive"] += 1
                    on_log(f"   ⏭️  Sudah pernah didownload")
                    continue

                if "[download] 100%" in line:
                    stats["success"] += 1
                    on_log(f"   ✅ Selesai")
                    continue

                if "error" in low:
                    if TikTokDownloader._is_skip_error(line):
                        stats["skipped_error"] += 1
                        reason = "IP blocked"
                        if "unavailable" in low or "404" in low:
                            reason = "unavailable/deleted"
                        elif "not available in your country" in low:
                            reason = "region-locked"
                        on_log(f"   ⏭️  SKIP: {reason}")
                    else:
                        stats["failed"] += 1
                        on_log(f"   ❌ ERROR: {line[:150]}")
                    continue

                if "destination" in low:
                    on_log(f"   💾 {line[:150]}")

            p.wait()

            on_log("")
            on_log("=" * 55)
            on_log("📊 SUMMARY")
            on_log("=" * 55)
            on_log(f"   ✅ Berhasil:          {stats['success']}")
            on_log(f"   🖼️  Thumbnails:       {stats['thumbnails']}")
            on_log(f"   ⏭️  Skip (sudah ada): {stats['skipped_archive']}")
            on_log(f"   ⏭️  Skip (error):     {stats['skipped_error']}")
            on_log(f"   ❌ Gagal:            {stats['failed']}")
            on_log("=" * 55)

            if use_archive:
                exists, total, _ = TikTokDownloader.get_archive_info(url)
                if exists:
                    on_log(f"📚 Total archive: {total} video")

            total_done = stats["success"] + stats["skipped_archive"] + stats["skipped_error"]
            success = total_done > 0 or stats["failed"] == 0

            if stats["success"] == 0 and stats["skipped_archive"] > 0:
                on_log("🎉 Semua video sudah pernah didownload sebelumnya!")
            elif stats["success"] > 0:
                on_log(f"🎉 Selesai! {stats['success']} video + {stats['thumbnails']} thumbnails")
            else:
                on_log("⚠️  Tidak ada video yang diproses")

            on_progress(1.0, "Selesai")
            return success

        except KeyboardInterrupt:
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass
            on_log("⏸️ Dihentikan")
            return False
        except Exception as e:
            on_log(f"❌ Error: {str(e)[:200]}")
            return False

    # ══════════════════════════════════════════════════════
    # DOWNLOAD MULTIPLE USERS
    # ══════════════════════════════════════════════════════
    @staticmethod
    def download_multiple(users_text, quality="hd", use_archive=True,
                          stop_event=None, on_log=None, on_progress=None):
        """
        Download multiple user/URL sekaligus.
        - users_text : string mentah dari input (multi-baris / koma / dll)
        - on_log     : callback (message:str)
        - on_progress: callback (progress_global:float 0..1, message:str)
        """
        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda p, m: None)

        if not YTDLP_AVAILABLE:
            on_log("❌ yt-dlp tidak terinstall")
            return False

        urls = TikTokDownloader.parse_multiple(users_text)
        if not urls:
            on_log("❌ Tidak ada user/URL valid")
            return False

        total = len(urls)
        on_log("=" * 55)
        on_log(f"🎯 Multi-user mode: {total} target")
        for i, u in enumerate(urls, 1):
            on_log(f"   {i}. {u}")
        on_log("=" * 55)

        results = []
        for idx, url in enumerate(urls, 1):
            if stop_event.is_set():
                on_log("⏸️ Dihentikan oleh user")
                break

            # progress global diskalakan per target
            base = (idx - 1) / total
            span = 1 / total

            def local_progress(p, msg, _base=base, _span=span, _idx=idx, _total=total):
                on_progress(_base + p * _span, f"[{_idx}/{_total}] {msg}")

            on_log("")
            on_log("─" * 55)
            on_log(f"▶️  [{idx}/{total}] Mulai: {url}")
            on_log("─" * 55)

            try:
                ok = TikTokDownloader.download(
                    url,
                    quality=quality,
                    use_archive=use_archive,
                    stop_event=stop_event,
                    on_log=on_log,
                    on_progress=local_progress,
                )
            except Exception as e:
                ok = False
                on_log(f"❌ Exception: {str(e)[:200]}")

            results.append((url, ok))
            on_log(f"{'✅' if ok else '❌'} Selesai [{idx}/{total}]: {url}")

        # ── summary akhir ──
        ok_count = sum(1 for _, ok in results if ok)
        fail_count = len(results) - ok_count

        on_log("")
        on_log("=" * 55)
        on_log("📊 MULTI-USER SUMMARY")
        on_log("=" * 55)
        on_log(f"   ✅ Berhasil : {ok_count}/{len(results)}")
        on_log(f"   ❌ Gagal    : {fail_count}/{len(results)}")
        if fail_count:
            on_log("   Detail gagal:")
            for url, ok in results:
                if not ok:
                    on_log(f"      • {url}")
        on_log("=" * 55)

        on_progress(1.0, "Multi-user selesai")
        return ok_count > 0