"""Logging setup: concise console output plus a timestamped file per run."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from .paths import LOGS_DIR

_LOGGER_NAME = "mi2_aio"


def configure(level: str = "INFO", *, log_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if logger.handlers:
        return logger

    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    )
    logger.addHandler(console)

    logfile = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    file_handler = logging.FileHandler(logfile, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)
    logger.debug("Logging to %s", logfile)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
