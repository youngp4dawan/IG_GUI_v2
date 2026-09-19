"""
Shared Paths — Single source of truth untuk semua path project.
==============================================================
Struktur folder:
    IG_GUI_v2/
    |-- Download/                 # hasil download
    |   |-- instagram/
    |   |-- tiktok/
    |   |-- youtube/
    |   |-- facebook/
    |   `-- twitter/
    |-- data/                     # cache, cookies, archive
    |   |-- instagram/
    |   |-- tiktok/
    |   |-- youtube/
    |   |-- facebook/
    |   `-- twitter/
    |-- config/                   # config JSON (cookies, settings)
    |   |-- instagram.json
    |   |-- tiktok.json
    |   |-- youtube.json
    |   |-- facebook.json
    |   `-- twitter.json
    `-- logs/                     # log files
"""
import os
import sys


# ============================================================
# ROOT DIRECTORIES
# ============================================================

# BASE_DIR = folder parent dari folder `shared/`
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOWNLOAD_ROOT = os.path.join(BASE_DIR, "Download")
DATA_ROOT     = os.path.join(BASE_DIR, "data")
CONFIG_ROOT   = os.path.join(BASE_DIR, "config")
LOGS_ROOT     = os.path.join(BASE_DIR, "logs")


# ============================================================
# LOG FILES
# ============================================================

LOG_FILE  = os.path.join(LOGS_ROOT, "app.log")
DEBUG_LOG = os.path.join(LOGS_ROOT, "debug.log")


# ============================================================
# INSTAGRAM
# ============================================================

DOWNLOAD_INSTAGRAM   = os.path.join(DOWNLOAD_ROOT, "instagram")
DATA_INSTAGRAM       = os.path.join(DATA_ROOT, "instagram")
DATA_INSTAGRAM_LINKS = os.path.join(DATA_INSTAGRAM, "links")
INSTAGRAM_CONFIG     = os.path.join(CONFIG_ROOT, "instagram.json")


# ============================================================
# TIKTOK
# ============================================================

DOWNLOAD_TIKTOK = os.path.join(DOWNLOAD_ROOT, "tiktok")
DATA_TIKTOK     = os.path.join(DATA_ROOT, "tiktok")
TIKTOK_CONFIG   = os.path.join(CONFIG_ROOT, "tiktok.json")
TIKTOK_COOKIES  = os.path.join(DATA_TIKTOK, "cookies.txt")


# ============================================================
# YOUTUBE
# ============================================================

DOWNLOAD_YOUTUBE       = os.path.join(DOWNLOAD_ROOT, "youtube")
DATA_YOUTUBE           = os.path.join(DATA_ROOT, "youtube")
YOUTUBE_CONFIG         = os.path.join(CONFIG_ROOT, "youtube.json")
YOUTUBE_UPLOAD_HISTORY = os.path.join(DATA_YOUTUBE, "upload_history.json")


# ============================================================
# FACEBOOK
# ============================================================

DOWNLOAD_FACEBOOK = os.path.join(DOWNLOAD_ROOT, "facebook")
DATA_FACEBOOK     = os.path.join(DATA_ROOT, "facebook")
FACEBOOK_CONFIG   = os.path.join(CONFIG_ROOT, "facebook.json")
FACEBOOK_COOKIES  = os.path.join(DATA_FACEBOOK, "cookies.txt")


# ============================================================
# TWITTER / X
# ============================================================

DOWNLOAD_TWITTER = os.path.join(DOWNLOAD_ROOT, "twitter")
DATA_TWITTER     = os.path.join(DATA_ROOT, "twitter")
TWITTER_CONFIG   = os.path.join(CONFIG_ROOT, "twitter.json")
TWITTER_COOKIES  = os.path.join(DATA_TWITTER, "cookies.txt")


# ============================================================
# ALL DIRS — untuk ensure_dirs() / ensure_all()
# ============================================================

ALL_DIRS = [
    DOWNLOAD_ROOT,
    DATA_ROOT,
    CONFIG_ROOT,
    LOGS_ROOT,

    # Instagram
    DOWNLOAD_INSTAGRAM,
    DATA_INSTAGRAM,
    DATA_INSTAGRAM_LINKS,

    # TikTok
    DOWNLOAD_TIKTOK,
    DATA_TIKTOK,

    # YouTube
    DOWNLOAD_YOUTUBE,
    DATA_YOUTUBE,

    # Facebook
    DOWNLOAD_FACEBOOK,
    DATA_FACEBOOK,

    # Twitter
    DOWNLOAD_TWITTER,
    DATA_TWITTER,
]


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs(*paths):
    """
    Buat folder (recursive) untuk setiap path.
    Aman dipanggil berkali-kali. Kalau gagal, print warning ke stderr
    (tidak raise, biar tidak breaking flow).
    """
    for p in paths:
        if not p:
            continue
        try:
            os.makedirs(p, exist_ok=True)
        except Exception as e:
            print(f"[paths] Warning: gagal buat folder '{p}': {e}",
                  file=sys.stderr)


def ensure_all():
    """Buat semua folder standar dari ALL_DIRS."""
    ensure_dirs(*ALL_DIRS)


def get_safe_path(*parts):
    """Gabung path & normalkan."""
    return os.path.normpath(os.path.join(*parts))