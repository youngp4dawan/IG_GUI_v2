"""TikTok downloader via yt-dlp (highest resolution + no watermark + thumbnail + multi-user)."""
import os
import re
import json
import time
import glob
import shutil
import subprocess
import threading

from shared.paths import DOWNLOAD_TIKTOK, TIKTOK_COOKIES, DATA_TIKTOK
from shared.utils import ensure_dirs
from tiktok.config import TikTokConfig

# [PATCH #2] Impersonate target bisa di-override via env tanpa edit kode.
# Contoh: set TIKTOK_IMPERSONATE=chrome-132 kalau chrome-131 mulai diblokir.
# Cek target tersedia: yt-dlp --list-impersonate-targets
IMPERSONATE_TARGET = os.environ.get("TIKTOK_IMPERSONATE", "chrome-131")

# [OPTIMASI] Batas maksimum video yang dicek untuk deteksi "sudah ada".
# Nilai lebih kecil = lebih cepat, tapi risiko miss video baru kalau user upload
# banyak antara 2 run. Rekomendasi:
#   - Run harian: 10
#   - Run mingguan: 20 (default)
#   - Run bulanan: 50
PLAYLIST_END = int(os.environ.get("TIKTOK_PLAYLIST_END", "20"))

YTDLP_AVAILABLE = shutil.which("yt-dlp") is not None

ARCHIVE_DIR = os.path.join(DATA_TIKTOK, "archive")
SEC_UID_CACHE = os.path.join(DATA_TIKTOK, "sec_uid_cache.json")

SKIP_PATTERNS = [
    "IP address is blocked",
    "This video is unavailable",
    "Video unavailable",
    "not available in your country",
    "This post is unavailable",
    "HTTP Error 404",
    "Video currently unavailable",
]

# [PATCH #3] Error spesifik yang menandakan bot detection → trigger retry
SEC_UID_ERROR_MARKERS = [
    "unable to extract secondary user id",
    "unable to extract primary user id",
]


# ══════════════════════════════════════════════════════════
# SEC_UID CACHE HELPERS
# ══════════════════════════════════════════════════════════

