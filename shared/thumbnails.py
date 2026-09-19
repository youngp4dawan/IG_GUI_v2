"""
Video Thumbnail Extractor
==========================
Extract first frame dari video sebagai thumbnail.
Cache di data/thumbnails/ supaya tidak extract ulang.
"""
import os
import shutil
import hashlib
import subprocess

from shared.paths import DATA_DIR


CACHE_DIR = os.path.join(DATA_DIR, "thumbnails")
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _get_cache_path(video_path):
    """Generate cache path berdasarkan video path + mtime + size."""
    try:
        st = os.stat(video_path)
        key = f"{video_path}_{st.st_mtime}_{st.st_size}"
        h = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
        return os.path.join(CACHE_DIR, f"{h}.jpg")
    except Exception:
        return None


def extract_thumbnail(video_path, time_offset=1.0, size=120):
    """
    Extract frame dari video jadi thumbnail.
    Return path ke JPG thumbnail, atau None kalau gagal.

    Args:
        video_path: path video
        time_offset: detik ke berapa frame diambil (default 1s)
        size: ukuran square thumbnail (default 120x120)
    """
    if not FFMPEG_AVAILABLE:
        return None

    if not os.path.exists(video_path):
        return None

    cache_path = _get_cache_path(video_path)
    if not cache_path:
        return None

    # Cache hit
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path

    os.makedirs(CACHE_DIR, exist_ok=True)

    try:
        vf = f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}"

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(time_offset),
            "-i", video_path,
            "-vframes", "1",
            "-vf", vf,
            "-q:v", "5",
            cache_path,
        ]

        # Hide ffmpeg window on Windows
        creation_flags = 0x08000000 if os.name == "nt" else 0

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=20,
            creationflags=creation_flags,
        )

        if result.returncode == 0 and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return cache_path

    except Exception:
        pass

    return None


def clear_cache():
    """Hapus semua cached thumbnails."""
    try:
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        return True
    except Exception:
        return False


def cache_size_mb():
    """Return ukuran cache dalam MB."""
    if not os.path.exists(CACHE_DIR):
        return 0.0
    total = 0
    for root, _, files in os.walk(CACHE_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total / (1024 * 1024)