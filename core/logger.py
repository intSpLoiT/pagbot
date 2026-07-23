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
DEFAULT_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


# ============================================================
# LOGGER SETUP
# ============================================================

def setup_logger(
    name: str = "PAG",
    level: int = DEFAULT_LOG_LEVEL,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """
    PAG Bot için logger oluşturur veya mevcut logger'ı yapılandırır.

    Aynı logger birden fazla kez setup edilirse
    duplicate handler oluşturmaz.
    """

    logger = logging.getLogger(name)

    # Logger seviyesini ayarla
    logger.setLevel(level)

    # Parent logger'dan gelen duplicate çıktıları engelle
    logger.propagate = False

    # Daha önce setup edilmişse tekrar handler ekleme
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # --------------------------------------------------------
    # CONSOLE HANDLER
    # --------------------------------------------------------

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    # --------------------------------------------------------
    # FILE HANDLER
    # --------------------------------------------------------

    if log_file is not None:
        log_path = Path(log_file)

        # Log klasörü yoksa oluştur
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            filename=log_path,
            encoding="utf-8",
        )

        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger


# ============================================================
# PAG LOGGER CLASS
# ============================================================

class PAGLogger:
    """
    PAG Bot için sade logger wrapper'ı.

    Logger setup işlemi bu class'ın dışında yapılır.
    """

    def __init__(self, name: str = "PAG"):
        self._logger = logging.getLogger(name)

    # --------------------------------------------------------
    # INFO
    # --------------------------------------------------------

    def info(self, message: str) -> None:
        self._logger.info(message)

    # --------------------------------------------------------
    # WARNING
    # --------------------------------------------------------

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    def error(self, message: str) -> None:
        self._logger.error(message)

    # --------------------------------------------------------
    # DEBUG
    # --------------------------------------------------------

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    # --------------------------------------------------------
    # EXCEPTION
    # --------------------------------------------------------

    def exception(self, message: str) -> None:
        """
        Exception sırasında kullanılır.

        Kullanıldığı yerde mevcut exception'ın
        traceback bilgisini de loglar.
        """

        self._logger.exception(message)