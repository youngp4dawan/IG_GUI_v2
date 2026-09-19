"""Common utilities."""
import os
import time

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def current_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")
