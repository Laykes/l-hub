"""Centralized logging configuration for L-Hub."""

import logging
import sys
from typing import Optional

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
DEFAULT_LOG_LEVEL = logging.WARNING


def configure_logging(debug: bool = False, level: Optional[int] = None) -> logging.Logger:
    """Configure root and L-Hub loggers with a clean stderr format.

    Repeated calls replace only handlers managed by this function so external
    handlers (such as unittest ``assertLogs``) are preserved.
    """
    target_level = level if level is not None else (logging.DEBUG if debug else DEFAULT_LOG_LEVEL)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_lhub_managed", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.NOTSET)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    setattr(handler, "_lhub_managed", True)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    lhub_logger = logging.getLogger("lhub")
    lhub_logger.setLevel(target_level)
    return lhub_logger
