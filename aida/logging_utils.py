import logging
import os
from typing import Optional
from .config import AidaConfig

_LOGGER: Optional[logging.Logger] = None

def setup_logging(config: AidaConfig) -> None:
    """
    Initialize AIDA's logging system. Creates a log directory if needed.
    """
    global _LOGGER

    # Prevent re-initialization
    if _LOGGER is not None:
        return

    os.makedirs(config.log_dir, exist_ok=True)
    log_path = os.path.join(config.log_dir, "aida.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    _LOGGER = logging.getLogger("AIDA")


def get_logger(name: str) -> logging.Logger:
    """
    Retrieve a logger for a given module or component.
    """
    if _LOGGER is None:
        # Fallback if logging wasn't initialized yet
        logging.basicConfig(level=logging.INFO)
    return logging.getLogger(name)
