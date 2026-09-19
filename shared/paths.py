"""
Shared Paths — Single source of truth untuk semua path project.
==============================================================
Struktur folder:
    IG_GUI_v2/
    ├── Download/                 ← hasil download
    │   ├── instagram/
    │   ├── tiktok/
    │   ├── youtube/
    │   ├── facebook/
    │   └── twitter/
    ├── data/                     ← cache, cookies, archive
    │   ├── instagram/
    │   ├── tiktok/
    │   ├── youtube/
    │   ├── facebook/
    │   └── twitter/
    ├── config/                   ← config JSON (cookies, settings)
    │   ├── instagram.json
    │   ├── tiktok.json
    │   ├── youtube.json
    │   ├── facebook.json
    │   └── twitter.json
    └── logs/                     ← log files
"""
import os

# ══════════════════════════════════════════════════════════
# ROOT DIRECTORIES
# ══════════════════════════════════════════════════════════

# BASE_DIR = folder parent dari folder `shared/`
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Folder download (semua platform)
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "Download")

# Folder data (cache, cookies, archive)
DATA_ROOT = os.path.join(BASE_DIR, "data")

# Folder config (settings JSON)
CONFIG_ROOT = os.path.join(BASE_DIR, "config")

# Folder log
LOGS_ROOT = os.path.join(BASE_DIR, "logs")


# ══════════════════════════════════════════════════════════
# LOG FILES
# ══════════════════════════════════════════════════════════

LOG_FILE = os.path.join(LOGS_ROOT, "app.log")
DEBUG_LOG = os.path.join(LOGS_ROOT, "debug.log")

# Alias — beberapa modul mungkin pakai nama berbeda
LOG_PATH = LOG_FILE


# ══════════════════════════════════════════════════════════
# INSTAGRAM
# ══════════════════════════════════════════════════════════

DOWNLOAD_INSTAGRAM = os.path.join(DOWNLOAD_ROOT, "instagram")
DATA_INSTAGRAM = os.path.join(DATA_ROOT, "instagram")
DATA_INSTAGRAM_LINKS = os.path.join(DATA_INSTAGRAM, "links")
INSTAGRAM_CONFIG = os.path.join(CONFIG_ROOT, "instagram.json")


# ══════════════════════════════════════════════════════════
# TIKTOK
# ══════════════════════════════════════════════════════════

DOWNLOAD_TIKTOK = os.path.join(DOWNLOAD_ROOT, "tiktok")
DATA_TIKTOK = os.path.join(DATA_ROOT, "tiktok")
TIKTOK_CONFIG = os.path.join(CONFIG_ROOT, "tiktok.json")
TIKTOK_COOKIES = os.path.join(DATA_TIKTOK, "cookies.txt")


# ══════════════════════════════════════════════════════════
# YOUTUBE
# ══════════════════════════════════════════════════════════

DOWNLOAD_YOUTUBE = os.path.join(DOWNLOAD_ROOT, "youtube")
DATA_YOUTUBE = os.path.join(DATA_ROOT, "youtube")
YOUTUBE_CONFIG = os.path.join(CONFIG_ROOT, "youtube.json")
YOUTUBE_UPLOAD_HISTORY = os.path.join(DATA_YOUTUBE, "upload_history.json")


# ══════════════════════════════════════════════════════════
# FACEBOOK
# ══════════════════════════════════════════════════════════

DOWNLOAD_FACEBOOK = os.path.join(DOWNLOAD_ROOT, "facebook")
DATA_FACEBOOK = os.path.join(DATA_ROOT, "facebook")
FACEBOOK_CONFIG = os.path.join(CONFIG_ROOT, "facebook.json")
FACEBOOK_COOKIES = os.path.join(DATA_FACEBOOK, "cookies.txt")


# ══════════════════════════════════════════════════════════
# TWITTER / X
# ══════════════════════════════════════════════════════════

DOWNLOAD_TWITTER = os.path.join(DOWNLOAD_ROOT, "twitter")
DATA_TWITTER = os.path.join(DATA_ROOT, "twitter")
TWITTER_CONFIG = os.path.join(CONFIG_ROOT, "twitter.json")
TWITTER_COOKIES = os.path.join(DATA_TWITTER, "cookies.txt")


# ══════════════════════════════════════════════════════════
# DATABASE (Wails media_library.db)
# ══════════════════════════════════════════════════════════

def find_media_db():
    """Return path ke media_library.db kalau ada, else None."""
    candidates = [
        os.path.join(BASE_DIR, "website-wails", "build", "bin", "media_library.db"),
        os.path.join(BASE_DIR, "build", "bin", "media_library.db"),
        os.path.join(BASE_DIR, "media_library.db"),
        os.path.join(BASE_DIR, "..", "website-wails", "build", "bin", "media_library.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None


MEDIA_DB = find_media_db() or os.path.join(
    BASE_DIR, "website-wails", "build", "bin", "media_library.db"
)


# ══════════════════════════════════════════════════════════
# ALL DIRS — untuk ensure_dirs() / ensure_all()
# ══════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def ensure_dirs(*paths):
    """Buat folder (recursive) untuk setiap path. Aman dipanggil berkali-kali."""
    for p in paths:
        if not p:
            continue
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass


def ensure_all():
    """Buat semua folder standar dari ALL_DIRS."""
    ensure_dirs(*ALL_DIRS)


def get_safe_path(*parts):
    """Gabung path & bersihkan."""
    p = os.path.join(*parts)
    return os.path.normpath(p)