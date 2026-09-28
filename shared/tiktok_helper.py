"""
shared/tiktok_helper.py
Helper untuk TikTok: extract sec_uid, cache, dan resolve URL.
"""
import sqlite3
import yt_dlp
from shared.ytdlp_opts import tiktok_opts
from shared.logger import setup_logging

logger = setup_logging(__name__)


def ensure_tiktok_users_table(db_path: str):
    """Buat tabel cache sec_uid kalau belum ada."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tiktok_users (
                username TEXT PRIMARY KEY,
                sec_uid TEXT,
                channel_id TEXT,
                last_success TIMESTAMP,
                fail_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def get_cached_secuid(db_path: str, username: str) -> str | None:
    """Ambil sec_uid dari cache."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT sec_uid FROM tiktok_users WHERE username = ?",
            (username,)
        ).fetchone()
        return row[0] if row else None


def save_secuid(db_path: str, username: str, sec_uid: str, channel_id: str = None):
    """Simpan sec_uid ke cache."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO tiktok_users (username, sec_uid, channel_id, last_success, fail_count)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)
            ON CONFLICT(username) DO UPDATE SET
                sec_uid = excluded.sec_uid,
                channel_id = excluded.channel_id,
                last_success = CURRENT_TIMESTAMP,
                fail_count = 0
        """, (username, sec_uid, channel_id))
        conn.commit()


def extract_secuid_from_video(video_url: str) -> tuple[str | None, str | None]:
    """
    Extract sec_uid (channel_id) dari URL video TikTok.
    Return: (sec_uid, channel_id) atau (None, None) kalau gagal.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "impersonate": tiktok_opts().get("impersonate"),
        "skip_download": True,
    }
    if tiktok_opts().get("cookiefile"):
        opts["cookiefile"] = tiktok_opts()["cookiefile"]
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False, process=False)
            if info:
                # TikTok pakai 'channel_id' untuk sec_uid dan 'uploader_id' untuk username
                sec_uid = info.get("channel_id")
                channel_id = info.get("channel_id")
                return sec_uid, channel_id
    except Exception as e:
        logger.warning(f"[tiktok] Gagal extract sec_uid dari {video_url}: {e}")
    return None, None


def parse_username_from_url(url: str) -> str | None:
    """
    Extract username dari URL TikTok profile.
    Contoh: https://www.tiktok.com/@momona.1012 → 'momona.1012'
    """
    import re
    match = re.search(r"tiktok\.com/@([^/?]+)", url)
    return match.group(1) if match else None