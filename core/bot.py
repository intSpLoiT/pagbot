from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands, tasks

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
    - Database migration sistemi
    - RobloxService yaşam döngüsü
    - DiscordService yaşam döngüsü
    - EventService yaşam döngüsü
    - Cog yükleme ve kaldırma
    - Guild kontrolü
    - Slash command guild sync
    - Discord presence yönetimi
    - Kontrollü kapanış
    """

    # ========================================================
    # PRESENCE SETTINGS
    # ========================================================

    PRESENCE_INTERVAL: int = 60

    # ========================================================
    # INIT
    # ========================================================

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

        # ====================================================
        # GUILD OBJECT
        # ====================================================

        self.guild_object = discord.Object(
            id=config.discord_guild_id,
        )

        # ====================================================
        # SERVICES
        # ====================================================

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

        # ====================================================
        # STATE
        # ====================================================

        self._started = False

        self._closed = False

        self._ready_logged = False

        self._presence_started = False

        self._commands_synced = False

        self._started_at = time.monotonic()

    # ========================================================
    # SETUP HOOK
    # ========================================================

    async def setup_hook(
        self,
    ) -> None:
        """
        Discord bağlantısı kurulmadan önce çalışır.

        Initialization sırası:

            Database
                ↓
            Migrations
                ↓
            Services
                ↓
            Cogs
                ↓
            Guild Slash Command Sync
        """

        if self._started:

            self.logger.debug(
                "PAG Bot initialization already completed.",
            )

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
        # ========================================================

        await self.cog_loader.load_all()

        # ====================================================
        # SLASH COMMAND SYNC
        # ====================================================

        await self._sync_commands()

        # ====================================================
        # INITIALIZATION COMPLETE
        # ====================================================

        self._started = True

        self.logger.info(
            "PAG Bot initialization completed.",
        )

    # ========================================================
    # DATABASE MIGRATIONS
    # ========================================================

    async def _run_migrations(
        self,
    ) -> None:
        """
        Database migration sistemini çalıştırır.
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
    # SLASH COMMAND SYNC
    # ========================================================

    async def _sync_commands(
        self,
    ) -> None:
        """
        Slash command'ları PAG guild'ine senkronize eder.

        Guild sync kullanıldığı için komutlar
        yalnızca yapılandırılmış sunucuda görünür.

        Bu yöntem:

            - Komut listesini Discord'a gönderir.
            - Eski guild komutlarını günceller.
            - Yeni komutları ekler.
            - Silinen komutları temizler.
            - Global command cache sorunlarını önler.
        """

        if self._commands_synced:

            self.logger.debug(
                "Slash commands already synchronized.",
            )

            return

        try:

            synced_commands = await self.tree.sync(
                guild=self.guild_object,
            )

            self._commands_synced = True

            self.logger.info(
                "Slash commands synchronized.",
            )

            self.logger.info(
                "Guild command count: %s.",
                len(synced_commands),
            )

            for command in synced_commands:

                self.logger.debug(
                    "Synced command: /%s",
                    command.name,
                )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to synchronize slash commands.",
            )

            raise

        except Exception:

            self.logger.exception(
                "Unexpected slash command sync error.",
            )

            raise

    # ========================================================
    # DISCORD SERVICE
    # ========================================================

    async def _start_discord_service(
        self,
    ) -> None:
        """
        DiscordService varsa start() metodunu çalıştırır.
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

    async def _start_event_service(
        self,
    ) -> None:
        """
        EventService varsa start() metodunu çalıştırır.
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

    async def on_ready(
        self,
    ) -> None:
        """
        Discord bağlantısı hazır olduğunda çalışır.

        Reconnect durumunda tekrar çalışabilir.
        Ağır initialization burada yapılmaz.
        """

        if self.user is None:

            return

        if not self._ready_logged:

            self.logger.info(
                "Connected to Discord as %s (%s).",
                self.user,
                self.user.id,
            )

            self.logger.info(
                "Connected guilds: %s.",
                len(self.guilds),
            )

            self._ready_logged = True

        else:

            self.logger.info(
                "Discord connection restored.",
            )

        self._start_presence_loop()

        await self._update_presence()

    # ========================================================
    # PRESENCE LOOP
    # ========================================================

    def _start_presence_loop(
        self,
    ) -> None:
        """
        Presence loop'un yalnızca bir kez
        başlatılmasını sağlar.
        """

        if self._presence_started:

            return

        if self.presence_loop.is_running():

            self._presence_started = True

            return

        self.presence_loop.start()

        self._presence_started = True

        self.logger.info(
            "Presence rotation started.",
        )

    # ========================================================
    # PRESENCE ROTATION
    # ========================================================

    @tasks.loop(
        seconds=PRESENCE_INTERVAL,
    )
    async def presence_loop(
        self,
    ) -> None:
        """
        Bot activity bilgisini belirli aralıklarla
        günceller.
        """

        try:

            await self._update_presence()

        except discord.HTTPException as error:

            self.logger.warning(
                "Presence update failed: %s",
                error,
            )

        except Exception:

            self.logger.exception(
                "Unexpected presence update error.",
            )

    # ========================================================
    # PRESENCE LOOP READY
    # ========================================================

    @presence_loop.before_loop
    async def before_presence_loop(
        self,
    ) -> None:
        """
        Presence loop başlamadan önce Discord
        bağlantısının hazır olmasını bekler.
        """

        await self.wait_until_ready()

    # ========================================================
    # UPDATE PRESENCE
    # ========================================================

    async def _update_presence(
        self,
    ) -> None:
        """
        Botun Discord presence bilgisini günceller.
        """

        if self.is_closed():

            return

        if self.user is None:

            return

        guild_count = len(
            self.guilds,
        )

        member_count = sum(
            guild.member_count or 0
            for guild in self.guilds
        )

        command_count = len(
            self.tree.get_commands(
                guild=self.guild_object,
            ),
        )

        uptime = self._get_uptime()

        activities = (
            discord.Activity(
                type=discord.ActivityType.watching,
                name="/help",
            ),

            discord.Activity(
                type=discord.ActivityType.playing,
                name="PAG Community",
            ),

            discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{member_count} PAG Members",
            ),

            discord.Activity(
                type=discord.ActivityType.playing,
                name=f"{command_count} Commands",
            ),

            discord.Activity(
                type=discord.ActivityType.watching,
                name=f"PAG | {guild_count} Server",
            ),

            discord.Activity(
                type=discord.ActivityType.playing,
                name=f"Online for {uptime}",
            ),
        )

        current_index = (
            int(
                time.monotonic()
                // self.PRESENCE_INTERVAL
            )
            % len(activities)
        )

        activity = activities[
            current_index
        ]

        await self.change_presence(
            status=discord.Status.online,
            activity=activity,
        )

    # ========================================================
    # UPTIME
    # ========================================================

    def _get_uptime(
        self,
    ) -> str:
        """
        Bot uptime bilgisini okunabilir formatta
        döndürür.
        """

        elapsed = int(
            time.monotonic()
            - self._started_at
        )

        days, remainder = divmod(
            elapsed,
            86400,
        )

        hours, remainder = divmod(
            remainder,
            3600,
        )

        minutes, _ = divmod(
            remainder,
            60,
        )

        if days > 0:

            return (
                f"{days}d "
                f"{hours}h "
                f"{minutes}m"
            )

        if hours > 0:

            return (
                f"{hours}h "
                f"{minutes}m"
            )

        return f"{minutes}m"

    # ========================================================
    # GUILD JOIN
    # ========================================================

    async def on_guild_join(
        self,
        guild: discord.Guild,
    ) -> None:
        """
        Bot yalnızca yapılandırılmış PAG guild'inde
        çalışır.
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

    async def close(
        self,
    ) -> None:
        """
        Tüm servisleri kontrollü şekilde kapatır.
        """

        if self._closed:

            return

        self._closed = True

        self.logger.info(
            "Shutting down PAG Bot...",
        )

        # ====================================================
        # PRESENCE LOOP
        # ====================================================

        if self.presence_loop.is_running():

            self.presence_loop.cancel()

            self.logger.info(
                "Presence rotation stopped.",
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