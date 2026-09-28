"""
shared/ytdlp_opts.py
Opts yt-dlp terpusat per platform.
Update di sini kalau TikTok/IG/X ubah deteksi.
"""
import os
from pathlib import Path

# === KONFIGURASI GLOBAL ===
# Update target impersonate sesuai versi Chrome terbaru yang didukung curl_cffi
# Cek: yt-dlp --list-impersonate-targets
IMPERSONATE_TARGET = "chrome-131"

# Path cookies (opsional, kalau ada)
COOKIES_FILE = Path(__file__).resolve().parent.parent / "cookies" / "tiktok_cookies.txt"

# TikTok app_info (iid) — opsional, untuk mobile API fallback
# Dapat dari localStorage TikTok atau device_id mobile app
TIKTOK_IID = os.environ.get("TIKTOK_IID", "").strip()


def base_opts() -> dict:
    """Opts dasar yang aman untuk semua platform."""
    return {
        "quiet": False,
        "no_warnings": False,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 5,
        "sleep_requests": 2,
        "sleep_interval": 1,
        "ignoreerrors": False,
        "noprogress": False,
        "consoletitle": False,
    }


def tiktok_opts(extra: dict | None = None) -> dict:
    """
    Opts untuk TikTok.
    
    WAJIB pakai impersonate — tanpa ini TikTok akan return halaman kosong
    dan error 'Unable to extract secondary user ID'.
    """
    opts = base_opts()
    opts.update({
        "impersonate": IMPERSONATE_TARGET,
        "extractor_retries": 5,
        "sleep_requests": 3,  # TikTok agresif rate limit
    })
    
    # Cookies kalau ada
    if COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)
    
    # app_info mobile API (kalau di-set)
    if TIKTOK_IID:
        opts.setdefault("extractor_args", {})["tiktok"] = {
            "app_info": TIKTOK_IID,
            "api_hostname": "api22-normal-c-useast2a.tiktokv.com",  # US region, lebih toleran
        }
    
    if extra:
        opts.update(extra)
    return opts


def instagram_opts(extra: dict | None = None) -> dict:
    """Opts untuk Instagram."""
    opts = base_opts()
    opts.update({
        "impersonate": IMPERSONATE_TARGET,
        "sleep_requests": 2,
    })
    if COOKIES_FILE.exists():
        # Kamu mungkin punya cookies IG terpisah
        ig_cookies = COOKIES_FILE.parent / "instagram_cookies.txt"
        if ig_cookies.exists():
            opts["cookiefile"] = str(ig_cookies)
    if extra:
        opts.update(extra)
    return opts


def x_opts(extra: dict | None = None) -> dict:
    """Opts untuk X / Twitter."""
    opts = base_opts()
    opts.update({
        "impersonate": IMPERSONATE_TARGET,
    })
    if extra:
        opts.update(extra)
    return opts


def generic_opts(extra: dict | None = None) -> dict:
    """Opts generic untuk platform lain."""
    opts = base_opts()
    opts.update({
        "impersonate": IMPERSONATE_TARGET,
    })
    if extra:
        opts.update(extra)
    return opts


def get_opts(platform: str, extra: dict | None = None) -> dict:
    """Dispatcher: pilih opts sesuai platform."""
    platform = (platform or "").lower()
    if platform == "tiktok":
        return tiktok_opts(extra)
    elif platform == "instagram":
        return instagram_opts(extra)
    elif platform in ("x", "twitter"):
        return x_opts(extra)
    else:
        return generic_opts(extra)