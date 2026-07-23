"""
PAG Core
Main Discord Bot

This module contains the main PAG Core Discord bot class.

The PAGBot class is responsible for:

- Configuring Discord intents
- Managing the database lifecycle
- Loading application extensions
- Synchronizing slash commands
- Handling the Discord ready event
- Tracking connection state
- Handling graceful shutdowns
- Managing application-level bot state

Application startup flow:

    main.py
        |
        v
    PAGBot()
        |
        v
    setup_hook()
        |
        +--> Connect database
        |
        +--> Initialize database
        |
        +--> Load extensions
        |
        +--> Sync commands
        |
        v
    Discord login
        |
        v
    on_ready()
        |
        v
    PAG Core ONLINE
"""


from __future__ import annotations


import time
from typing import Final

import discord
import importlib
import pkgutil

import cogs
from discord.ext import commands


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


from core.database import Database
from core.logger import logger


class PAGBot(commands.Bot):
    """
    Main Discord bot class for PAG Core.

    PAGBot acts as the central application controller.

    Other systems communicate with the bot through:

        self.database

        self.services

        self.config

        self.application_state

    The bot itself should remain responsible for the
    application lifecycle rather than containing all business
    logic directly.
    """


    def __init__(self) -> None:
        """
        Initialize PAG Core.

        Discord intents are configured here before the bot
        connects to Discord.
        """


        intents = self._create_intents()


        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )


        self.database: Final[
            Database
        ] = Database()


        self.start_time: float = time.time()


        self.is_fully_ready: bool = False


        self.is_shutting_down: bool = False


        self._ready_event = False


    @staticmethod
    def _create_intents() -> discord.Intents:
        """
        Create and configure Discord intents.

        The current PAG Core system requires member access
        because several future systems depend on Discord
        guild members.

        Required systems include:

        - Role Info
        - Rank management
        - Member Spotlight
        - Leaderboards
        - Member synchronization
        """

        intents = discord.Intents.default()


        intents.guilds = True


        intents.members = True


        intents.guild_messages = True


        intents.message_content = True


        return intents


    async def setup_hook(self) -> None:
        """
        Run application initialization before Discord becomes
        fully ready.

        This is the main startup lifecycle.

        Startup sequence:

            1. Log startup information
            2. Connect to database
            3. Initialize database schema
            4. Load extensions
            5. Synchronize slash commands
            6. Finish startup preparation

        Discord's on_ready event is triggered later when the
        bot has successfully connected to Discord.
        """

        self._log_startup()


        await self._initialize_database()


        await self._load_extensions()


        await self._sync_commands()


        logger.info(
            "Startup preparation completed."
        )


    async def _initialize_database(self) -> None:
        """
        Initialize the database connection and schema.
        """

        logger.info(
            "Initializing database..."
        )


        try:

            await self.database.connect()


            await self.database.initialize()


        except Exception:

            logger.exception(
                "Database initialization failed."
            )


            raise


        logger.info(
            "Database initialization completed."
        )


    async def _load_extensions(self) -> None:
        """
        Automatically discover and load all valid extensions
        from the cogs package.

        The extension loader is designed to be:

        - Automatic
        - Safe
        - Extensible
        - Debug-friendly
        - Resistant to invalid files
        - Compatible with nested Cog packages

        Expected structure:

            cogs/
            ├── __init__.py
            ├── system.py
            ├── roblox.py
            ├── profiles.py
            │
            └── admin/
                ├── __init__.py
                ├── moderation.py
                └── configuration.py

        Every valid Python module containing a valid Discord
        extension can be automatically discovered and loaded.

        The loader does not require every Cog to be manually
        added to a hardcoded list.

        This means that adding a new Cog is as simple as:

            cogs/new_feature.py

        The bot will automatically discover it on startup.
        """


        logger.info(
            "Beginning extension discovery."
        )


        extension_package_name = "cogs"


        try:

            extension_package = importlib.import_module(
                extension_package_name
            )


        except ModuleNotFoundError:

            logger.exception(
                "The cogs package could not be imported."
            )


            raise


        except Exception:

            logger.exception(
                "Unexpected error while importing "
                "the cogs package."
            )


            raise


        if not hasattr(
            extension_package,
            "__path__",
        ):

            logger.error(
                "The cogs package does not have "
                "a valid package path."
            )


            raise RuntimeError(
                "The cogs package is not a valid package."
            )


        discovered_extensions: list[str] = []


        failed_discoveries: list[str] = []


        logger.info(
            "Scanning extension package: %s",
            extension_package_name,
        )


        try:

            module_iterator = pkgutil.walk_packages(
                extension_package.__path__,
                prefix=(
                    f"{extension_package_name}."
                ),
            )


        except Exception:

            logger.exception(
                "Failed to scan the extension package."
            )


            raise


        for module_info in module_iterator:

            module_name = module_info.name


            is_package = module_info.ispkg


            if not module_name:

                continue


            if module_name.endswith(
                ".__init__"
            ):

                continue


            module_parts = module_name.split(
                "."
            )


            if any(
                part.startswith("_")
                for part in module_parts
            ):

                logger.debug(
                    "Skipping private extension: %s",
                    module_name,
                )


                continue


            if is_package:

                logger.debug(
                    "Skipping package directory: %s",
                    module_name,
                )


                continue


            if not module_name.endswith(
                ".py"
            ):

                pass


            discovered_extensions.append(
                module_name
            )


        discovered_extensions = sorted(
            set(
                discovered_extensions
            )
        )


        if not discovered_extensions:

            logger.warning(
                "No extensions were discovered."
            )


            return


        logger.info(
            "Discovered %d extension(s).",
            len(
                discovered_extensions
            ),
        )


        loaded_extensions: list[str] = []


        skipped_extensions: list[str] = []


        failed_extensions: dict[
            str,
            str,
        ] = {}


        for extension_name in (
            discovered_extensions
        ):

            logger.info(
                "Preparing extension: %s",
                extension_name,
            )


            if extension_name in (
                self.extensions
            ):

                logger.warning(
                    "Extension already loaded: %s",
                    extension_name,
                )


                skipped_extensions.append(
                    extension_name
                )


                continue


            try:

                extension_module = importlib.import_module(
                    extension_name
                )


            except ModuleNotFoundError as error:

                error_message = (
                    f"ModuleNotFoundError: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Failed to import extension: %s",
                    extension_name,
                )


                continue


            except ImportError as error:

                error_message = (
                    f"ImportError: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Import error while importing: %s",
                    extension_name,
                )


                continue


            except Exception as error:

                error_message = (
                    f"{type(error).__name__}: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Unexpected error while importing: %s",
                    extension_name,
                )


                continue


            if not hasattr(
                extension_module,
                "setup",
            ):

                logger.warning(
                    "Skipping invalid extension: %s",
                    extension_name,
                )


                logger.warning(
                    "Reason: missing setup() function."
                )


                skipped_extensions.append(
                    extension_name
                )


                continue


            setup_function = getattr(
                extension_module,
                "setup",
            )


            if not callable(
                setup_function
            ):

                logger.warning(
                    "Skipping invalid extension: %s",
                    extension_name,
                )


                logger.warning(
                    "Reason: setup is not callable."
                )


                skipped_extensions.append(
                    extension_name
                )


                continue


            try:

                await self.load_extension(
                    extension_name
                )


            except commands.ExtensionAlreadyLoaded:

                logger.warning(
                    "Extension already loaded: %s",
                    extension_name,
                )


                skipped_extensions.append(
                    extension_name
                )


                continue


            except commands.ExtensionNotFound as error:

                error_message = (
                    f"ExtensionNotFound: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Extension file could not be loaded: %s",
                    extension_name,
                )


                continue


            except commands.NoEntryPointError as error:

                error_message = (
                    f"NoEntryPointError: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Extension has no valid setup entry point: %s",
                    extension_name,
                )


                continue


            except commands.ExtensionFailed as error:

                error_message = (
                    f"ExtensionFailed: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Extension setup failed: %s",
                    extension_name,
                )


                continue


            except Exception as error:

                error_message = (
                    f"{type(error).__name__}: {error}"
                )


                failed_extensions[
                    extension_name
                ] = error_message


                logger.exception(
                    "Unexpected error while loading: %s",
                    extension_name,
                )


                continue


            loaded_extensions.append(
                extension_name
            )


            logger.info(
                "Extension loaded successfully: %s",
                extension_name,
            )


        logger.info(
            "Extension discovery completed."
        )


        logger.info(
            "Total discovered: %d",
            len(
                discovered_extensions
            ),
        )


        logger.info(
            "Total loaded: %d",
            len(
                loaded_extensions
            ),
        )


        logger.info(
            "Total skipped: %d",
            len(
                skipped_extensions
            ),
        )


        logger.info(
            "Total failed: %d",
            len(
                failed_extensions
            ),
        )


        if loaded_extensions:

            logger.info(
                "Loaded extensions: %s",
                ", ".join(
                    loaded_extensions
                ),
            )


        if skipped_extensions:

            logger.info(
                "Skipped extensions: %s",
                ", ".join(
                    skipped_extensions
                ),
            )


        if failed_extensions:

            logger.error(
                "One or more extensions failed to load."
            )


            for (
                extension_name,
                error_message,
            ) in failed_extensions.items():

                logger.error(
                    "%s -> %s",
                    extension_name,
                    error_message,
                )


        if failed_extensions:

            logger.warning(
                "PAG Core started with extension errors."
            )


        else:

            logger.info(
                "All discovered extensions loaded successfully."
            )


    async def _sync_commands(self) -> None:
        """
        Synchronize application slash commands with Discord.

        Global slash commands may take time to propagate.

        During development, commands can later be synchronized
        to a development guild for faster testing.
        """

        logger.info(
            "Synchronizing application commands..."
        )


        try:

            synced = await self.tree.sync()


        except Exception:

            logger.exception(
                "Application command synchronization failed."
            )


            raise


        logger.info(
            "Application commands synchronized: %d",
            len(synced),
        )


    def _log_startup(self) -> None:
        """
        Log application startup information.
        """

        logger.info(
            "Starting %s",
            BOT_NAME,
        )


        logger.info(
            "Version: %s",
            BOT_VERSION,
        )


        logger.info(
            "Initializing Discord connection..."
        )


    async def on_ready(self) -> None:
        """
        Handle the Discord ready event.

        This event is triggered when the bot has successfully
        connected and Discord has completed the initial
        connection process.

        The method is designed to be safe if Discord reconnects
        and triggers the ready event again.
        """

        if self.user is None:

            logger.warning(
                "Ready event received without bot user."
            )


            return


        self._ready_event = True


        self.is_fully_ready = True


        logger.info(
            "Discord connection established."
        )


        logger.info(
            "Logged in as: %s",
            self.user,
        )


        logger.info(
            "Bot ID: %s",
            self.user.id,
        )


        logger.info(
            "Guild count: %d",
            len(self.guilds),
        )


        logger.info(
            "Latency: %.2f ms",
            self.latency * 1000,
        )


        logger.info(
            "PAG Core is now ONLINE."
        )


    async def on_resumed(self) -> None:
        """
        Handle a successful Discord session resume.

        Discord may reconnect the bot after a temporary
        connection interruption.
        """

        logger.info(
            "Discord session resumed."
        )


        logger.info(
            "PAG Core connection restored."
        )


    async def on_disconnect(self) -> None:
        """
        Handle a Discord disconnection.

        A disconnection does not necessarily mean that the
        application has permanently stopped.

        discord.py may automatically reconnect.
        """

        self.is_fully_ready = False


        logger.warning(
            "Discord connection lost."
        )


        logger.warning(
            "Waiting for Discord reconnection..."
        )


    async def on_command_error(
        self,
        context: commands.Context,
        exception: commands.CommandError,
    ) -> None:
        """
        Handle traditional prefix command errors.

        Slash command errors are handled separately through
        application command error handlers.
        """

        logger.error(
            "Command error: %s",
            exception,
        )


        if isinstance(
            exception,
            commands.CommandNotFound,
        ):

            return


        if context.channel is not None:

            try:

                await context.send(
                    "An unexpected error occurred."
                )


            except discord.HTTPException:

                logger.exception(
                    "Failed to send command error message."
                )


    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        exception: discord.app_commands.AppCommandError,
    ) -> None:
        """
        Handle slash command errors.

        This provides a centralized fallback for application
        command failures.
        """

        logger.exception(
            "Application command error.",
            exc_info=exception,
        )


        if interaction.response.is_done():

            try:

                await interaction.followup.send(
                    "An unexpected error occurred.",
                    ephemeral=True,
                )


            except discord.HTTPException:

                logger.exception(
                    "Failed to send slash command error."
                )


        else:

            try:

                await interaction.response.send_message(
                    "An unexpected error occurred.",
                    ephemeral=True,
                )


            except discord.HTTPException:

                logger.exception(
                    "Failed to respond to slash command error."
                )


    def get_uptime(self) -> int:
        """
        Return the current bot uptime in seconds.
        """

        return int(
            time.time()
            - self.start_time
        )


    def get_uptime_formatted(self) -> str:
        """
        Return the current bot uptime in a readable format.

        Example:

            2d 4h 31m 12s
        """

        total_seconds = self.get_uptime()


        days, remainder = divmod(
            total_seconds,
            86400,
        )


        hours, remainder = divmod(
            remainder,
            3600,
        )


        minutes, seconds = divmod(
            remainder,
            60,
        )


        parts: list[str] = []


        if days:

            parts.append(
                f"{days}d"
            )


        if hours:

            parts.append(
                f"{hours}h"
            )


        if minutes:

            parts.append(
                f"{minutes}m"
            )


        parts.append(
            f"{seconds}s"
        )


        return " ".join(
            parts
        )


    def get_status_data(self) -> dict[str, object]:
        """
        Return a snapshot of the current bot state.

        This can later be used by:

        - Status commands
        - Health checks
        - Web dashboards
        - Monitoring systems
        """

        return {

            "name": BOT_NAME,

            "version": BOT_VERSION,

            "online": self.is_fully_ready,

            "connected": not self.is_closed(),

            "guilds": len(
                self.guilds
            ),

            "latency_ms": round(
                self.latency * 1000,
                2,
            ),

            "uptime_seconds": self.get_uptime(),

            "uptime": self.get_uptime_formatted(),

        }


    async def close(self) -> None:
        """
        Gracefully shut down PAG Core.

        Shutdown sequence:

            1. Prevent duplicate shutdown attempts
            2. Mark the application offline
            3. Close the database
            4. Close the Discord connection
            5. Log shutdown completion
        """

        if self.is_shutting_down:

            logger.warning(
                "Shutdown already in progress."
            )


            return


        self.is_shutting_down = True


        self.is_fully_ready = False


        logger.info(
            "PAG Core shutdown initiated."
        )


        try:

            await self.database.close()


        except Exception:

            logger.exception(
                "Database shutdown failed."
            )


        try:

            await super().close()


        except Exception:

            logger.exception(
                "Discord client shutdown failed."
            )


        logger.info(
            "PAG Core is now OFFLINE."
        )