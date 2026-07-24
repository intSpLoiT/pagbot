# core/loader.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from discord.ext import commands


if TYPE_CHECKING:

    from core.bot import PAGBot


# ============================================================
# COG LOADER
# ============================================================

class CogLoader:
    """
    PAG Bot Cog Loader.

    Tüm aktif Discord Cog'larını merkezi olarak
    yükler ve güvenli şekilde kaldırır.

    Cog sırası kontrollüdür.

    Örneğin:
        general
            ↓
        verify
            ↓
        blacklist
            ↓
        top-10
            ↓
        say
    """

    # ========================================================
    # COG LIST
    # ========================================================

    COGS: Final[
        tuple[str, ...]
    ] = (

        "cogs.announcement",

        "cogs.blacklist",

        "cogs.general",

        "cogs.profile",

        "cogs.roblox",

        "cogs.role-info",

        "cogs.say",

        "cogs.system",

        "cogs.top-10",

        "cogs.top10",

        "cogs.verify",

        "cogs.write",
    )

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        bot: PAGBot,
        logger: logging.Logger,
    ) -> None:

        self.bot = bot

        self.logger = logger

    # ========================================================
    # LOAD ALL
    # ========================================================

    async def load_all(
        self,
    ) -> None:
        """
        Tüm Cog'ları sırayla yükler.

        Bir Cog yüklenemezse exception yeniden
        yükseltilir ve botun hatalı bir state ile
        çalışmaya devam etmesi engellenir.
        """

        for extension in self.COGS:

            # ------------------------------------------------
            # DUPLICATE CHECK
            # ------------------------------------------------

            if extension in self.bot.extensions:

                self.logger.warning(
                    "Cog already loaded: %s",
                    extension,
                )

                continue

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

            except Exception:

                self.logger.exception(
                    "Unexpected error while loading cog: %s",
                    extension,
                )

                raise

    # ========================================================
    # UNLOAD ALL
    # ========================================================

    async def unload_all(
        self,
    ) -> None:
        """
        Yüklenmiş Cog'ları ters sırayla güvenli
        şekilde kaldırır.

        Ters sıra kullanılmasının amacı,
        bağımlılığı olan sistemlerin önce
        kaldırılmasını sağlamaktır.
        """

        for extension in reversed(
            self.COGS,
        ):

            # ------------------------------------------------
            # NOT LOADED
            # ------------------------------------------------

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

    # ========================================================
    # LOADED COG COUNT
    # ========================================================

    def loaded_count(
        self,
    ) -> int:
        """
        Bu loader tarafından yüklenmiş olan
        aktif Cog sayısını döndürür.
        """

        return sum(
            extension in self.bot.extensions
            for extension in self.COGS
        )