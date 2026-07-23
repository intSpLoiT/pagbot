from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from config.config import Config
from core.database import Database
from core.loader import CogLoader
from services.discord_service import DiscordService
from services.event_service import EventService
from services.roblox_service import RobloxService


class PAGBot(commands.Bot):
    """
    PAG Bot ana Discord bot sınıfı.

    Sorumlulukları:

    - Discord bağlantısı
    - Database yaşam döngüsü
    - RobloxService yaşam döngüsü
    - DiscordService yaşam döngüsü
    - EventService başlatılması
    - Cog yükleme
    - Guild kontrolü
    - Kontrollü kapanış
    """

    def __init__(
        self,
        *,
        config: Config,
        logger: logging.Logger,
    ) -> None:

        intents = discord.Intents.default()

        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        self.config = config
        self.logger = logger

        self.database = Database(
            database_path=config.database_path,
            logger=logger,
        )

        self.roblox_service = RobloxService(
            logger=logger,
        )

        self.event_service = EventService(
            database=self.database,
            logger=logger,
        )

        self.discord_service = DiscordService(
            logger=logger,
        )

        self.cog_loader = CogLoader(
            self,
            logger,
        )

        self._started = False
        self._closed = False

    # ========================================================
    # SETUP HOOK
    # ========================================================

    async def setup_hook(self) -> None:
        """
        Discord bağlantısı kurulmadan önce çalışır.

        Ağır işlemleri on_ready içine koymuyoruz.

        Böylece:
            - Cog'lar birden fazla kez yüklenmez.
            - Database başlangıcı kontrollü olur.
            - Servisler hazır olmadan komutlar çalışmaz.
            - Reconnect sırasında initialization tekrarlanmaz.
        """

        if self._started:
            return

        self.logger.info(
            "Starting PAG Bot initialization...",
        )

        # ====================================================
        # DATABASE
        # ====================================================

        await self.database.connect()

        self.logger.info(
            "Database connected.",
        )

        # ====================================================
        # MIGRATIONS
        # ====================================================

        await self._run_migrations()

        # ====================================================
        # ROBLOX SERVICE
        # ====================================================

        await self.roblox_service.start()

        self.logger.info(
            "Roblox service started.",
        )

        # ====================================================
        # DISCORD SERVICE
        # ====================================================

        await self._start_discord_service()

        # ====================================================
        # EVENT SERVICE
        # ====================================================

        await self._start_event_service()

        # ====================================================
        # COGS
        # ====================================================

        await self.cog_loader.load_all()

        self._started = True

        self.logger.info(
            "PAG Bot initialization completed.",
        )

    # ========================================================
    # MIGRATIONS
    # ========================================================

    async def _run_migrations(self) -> None:
        """
        Database migration sistemini çalıştırır.

        MigrationManager'ın mevcut yapısı
        database ve logger ile çalışır.
        """

        from core.migrations import MigrationManager

        migration_manager = MigrationManager(
            database=self.database,
            logger=self.logger,
        )

        await migration_manager.run()

        self.logger.info(
            "Database migrations completed.",
        )

    # ========================================================
    # DISCORD SERVICE
    # ========================================================

    async def _start_discord_service(self) -> None:
        """
        DiscordService varsa yaşam döngüsünü başlatır.

        Service start() metoduna sahipse çağrılır.
        Böylece servis kullanılmadan önce hazır olur.
        """

        start_method = getattr(
            self.discord_service,
            "start",
            None,
        )

        if start_method is None:
            self.logger.info(
                "Discord service has no start hook.",
            )

            return

        await start_method()

        self.logger.info(
            "Discord service started.",
        )

    # ========================================================
    # EVENT SERVICE
    # ========================================================

    async def _start_event_service(self) -> None:
        """
        EventService başlangıç hook'unu çalıştırır.

        EventService'in mevcut API'sine göre
        kullanılabilir yaşam döngüsü metodunu çağırır.
        """

        start_method = getattr(
            self.event_service,
            "start",
            None,
        )

        if start_method is None:
            self.logger.info(
                "Event service has no start hook.",
            )

            return

        await start_method()

        self.logger.info(
            "Event service started.",
        )

    # ========================================================
    # READY
    # ========================================================

    async def on_ready(self) -> None:
        """
        Discord bağlantısı hazır olduğunda çalışır.

        Burada ağır initialization yapılmaz.
        on_ready reconnect durumunda birden fazla kez
        çalışabileceği için sadece durum loglanır.
        """

        if self.user is None:
            return

        self.logger.info(
            "Connected to Discord as %s (%s).",
            self.user,
            self.user.id,
        )

        self.logger.info(
            "Connected guilds: %s.",
            len(self.guilds),
        )

    # ========================================================
    # GUILD JOIN
    # ========================================================

    async def on_guild_join(
        self,
        guild: discord.Guild,
    ) -> None:
        """
        Bot yalnızca yapılandırılmış PAG guild'inde çalışır.

        Başka bir sunucuya eklenirse otomatik olarak ayrılır.
        """

        allowed_guild_id = (
            self.config.discord_guild_id
        )

        if guild.id == allowed_guild_id:

            self.logger.info(
                "Joined allowed guild: %s (%s).",
                guild.name,
                guild.id,
            )

            return

        self.logger.warning(
            (
                "Unauthorized guild detected: "
                "%s (%s). Leaving."
            ),
            guild.name,
            guild.id,
        )

        try:

            await guild.leave()

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to leave unauthorized "
                    "guild: %s (%s)."
                ),
                guild.name,
                guild.id,
            )

    # ========================================================
    # GUILD REMOVE
    # ========================================================

    async def on_guild_remove(
        self,
        guild: discord.Guild,
    ) -> None:
        """
        PAG guild'inden ayrılma durumunu loglar.
        """

        self.logger.warning(
            "Bot removed from guild: %s (%s).",
            guild.name,
            guild.id,
        )

    # ========================================================
    # COMMAND ERROR
    # ========================================================

    async def on_command_error(
        self,
        context: commands.Context,
        exception: commands.CommandError,
    ) -> None:
        """
        Prefix command hatalarını loglar.

        Slash command hataları ilgili Cog'ların
        app command error handler'ları tarafından yönetilir.
        """

        if isinstance(
            exception,
            commands.CommandNotFound,
        ):
            return

        self.logger.error(
            "Command error: %s",
            exception,
            exc_info=(
                type(exception),
                exception,
                exception.__traceback__,
            ),
        )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self) -> None:
        """
        Tüm servisleri kontrollü sırayla kapatır.

        Kapanış sırasında herhangi bir kaynak açık
        bırakılmaması amaçlanır.
        """

        if self._closed:
            return

        self._closed = True

        self.logger.info(
            "Shutting down PAG Bot...",
        )

        # ====================================================
        # COGS
        # ====================================================

        try:

            await self.cog_loader.unload_all()

        except Exception:

            self.logger.exception(
                "Failed to unload one or more cogs.",
            )

        # ====================================================
        # DISCORD SERVICE
        # ====================================================

        await self._close_service(
            self.discord_service,
            "Discord service",
        )

        # ====================================================
        # EVENT SERVICE
        # ====================================================

        await self._close_service(
            self.event_service,
            "Event service",
        )

        # ====================================================
        # ROBLOX SERVICE
        # ====================================================

        await self._close_service(
            self.roblox_service,
            "Roblox service",
        )

        # ====================================================
        # DATABASE
        # ====================================================

        try:

            await self.database.close()

            self.logger.info(
                "Database closed.",
            )

        except Exception:

            self.logger.exception(
                "Failed to close database.",
            )

        # ====================================================
        # DISCORD
        # ====================================================

        await super().close()

        self.logger.info(
            "PAG Bot shutdown completed.",
        )

    # ========================================================
    # SERVICE CLOSE HELPER
    # ========================================================

    async def _close_service(
        self,
        service: Any,
        service_name: str,
    ) -> None:
        """
        Service close() metodunu varsa çalıştırır.
        """

        close_method = getattr(
            service,
            "close",
            None,
        )

        if close_method is None:
            return

        try:

            await close_method()

            self.logger.info(
                "%s closed.",
                service_name,
            )

        except Exception:

            self.logger.exception(
                "Failed to close %s.",
                service_name,
            )