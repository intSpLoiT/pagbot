from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from discord.ext import commands


if TYPE_CHECKING:
    from core.bot import PAGBot


class CogLoader:
    """
    PAG Bot Cog Loader.

    Tüm Cog'ları merkezi olarak yükler.
    """

    COGS: tuple[str, ...] = (
        "cogs.general",
        "cogs.verify",
        "cogs.blacklist",
        "cogs.top-10",
        "cogs.say",
        "cogs.events",
    )

    def __init__(
        self,
        bot: PAGBot,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.logger = logger

    async def load_all(self) -> None:
        """
        Tüm Cog'ları sırayla yükler.
        """

        for extension in self.COGS:

            try:

                await self.bot.load_extension(
                    extension,
                )

                self.logger.info(
                    "Loaded cog: %s",
                    extension,
                )

            except commands.ExtensionAlreadyLoaded:

                self.logger.warning(
                    "Cog already loaded: %s",
                    extension,
                )

            except commands.ExtensionNotFound:

                self.logger.exception(
                    "Cog not found: %s",
                    extension,
                )

                raise

            except commands.NoEntryPointError:

                self.logger.exception(
                    "Cog setup() not found: %s",
                    extension,
                )

                raise

            except commands.ExtensionFailed:

                self.logger.exception(
                    "Cog failed to load: %s",
                    extension,
                )

                raise

    async def unload_all(self) -> None:
        """
        Yüklenmiş Cog'ları güvenli şekilde kaldırır.
        """

        for extension in reversed(
            self.COGS,
        ):

            if extension not in self.bot.extensions:
                continue

            try:

                await self.bot.unload_extension(
                    extension,
                )

                self.logger.info(
                    "Unloaded cog: %s",
                    extension,
                )

            except commands.ExtensionNotLoaded:

                continue

            except Exception:

                self.logger.exception(
                    "Failed to unload cog: %s",
                    extension,
                )