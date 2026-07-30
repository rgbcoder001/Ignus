"""Logging setup: stderr plus a rotating file the user can hand over."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(log_path: Path | None = None, *, level: int = logging.INFO) -> Path | None:
    """Configure root logging. Returns the log file path, or None if unusable.

    A failure to open the log file is never fatal — the app still runs and
    logs to stderr.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_path is None:
        return None

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        logging.getLogger(__name__).warning(
            "could not open log file %s — logging to stderr only",
            log_path,
            exc_info=True,
        )
        return None

    return log_path
