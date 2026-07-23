from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = PROJECT_ROOT / "data"

LOG_DIR = DATA_DIR / "logs"

DATABASE_PATH = (
    DATA_DIR / "pag.db"
)

LOG_FILE_PATH = (
    LOG_DIR / "pag.log"
)


# ============================================================
# ENVIRONMENT
# ============================================================

ENV_FILE = (
    PROJECT_ROOT / ".env"
)

load_dotenv(
    ENV_FILE,
)


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(
    frozen=True,
    slots=True,
)
class Config:
    """
    PAG Bot merkezi configuration.

    frozen=True:
        Runtime sırasında ayarların değiştirilmesini önler.

    slots=True:
        Gereksiz __dict__ kullanımını önler.
    """

    discord_token: str

    discord_guild_id: int

    database_path: Path

    log_file_path: Path

    debug: bool = False


# ============================================================
# CONFIG LOADER
# ============================================================

def load_config() -> Config:
    """
    Environment değişkenlerinden Config oluşturur.

    Gerekli değerler eksikse bot başlatılmaz.
    """

    # ========================================================
    # DISCORD TOKEN
    # ========================================================

    discord_token = os.getenv(
        "DISCORD_TOKEN",
    )

    if not discord_token:

        raise RuntimeError(
            "DISCORD_TOKEN is missing "
            "from the environment."
        )

    # ========================================================
    # DISCORD GUILD ID
    # ========================================================

    guild_id_value = os.getenv(
        "DISCORD_GUILD_ID",
    )

    if not guild_id_value:

        raise RuntimeError(
            "DISCORD_GUILD_ID is missing "
            "from the environment."
        )

    try:

        discord_guild_id = int(
            guild_id_value,
        )

    except ValueError as error:

        raise RuntimeError(
            "DISCORD_GUILD_ID must be a valid integer."
        ) from error

    if discord_guild_id <= 0:

        raise RuntimeError(
            "DISCORD_GUILD_ID must be positive."
        )

    # ========================================================
    # DEBUG
    # ========================================================

    debug_value = os.getenv(
        "DEBUG",
        "false",
    ).strip().lower()

    debug = debug_value in {
        "1",
        "true",
        "yes",
        "on",
    }

    # ========================================================
    # DIRECTORIES
    # ========================================================

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # CONFIG
    # ========================================================

    return Config(
        discord_token=discord_token,
        discord_guild_id=discord_guild_id,
        database_path=DATABASE_PATH,
        log_file_path=LOG_FILE_PATH,
        debug=debug,
    )