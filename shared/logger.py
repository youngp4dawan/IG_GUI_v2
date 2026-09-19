"""Logging setup."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from shared.paths import LOG_FILE


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger("igdownloader")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    if sys.stdout and sys.stdout.isatty():
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.setLevel(logging.WARNING)
        root.addHandler(ch)

    return root


log = logging.getLogger("igdownloader")
