"""
utils/logger.py
---------------
Centralised logging configuration for the CAD Automation Platform.

Single responsibility: set up and return a consistently formatted logger.

Usage
-----
In any module::

    from utils.logger import get_logger
    logger = get_logger(__name__)

Call ``configure_logging()`` once at application start (in app.py) to
activate the handlers.  All subsequent ``get_logger()`` calls share the
same configuration automatically because they use the standard Python
logging hierarchy.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

# Root logger name for the entire platform.
# All module loggers use ``__name__`` which places them under this hierarchy.
_ROOT_LOGGER_NAME: str = "cad_automation"

# Default log format
_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure the platform root logger with a stream handler to stdout.

    Call this **once** at application startup (e.g. the top of app.py).
    Subsequent calls are safe — handlers are not duplicated.

    Parameters
    ----------
    level:
        Logging level applied to the root platform logger.
        Defaults to ``logging.INFO``.
        Pass ``logging.DEBUG`` during development for verbose output.
    """
    root = logging.getLogger(_ROOT_LOGGER_NAME)

    # Guard: do not add a second handler if already configured
    if root.handlers:
        return

    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root.addHandler(handler)

    # Prevent log records from propagating to the root Python logger,
    # which avoids duplicate output when third-party libraries also log.
    root.propagate = False


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Return a logger that sits under the platform root logger hierarchy.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.
        If *name* already starts with the platform prefix it is used as-is;
        otherwise the prefix is prepended so all loggers share a tree.
    level:
        Optional per-logger override level.  If ``None``, the logger
        inherits from the platform root.

    Returns
    -------
    logging.Logger
    """
    if not name.startswith(_ROOT_LOGGER_NAME):
        qualified = f"{_ROOT_LOGGER_NAME}.{name}"
    else:
        qualified = name

    logger = logging.getLogger(qualified)

    if level is not None:
        logger.setLevel(level)

    return logger
