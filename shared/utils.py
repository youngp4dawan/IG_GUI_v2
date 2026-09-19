"""Common utilities."""

import time

# Re-export dari paths — single source of truth.
# ensure_dirs() hanya ada di paths.py (dengan error handling proper).
# Tetap di-export di sini untuk backward compatibility caller lama.
from shared.paths import ensure_dirs  # noqa: F401


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


def current_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")


__all__ = ["ensure_dirs", "current_time", "USER_AGENT"]