from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from aida.config import AidaConfig

_LOGGER: Optional[logging.Logger] = None
_LOCK = threading.RLock()


def setup_logging(config: AidaConfig) -> None:
    global _LOGGER
    with _LOCK:
        if _LOGGER is not None:
            return
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)
        log_path = os.path.join(config.log_dir, "aida.log")
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        if not any(
            isinstance(handler, logging.FileHandler)
            and getattr(handler, "baseFilename", None) == os.path.abspath(log_path)
            for handler in root.handlers
        ):
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        if not any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
            for handler in root.handlers
        ):
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            root.addHandler(stream_handler)
        _LOGGER = logging.getLogger("AIDA")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
