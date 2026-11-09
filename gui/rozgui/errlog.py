"""Shared error log for the GUI: gui/gui-error.log (rotating, UTF-8).

pythonw has no console, so every handled error is written here instead of
being dropped. `warn_once` keeps errors from the 1-second poll loop from
flooding the file.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Final

LOG_PATH: Final[str] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gui-error.log')
_MAX_BYTES: Final[int] = 512_000
_WARNED_CAP: Final[int] = 500

_warned: set[str] = set()


def _build_logger() -> logging.Logger:
    logger = logging.getLogger('rozgui')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler: logging.Handler
    try:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=_MAX_BYTES, backupCount=2, encoding='utf-8')
    except OSError:
        # Folder not writable: fall back to stderr (None under pythonw; logging copes with that).
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(module)s: %(message)s'))
    logger.addHandler(handler)
    return logger


log: Final[logging.Logger] = _build_logger()


def warn_once(key: str, msg: str, *args: object) -> None:
    """Log a warning only the first time `key` is seen (for repeating poll errors)."""
    if key in _warned:
        return
    if len(_warned) >= _WARNED_CAP:
        _warned.clear()
    _warned.add(key)
    log.warning(msg, *args, stacklevel=2)   # attribute the record to the caller's module
