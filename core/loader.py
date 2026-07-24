# core/loader.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

import discord
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

        announcement
            ↓
        blacklist
            ↓
        general
            ↓
        profile
            ↓
        roblox
            ↓
        role-info
            ↓
        say
            ↓
        system
            ↓
        top-10
            ↓
        top10
            ↓
        verify
            ↓
        write
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
    # COMMAND TREE RESET
    # ========================================================

    def reset_command_tree(
        self,
    ) -> None:
        """
        Discord application command tree'sini temizler.

        Bu işlem özellikle:

            - Önceki bot instance'ından kalan
              command state'lerini

            - Yeniden başlatma sırasında oluşabilecek
              duplicate command kayıtlarını

            - Aynı isimli slash command'lerin
              eski referanslarını

        temizlemek için kullanılır.

        Bu işlem Discord'daki mevcut global komutları
        doğrudan silmez.

        Sadece mevcut Python process'i içindeki
        command tree temizlenir.
        """

        try:

            command_count = len(
                self.bot.tree.get_commands(),
            )

            if command_count == 0:

                self.logger.debug(
                    "Application command tree is already empty.",
                )

                return

            self.bot.tree.clear_commands(
                guild=None,
            )

            self.logger.info(
                "Application command tree reset. "
                "Removed %s local command(s).",
                command_count,
            )

        except Exception:

            self.logger.exception(
                "Failed to reset application command tree.",
            )

            raise

    # ========================================================
    # LOAD ALL
    # ========================================================

    async def load_all(
        self,
    ) -> None:
        """
        Tüm Cog'ları sırayla yükler.

        Başlamadan önce application command tree
        temizlenir.

        Böylece bot yeniden başlatıldığında
        process içindeki eski command state'lerinin
        yeni Cog'larla çakışması engellenir.

        Bir Cog yüklenemediğinde:

            - Hata loglanır.
            - Problemli extension mümkünse temizlenir.
            - Botun tamamen çökmesi engellenir.

        Böylece sağlam Cog'lar çalışmaya devam edebilir.
        """

        # ----------------------------------------------------
        # COMMAND TREE RESET
        # ----------------------------------------------------

        self.reset_command_tree()

        # ----------------------------------------------------
        # LOAD EXTENSIONS
        # ----------------------------------------------------

        for extension in self.COGS:

            # ------------------------------------------------
            # DUPLICATE EXTENSION CHECK
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

            # ------------------------------------------------
            # ALREADY LOADED
            # ------------------------------------------------

            except commands.ExtensionAlreadyLoaded:

                self.logger.warning(
                    "Cog already loaded: %s",
                    extension,
                )

                continue

            # ------------------------------------------------
            # NOT FOUND
            # ------------------------------------------------

            except commands.ExtensionNotFound:

                self.logger.error(
                    "Cog not found: %s",
                    extension,
                    exc_info=True,
                )

                # Eksik Cog nedeniyle botu çökertme.
                continue

            # ------------------------------------------------
            # NO SETUP
            # ------------------------------------------------

            except commands.NoEntryPointError:

                self.logger.error(
                    "Cog setup() not found: %s",
                    extension,
                    exc_info=True,
                )

                # Setup olmayan Cog atlanır.
                continue

            # ------------------------------------------------
            # COMMAND ALREADY REGISTERED
            # ------------------------------------------------

            except commands.ExtensionFailed as error:

                original_error = error.original

                if isinstance(
                    original_error,
                    discord.app_commands.CommandAlreadyRegistered,
                ):

                    self.logger.error(
                        (
                            "Duplicate application command "
                            "detected while loading %s: %s"
                        ),
                        extension,
                        original_error,
                    )

                    self.logger.warning(
                        (
                            "Skipping conflicting Cog: %s. "
                            "Check duplicate slash command names."
                        ),
                        extension,
                    )

                    # Extension başarısız olduğundan
                    # normalde discord.py rollback yapar.
                    #
                    # Burada botun tamamen kapanmasını
                    # engelliyoruz.
                    continue

                self.logger.error(
                    "Cog failed to load: %s",
                    extension,
                    exc_info=True,
                )

                # Diğer Cog'ların çalışmaya devam
                # edebilmesi için bu extension atlanır.
                continue

            # ------------------------------------------------
            # UNEXPECTED ERROR
            # ------------------------------------------------

            except Exception:

                self.logger.exception(
                    "Unexpected error while loading cog: %s",
                    extension,
                )

                # Tek bir Cog yüzünden tüm botun
                # kapanmasını engelle.
                continue

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

        # ----------------------------------------------------
        # COMMAND TREE RESET
        # ----------------------------------------------------

        try:

            self.reset_command_tree()

        except Exception:

            self.logger.exception(
                "Failed to reset command tree during unload.",
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

    # ========================================================
    # LOADED COGS
    # ========================================================

    def loaded_cogs(
        self,
    ) -> tuple[str, ...]:
        """
        Aktif olarak yüklenmiş Cog'ların isimlerini
        tuple olarak döndürür.
        """

        return tuple(
            extension
            for extension in self.COGS
            if extension in self.bot.extensions
        )

    # ========================================================
    # STATUS
    # ========================================================

    def status(
        self,
    ) -> dict[str, object]:
        """
        Loader durumunu döndürür.

        Health/status sistemleri tarafından
        kullanılabilir.
        """

        loaded = self.loaded_cogs()

        return {
            "total": len(self.COGS),
            "loaded": len(loaded),
            "extensions": loaded,
            "commands": len(
                self.bot.tree.get_commands(),
            ),
        }