def _load_sec_uid_cache():
    """Load mapping username → sec_uid. Return {} kalau tidak ada."""
    try:
        if os.path.exists(SEC_UID_CACHE):
            with open(SEC_UID_CACHE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


# [PATCH #1] Atomic write untuk hindari corrupt saat crash
def _save_sec_uid_cache(cache):
    """Simpan cache dengan atomic write (tmp + rename)."""
    try:
        ensure_dirs(os.path.dirname(SEC_UID_CACHE))
        tmp = SEC_UID_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        os.replace(tmp, SEC_UID_CACHE)
        return True
    except Exception:
        return False


def _extract_username_from_url(url):
    """Ambil username TikTok dari URL profile. Return None kalau tidak match."""
    m = re.search(r"tiktok\.com/@([A-Za-z0-9_.]+)", url)
    return m.group(1) if m else None


def _resolve_effective_url(url):
    """
    Kalau username ada di sec_uid cache, return 'tiktokuser:SEC_UID'.
    Kalau tidak, return url asli.
    """
    username = _extract_username_from_url(url)
    if username:
        cache = _load_sec_uid_cache()
        if username in cache:
            return f"tiktokuser:{cache[username]}", username
    return url, username


# [PATCH #1] Auto-populate sec_uid cache dari info.json hasil yt-dlp
def _find_channel_id_from_recent_info(download_start_ts):
    """
    Scan file .info.json yang dibuat setelah download_start_ts,
    return channel_id (sec_uid) dari file terbaru yang valid.
    """
    try:
        pattern = os.path.join(DOWNLOAD_TIKTOK, "**", "*.info.json")
        files = glob.glob(pattern, recursive=True)
        files = [f for f in files if os.path.getmtime(f) >= download_start_ts]
        files.sort(key=os.path.getmtime, reverse=True)

        for path in files[:20]:  # batasi 20 file terbaru
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    info = json.load(fh)
                cid = info.get("channel_id")
                if cid and len(str(cid)) >= 15:
                    return str(cid)
            except Exception:
                continue
    except Exception:
        pass
    return None


# [PATCH #1] Simpan sec_uid ke cache kalau belum ada / berbeda
def _maybe_cache_sec_uid(username, download_start_ts, on_log):
    """Cek apakah perlu update cache sec_uid. Dipanggil setelah download."""
    if not username or username.startswith("_") or username.startswith("@"):
        return
    try:
        cache = _load_sec_uid_cache()
        if username in cache:
            return  # sudah ada, skip (hindari I/O tiap download)
        cid = _find_channel_id_from_recent_info(download_start_ts)
        if cid:
            cache[username] = cid
            if _save_sec_uid_cache(cache):
                on_log(f"   💾 Cached sec_uid untuk @{username}: {cid[:20]}...")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# DOWNLOADER
# ══════════════════════════════════════════════════════════

class TikTokDownloader:

    # ══════════════════════════════════════════════════════
    # URL NORMALIZATION
    # ══════════════════════════════════════════════════════
    @staticmethod
    def normalize_url(s):
        s = s.strip()
        if not s:
            return s
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
        m = re.search(r"tiktokuser:([A-Za-z0-9_.\-]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/video/(\d+)", url)
        if m:
            return f"_video_{m.group(1)}"
        return "_misc"

    @staticmethod
    def get_archive_path(url, username_hint=None):
        """
        Path archive. username_hint memastikan archive tetap konsisten
        meskipun URL sudah di-resolve ke format tiktokuser:SEC_UID.
        """
        ensure_dirs(ARCHIVE_DIR)
        name = username_hint or TikTokDownloader.extract_username(url)
        return os.path.join(ARCHIVE_DIR, f"{name}.txt")

    @staticmethod
    def get_archive_info(url, username_hint=None):
        path = TikTokDownloader.get_archive_path(url, username_hint)
        if not os.path.exists(path):
            return False, 0, path
        try:
            with open(path, "r", encoding="utf-8") as f:
                count = len([l for l in f if l.strip()])
            return True, count, path
        except Exception:
            return False, 0, path

    @staticmethod
    def reset_archive(url, username_hint=None):
        path = TikTokDownloader.get_archive_path(url, username_hint)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False

    # [PATCH #6] Deteksi apakah URL adalah playlist user atau single video
    @staticmethod
    def _is_single_video(url):
        """True kalau URL adalah single video (/video/ID)."""
        return "/video/" in url and "tiktokuser:" not in url

    # ══════════════════════════════════════════════════════
    # BUILD COMMAND
    # ══════════════════════════════════════════════════════
    @staticmethod
    def build_cmd(url, quality="hd", use_archive=True, username_hint=None):
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

        is_single = TikTokDownloader._is_single_video(url)

        cmd = [
            "yt-dlp",
            # [PATCH #2] Pakai IMPERSONATE_TARGET dari env
            "--impersonate", IMPERSONATE_TARGET,
            "--format", fmt,
            "--format-sort", fs,
            "--output", tpl,
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--merge-output-format", "mp4",
            # [PATCH #4] Tanpa --no-warnings biar warning penting tetap muncul,
            # baris [debug] difilter di parser output
            "--newline",
            "--progress",
            "--retries", "3",                      # [PATCH #5] naik dari 2
            "--fragment-retries", "3",             # [PATCH #5] naik dari 2
            "--extractor-retries", "5",            # [PATCH #5] BARU
            "--sleep-requests", "2",               # [PATCH #5] BARU — hindari rate limit
            "--socket-timeout", "30",
            "--no-overwrites",
        ]

        # [PATCH #6] Hanya pakai --ignore-errors untuk playlist (user),
        #           BUKAN untuk single video — biar error tidak disamarkan.
        if not is_single:
            cmd.extend([
                "--ignore-errors",
                "--no-abort-on-error",
                # ⚡ [OPTIMASI] STOP begitu ketemu video yang sudah di archive.
                #    Karena urutan TikTok baru→lama, ini bikin cek cuma beberapa video saja.
                "--break-on-existing",
                # ⚡ [OPTIMASI] Proses entry sambil jalan, jangan tunggu full extraction.
                "--lazy-playlist",
                # ⚡ [OPTIMASI] Safety net: minimal cek N video teratas.
                #    Ini juga jadi cap fetch page — cegah yt-dlp buka puluhan page.
                "--playlist-end", str(PLAYLIST_END),
            ])

        if use_archive:
            cmd.extend([
                "--download-archive",
                TikTokDownloader.get_archive_path(url, username_hint)
            ])

        if os.path.exists(TIKTOK_COOKIES):
            cmd.extend(["--cookies", TIKTOK_COOKIES])

        cmd.append(url)
        return cmd

    @staticmethod
    def _is_skip_error(line):
        return any(p.lower() in line.lower() for p in SKIP_PATTERNS)

    # [PATCH #3] Deteksi error bot detection untuk trigger retry
    @staticmethod
    def _is_sec_uid_error(line):
        low = line.lower()
        return any(m in low for m in SEC_UID_ERROR_MARKERS)

    # ══════════════════════════════════════════════════════
    # DOWNLOAD (single URL)
    # ══════════════════════════════════════════════════════
    @staticmethod
    def download(url, quality="hd", use_archive=True,
                 stop_event=None, on_log=None, on_progress=None,
                 _retry=0):
        """
        Download TikTok user / single video.

        _retry: internal flag (0 = percobaan pertama, 1 = retry via sec_uid cache)
        """
        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda p, m: None)

        if not YTDLP_AVAILABLE:
            on_log("❌ yt-dlp tidak terinstall")
            return False

        ensure_dirs(DOWNLOAD_TIKTOK)

        # Catat timestamp awal download untuk deteksi info.json baru
        download_start_ts = time.time()  # [PATCH #1]

        # ⚡ Resolve effective URL (sec_uid cache)
        effective_url, username = _resolve_effective_url(url)

        if use_archive:
            exists, count, _ = TikTokDownloader.get_archive_info(effective_url, username)
            if exists and count > 0:
                on_log(f"📚 Archive: {count} video sudah pernah didownload")
                on_log(f"   → Video lama akan otomatis di-skip")
            else:
                on_log(f"📚 Archive baru")

        config = TikTokConfig()
        ok, msg = config.generate_netscape()
        on_log(f"🍪 Cookies: {msg}" if ok else f"⚠️  {msg}")

        if effective_url != url:
            on_log(f"   🎯 Pakai sec_uid cache untuk @{username}")

        if _retry > 0:
            on_log(f"   🔄 Retry attempt #{_retry}")

        cmd = TikTokDownloader.build_cmd(
            effective_url, quality,
            use_archive=use_archive,
            username_hint=username,
        )
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

            # [PATCH #3] Flag untuk retry via sec_uid cache
            sec_uid_error_seen = False

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

                # [PATCH #4] Filter baris [debug] biar tidak spam GUI
                if low.startswith("[debug]"):
                    continue

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
                    # on_log(f"   ⏭️  Sudah pernah didownload")
                    continue

                if "[download] 100%" in line:
                    stats["success"] += 1
                    on_log(f"   ✅ Selesai")
                    continue

                if "error" in low:
                    # [PATCH #3] Cek dulu apakah ini sec_uid error
                    if TikTokDownloader._is_sec_uid_error(line):
                        sec_uid_error_seen = True
                        stats["failed"] += 1
                        on_log(f"   ⚠️  Bot detection: {line[:150]}")
                        continue

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

            # [PATCH #7] Logic success lebih ketat
            if TikTokDownloader._is_single_video(url):
                success = stats["success"] > 0 and stats["failed"] == 0
            else:
                success = (
                    stats["failed"] == 0
                    and (stats["success"] > 0 or stats["skipped_archive"] > 0)
                )

            # [OPTIMASI] Kalau --break-on-existing trigger sebelum ada video baru,
            # yt-dlp exit 0 tanpa hit stats["success"] ataupun skipped_archive
            # (karena "break" bukan "skip"). Anggap ini sukses.
            if not success and stats["failed"] == 0 and not TikTokDownloader._is_single_video(url):
                if stats["success"] == 0 and stats["skipped_archive"] == 0 and stats["skipped_error"] == 0:
                    # Kemungkinan besar break-on-existing trigger sebelum hit existing
                    # → artinya tidak ada video baru. Treat as success.
                    success = True

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
                exists, total, _ = TikTokDownloader.get_archive_info(effective_url, username)
                if exists:
                    on_log(f"📚 Total archive: {total} video")

            if stats["success"] == 0 and stats["skipped_archive"] > 0:
                on_log("🎉 Semua video sudah pernah didownload sebelumnya!")
            elif stats["success"] > 0:
                on_log(f"🎉 Selesai! {stats['success']} video + {stats['thumbnails']} thumbnails")
            else:
                on_log("⚠️  Tidak ada video yang diproses")

            on_progress(1.0, "Selesai")

            # [PATCH #1] Auto-populate sec_uid cache dari info.json hasil download
            if success and username and "tiktokuser:" not in effective_url:
                _maybe_cache_sec_uid(username, download_start_ts, on_log)

            # [PATCH #3] Fallback retry: kalau kena sec_uid error dan ada cache,
            #            coba lagi pakai tiktokuser:SEC_UID.
            if not success and sec_uid_error_seen and _retry == 0 and username:
                cache = _load_sec_uid_cache()
                if username in cache:
                    on_log("")
                    on_log("🔄 Fallback: retry via cached sec_uid...")
                    return TikTokDownloader.download(
                        f"tiktokuser:{cache[username]}",
                        quality=quality,
                        use_archive=use_archive,
                        stop_event=stop_event,
                        on_log=on_log,
                        on_progress=on_progress,
                        _retry=1,
                    )
                else:
                    on_log("")
                    on_log("⚠️  Tidak ada cache sec_uid untuk fallback.")
                    on_log("   Jalankan download 1 video dari user ini dulu,")
                    on_log("   atau set TIKTOK_IID env untuk mobile API.")

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