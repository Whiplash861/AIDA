from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aida.config import AidaConfig
from aida.memory.privacy import sanitize_text


class _RedactedFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return sanitize_text(super().format(record))


def setup_logging(config: AidaConfig) -> None:
    """Install bounded AIDA logging even if another library configured logging."""
    logger = logging.getLogger("aida")
    path = Path(config.log_dir) / "aida.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    for handler in logger.handlers:
        if getattr(handler, "baseFilename", None) == str(path.resolve()):
            return
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(_RedactedFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
