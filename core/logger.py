from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_LOG_LEVEL: Final[int] = logging.INFO

DEFAULT_LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)

DEFAULT_DATE_FORMAT: Final[str] = (
    "%Y-%m-%d %H:%M:%S"
)


# ============================================================
# GLOBAL LOGGER
# ============================================================

logger: logging.Logger = logging.getLogger(
    "PAG"
)


# ============================================================
# LOGGER SETUP
# ============================================================

def setup_logger(
    name: str = "PAG",
    level: int = DEFAULT_LOG_LEVEL,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """
    PAG Bot için logger oluşturur veya mevcut
    logger'ı yapılandırır.

    Aynı logger birden fazla kez setup edilirse
    duplicate handler oluşturmaz.
    """

    global logger

    configured_logger = logging.getLogger(
        name
    )

    configured_logger.setLevel(
        level
    )

    configured_logger.propagate = False

    formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # ========================================================
    # EXISTING HANDLERS
    # ========================================================

    has_console_handler = any(
        isinstance(
            handler,
            logging.StreamHandler,
        )
        and not isinstance(
            handler,
            logging.FileHandler,
        )
        for handler in configured_logger.handlers
    )

    has_file_handler = any(
        isinstance(
            handler,
            logging.FileHandler,
        )
        for handler in configured_logger.handlers
    )

    # ========================================================
    # CONSOLE HANDLER
    # ========================================================

    if not has_console_handler:

        console_handler = logging.StreamHandler(
            sys.stdout
        )

        console_handler.setLevel(
            level
        )

        console_handler.setFormatter(
            formatter
        )

        configured_logger.addHandler(
            console_handler
        )

    # ========================================================
    # FILE HANDLER
    # ========================================================

    if (
        log_file is not None
        and not has_file_handler
    ):

        log_path = Path(
            log_file
        )

        log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_handler = logging.FileHandler(
            filename=log_path,
            encoding="utf-8",
        )

        file_handler.setLevel(
            level
        )

        file_handler.setFormatter(
            formatter
        )

        configured_logger.addHandler(
            file_handler
        )

    # ========================================================
    # GLOBAL LOGGER REFERENCE
    # ========================================================

    logger = configured_logger

    return configured_logger


# ============================================================
# PAG LOGGER CLASS
# ============================================================

class PAGLogger:
    """
    PAG Bot için sade logger wrapper'ı.

    Logger setup işlemi bu class'ın dışında yapılır.
    """

    def __init__(
        self,
        name: str = "PAG",
    ) -> None:

        self._logger = logging.getLogger(
            name
        )

    # ========================================================
    # INFO
    # ========================================================

    def info(
        self,
        message: str,
        *args: object,
    ) -> None:

        self._logger.info(
            message,
            *args,
        )

    # ========================================================
    # WARNING
    # ========================================================

    def warning(
        self,
        message: str,
        *args: object,
    ) -> None:

        self._logger.warning(
            message,
            *args,
        )

    # ========================================================
    # ERROR
    # ========================================================

    def error(
        self,
        message: str,
        *args: object,
    ) -> None:

        self._logger.error(
            message,
            *args,
        )

    # ========================================================
    # DEBUG
    # ========================================================

    def debug(
        self,
        message: str,
        *args: object,
    ) -> None:

        self._logger.debug(
            message,
            *args,
        )

    # ========================================================
    # EXCEPTION
    # ========================================================

    def exception(
        self,
        message: str,
        *args: object,
    ) -> None:
        """
        Exception sırasında kullanılır.

        Mevcut exception'ın traceback bilgisini
        de loglar.
        """

        self._logger.exception(
            message,
            *args,
        )