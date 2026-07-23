"""
╔══════════════════════════════════════════════════════════════╗
║                         PAG CORE                            ║
║                    Application Settings                     ║
╚══════════════════════════════════════════════════════════════╝

Environment variables are loaded from the .env file.

Required:
    DISCORD_TOKEN

Optional:
    DATABASE_PATH
    DEBUG_MODE
"""

import os

from dotenv import load_dotenv


# ─────────────────────────────────────────────────────────────
# ENVIRONMENT
# ─────────────────────────────────────────────────────────────

load_dotenv()


# ─────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────


class Settings:
    """
    Central application configuration.

    All environment-based configuration is kept here so that
    the rest of the application does not directly access os.getenv.
    """

    def __init__(self) -> None:
        self.discord_token: str | None = os.getenv(
            "DISCORD_TOKEN"
        )

        self.database_path: str = os.getenv(
            "DATABASE_PATH",
            "data/pag.db",
        )

        self.debug_mode: bool = (
            os.getenv(
                "DEBUG_MODE",
                "false",
            ).lower()
            == "true"
        )

    def validate(self) -> None:
        """
        Validate required configuration values.

        Raises:
            ValueError:
                If the Discord token is missing.
        """

        if not self.discord_token:
            raise ValueError(
                "DISCORD_TOKEN is not configured."
            )


# ─────────────────────────────────────────────────────────────
# GLOBAL SETTINGS INSTANCE
# ─────────────────────────────────────────────────────────────

settings = Settings()