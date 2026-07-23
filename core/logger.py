"""
╔══════════════════════════════════════════════════════════════╗
║                         PAG CORE                            ║
║                      Logging System                          ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
import sys


# ─────────────────────────────────────────────────────────────
# LOGGER CONFIGURATION
# ─────────────────────────────────────────────────────────────

LOGGER_NAME = "pag_core"

LOG_FORMAT = (
    "%(asctime)s "
    "│ %(levelname)-8s "
    "│ %(name)s "
    "│ %(message)s"
)

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────
# LOGGER FACTORY
# ─────────────────────────────────────────────────────────────


def setup_logger() -> logging.Logger:
    """
    Create and configure the PAG Core logger.

    Returns:
        logging.Logger:
            Configured application logger.
    """

    logger = logging.getLogger(
        LOGGER_NAME
    )

    # Prevent duplicate handlers if the logger
    # is initialized more than once.
    if logger.handlers:
        return logger

    logger.setLevel(
        logging.INFO
    )

    formatter = logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )

    console_handler = logging.StreamHandler(
        sys.stdout
    )

    console_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        console_handler
    )

    return logger


# ─────────────────────────────────────────────────────────────
# GLOBAL LOGGER
# ─────────────────────────────────────────────────────────────

logger = setup_logger()