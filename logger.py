# -*- coding: utf-8 -*-
"""
Logging module for CNPJ extractor bot.
Centralizes logger configuration and provides get_logger for application modules.
"""

import logging
import os

# Logger name for the application
LOGGER_NAME = "hitss_billing"

# Format for console (can include emojis in messages; format is neutral)
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
# Format for file (machine-friendly, no emojis in format)
FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Default level if not in config yet (avoids import cycle at module load)
_default_level = os.environ.get("LOG_LEVEL", "INFO").upper()
_default_file = os.environ.get("LOG_FILE", "")


def _get_config():
    """Lazy import config to read LOG_LEVEL and LOG_FILE."""
    try:
        from config import LOG_LEVEL, LOG_FILE
        return LOG_LEVEL, LOG_FILE
    except ImportError:
        return _default_level, _default_file


def _setup_logger():
    """Configure the root application logger and its handlers."""
    root = logging.getLogger(LOGGER_NAME)
    if root.handlers:
        return root

    level_str, log_file = _get_config()
    level = getattr(logging, level_str, logging.INFO)
    root.setLevel(level)

    # Console (stderr)
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(console)

    # Optional file
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
            root.addHandler(file_handler)
        except OSError:
            root.warning("Could not open log file %s, file logging disabled", log_file)

    return root


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given module name.
    Use __name__ in each module: logger = get_logger(__name__).
    """
    _setup_logger()
    if name.startswith(LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
