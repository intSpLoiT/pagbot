"""
PAG Core
Main Application Entry Point

This file is the central entry point of the PAG Discord bot.

Architecture:

    main.py
        |
        ├── Configuration
        |
        ├── Logging
        |
        ├── Database
        |
        ├── Roblox Service
        |
        ├── Top 10 Service
        |
        ├── Extension Loader
        |
        └── Discord Bot
                |
                ├── Profile Cog
                ├── Role Info Cog
                ├── Top 10 Cog
                ├── Write Cog
                └── Announcement Cog


Startup flow:

    1. Load environment variables
    2. Validate configuration
    3. Initialize logging
    4. Initialize database
    5. Initialize shared services
    6. Create Discord bot
    7. Load extensions
    8. Sync application commands
    9. Connect to Discord
    10. Start the application


Shutdown flow:

    SIGINT / SIGTERM
        |
        v
    Close services
        |
        v
    Close Discord connection
        |
        v
    Exit cleanly
"""


from __future__ import annotations


import asyncio


import logging


import os


import signal


import sys


from pathlib import Path


from typing import Optional


import discord


from discord.ext import commands


from dotenv import load_dotenv


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


from core.logger import (
    logger,
)


from services.roblox_service import (
    RobloxService,
)


from services.top10_service import (
    Top10Service,
)


# ============================================================
# ENVIRONMENT
# ============================================================


load_dotenv()


DISCORD_TOKEN = (

    os.getenv(

        "DISCORD_TOKEN"

    )

)


if not DISCORD_TOKEN:

    raise RuntimeError(

        (

            "DISCORD_TOKEN is not configured. "

            "Add it to the .env file."

        )

    )


# ============================================================
# PATHS
# ============================================================


BASE_DIR = (

    Path(

        __file__

    ).resolve().parent

)


DATA_DIR = (

    BASE_DIR / "data"

)


COGS_DIR = (

    BASE_DIR / "cogs"

)


DATA_DIR.mkdir(

    parents=True,

    exist_ok=True,

)


# ============================================================
# EXTENSIONS
# ============================================================


EXTENSIONS = [

    "cogs.profile",

    "cogs.role_info",

    "cogs.top10",

    "cogs.write",

    "cogs.announcement",

]


# ============================================================
# BOT INTENTS
# ============================================================


INTENTS = discord.Intents.default()


INTENTS.guilds = True


INTENTS.members = True


INTENTS.messages = True


INTENTS.message_content = True


# ============================================================
# BOT CLASS
# ============================================================


class PAGBot(
    commands.Bot
):
    """
    Main PAG Discord bot.

    This class owns:

        - Discord connection
        - Shared services
        - Extension loading
        - Application command synchronization
        - Application lifecycle
    """


    def __init__(

        self,

    ) -> None:

        super().__init__(

            command_prefix="!",

            intents=INTENTS,

            help_command=None,

        )


        self.roblox_service: Optional[

            RobloxService

        ] = None


        self.top10_service: Optional[

            Top10Service

        ] = None


        self.loaded_extensions: list[

            str

        ] = []


        self.failed_extensions: dict[

            str,

            Exception

        ] = {}


        self.shutdown_event = asyncio.Event()


        self.startup_complete = False


        logger.info(

            (

                "%s v%s instance created."

            ),

            BOT_NAME,

            BOT_VERSION,

        )


    async def setup_hook(

        self,

    ) -> None:

        """
        Discord.py calls this before the bot connects.

        This is the ideal place for:

            - Service initialization
            - Extension loading
            - Command synchronization
        """

        logger.info(

            "Starting application setup."

        )


        await self.initialize_services()


        await self.load_extensions()


        await self.sync_commands()


        logger.info(

            "Application setup completed."

        )


    async def initialize_services(

        self,

    ) -> None:

        """
        Initialize shared application services.

        Shared services are attached to the bot
        so every Cog can access the same instance.

        This avoids creating multiple Roblox API
        clients or multiple database connections.
        """

        logger.info(

            "Initializing shared services."

        )


        # ----------------------------------------------------
        # Roblox Service
        # ----------------------------------------------------

        try:

            self.roblox_service = (

                RobloxService()

            )


            logger.info(

                "RobloxService initialized."

            )


        except Exception:

            logger.exception(

                "Failed to initialize RobloxService."

            )


            raise


        # ----------------------------------------------------
        # Top 10 Service
        # ----------------------------------------------------

        try:

            database_path = (

                DATA_DIR / "pag.db"

            )


            self.top10_service = (

                Top10Service(

                    database_path=str(

                        database_path

                    ),

                    roblox_service=(

                        self.roblox_service

                    ),

                )

            )


            logger.info(

                (

                    "Top10Service initialized. "

                    "Database: %s"

                ),

                database_path,

            )


        except Exception:

            logger.exception(

                "Failed to initialize Top10Service."

            )


            raise


        logger.info(

            "All shared services initialized."

        )


    async def load_extensions(

        self,

    ) -> None:

        """
        Load all Discord extensions.

        Every extension is loaded independently.

        This means one broken Cog does not hide
        the exact error behind a generic startup failure.

        Example:

            cogs.profile
            cogs.role_info
            cogs.top10
            cogs.write
            cogs.announcement
        """

        logger.info(

            (

                "Loading %d extensions."

            ),

            len(

                EXTENSIONS

            ),

        )


        for extension in EXTENSIONS:

            try:

                await self.load_extension(

                    extension

                )


                self.loaded_extensions.append(

                    extension

                )


                logger.info(

                    (

                        "Extension loaded: %s"

                    ),

                    extension,

                )


            except commands.ExtensionAlreadyLoaded:

                logger.warning(

                    (

                        "Extension already loaded: %s"

                    ),

                    extension,

                )


                self.loaded_extensions.append(

                    extension

                )


            except commands.ExtensionNotFound as error:

                self.failed_extensions[

                    extension

                ] = error


                logger.error(

                    (

                        "Extension not found: %s"

                    ),

                    extension,

                )


            except commands.NoEntryPointError as error:

                self.failed_extensions[

                    extension

                ] = error


                logger.error(

                    (

                        "Extension has no setup function: %s"

                    ),

                    extension,

                )


            except commands.ExtensionFailed as error:

                self.failed_extensions[

                    extension

                ] = error


                logger.exception(

                    (

                        "Extension failed during setup: %s"

                    ),

                    extension,

                )


            except Exception as error:

                self.failed_extensions[

                    extension

                ] = error


                logger.exception(

                    (

                        "Unexpected extension error: %s"

                    ),

                    extension,

                )


        logger.info(

            (

                "Extension loading finished. "

                "Loaded: %d | Failed: %d"

            ),

            len(

                self.loaded_extensions

            ),

            len(

                self.failed_extensions

            ),

        )


        if self.failed_extensions:

            logger.warning(

                (

                    "Some extensions failed to load."

                )

            )


    async def sync_commands(

        self,

    ) -> None:

        """
        Synchronize slash commands with Discord.
        """

        logger.info(

            "Synchronizing application commands."

        )


        try:

            synced = (

                await self.tree.sync()

            )


            logger.info(

                (

                    "Synchronized %d application commands."

                ),

                len(

                    synced

                ),

            )


        except Exception:

            logger.exception(

                (

                    "Application command synchronization failed."

                )

            )


    async def on_ready(

        self,

    ) -> None:

        """
        Called when the bot successfully connects.
        """

        if self.user is None:

            logger.warning(

                "Bot connected without user information."

            )


            return


        logger.info(

            (

                "Connected to Discord as %s "

                "(ID: %s)."

            ),

            self.user,

            self.user.id,

        )


        logger.info(

            (

                "Connected to %d guilds."

            ),

            len(

                self.guilds

            ),

        )


        activity = discord.Activity(

            type=discord.ActivityType.watching,

            name=(

                "PAG | /help"

            ),

        )


        await self.change_presence(

            status=discord.Status.online,

            activity=activity,

        )


        self.startup_complete = True


        logger.info(

            (

                "%s is now online."

            ),

            BOT_NAME,

        )


    async def on_disconnect(

        self,

    ) -> None:

        """
        Called when the bot disconnects.
        """

        logger.warning(

            "Disconnected from Discord."

        )


    async def on_resumed(

        self,

    ) -> None:

        """
        Called when the Discord connection resumes.
        """

        logger.info(

            "Discord connection resumed."

        )


    async def close(

        self,

    ) -> None:

        """
        Gracefully close all services.
        """

        logger.info(

            "Beginning graceful shutdown."

        )


        self.shutdown_event.set()


        # ----------------------------------------------------
        # Roblox Service
        # ----------------------------------------------------

        if self.roblox_service is not None:

            close_method = getattr(

                self.roblox_service,

                "close",

                None,

            )


            if close_method:

                try:

                    result = (

                        close_method()

                    )


                    if asyncio.iscoroutine(

                        result

                    ):

                        await result


                    logger.info(

                        "RobloxService closed."

                    )


                except Exception:

                    logger.exception(

                        (

                            "Error while closing "

                            "RobloxService."

                        )

                    )


        # ----------------------------------------------------
        # Top 10 Service
        # ----------------------------------------------------

        if self.top10_service is not None:

            close_method = getattr(

                self.top10_service,

                "close",

                None,

            )


            if close_method:

                try:

                    result = (

                        close_method()

                    )


                    if asyncio.iscoroutine(

                        result

                    ):

                        await result


                    logger.info(

                        "Top10Service closed."

                    )


                except Exception:

                    logger.exception(

                        (

                            "Error while closing "

                            "Top10Service."

                        )

                    )


        await super().close()


        logger.info(

            (

                "%s shutdown completed."

            ),

            BOT_NAME,

        )


# ============================================================
# SIGNAL HANDLING
# ============================================================


def install_signal_handlers(

    bot: PAGBot,

) -> None:

    """
    Register graceful shutdown handlers.

    SIGINT:

        Ctrl + C

    SIGTERM:

        Process termination
    """

    loop = asyncio.get_running_loop()


    def request_shutdown(

    ) -> None:

        logger.info(

            "Shutdown signal received."

        )


        asyncio.create_task(

            bot.close()

        )


    for signal_name in (

        signal.SIGINT,

        signal.SIGTERM,

    ):

        try:

            loop.add_signal_handler(

                signal_name,

                request_shutdown,

            )


        except NotImplementedError:

            # Windows compatibility

            logger.debug(

                (

                    "Signal handler unavailable "

                    "for %s."

                ),

                signal_name,

            )


# ============================================================
# APPLICATION RUNNER
# ============================================================


async def run_bot(

) -> None:

    """
    Start and run the PAG bot.
    """

    bot = (

        PAGBot()

    )


    install_signal_handlers(

        bot

    )


    try:

        await bot.start(

            DISCORD_TOKEN

        )


    except KeyboardInterrupt:

        logger.info(

            "Keyboard interrupt received."

        )


    except discord.LoginFailure:

        logger.critical(

            (

                "Discord login failed. "

                "Check the bot token."

            )

        )


    except discord.PrivilegedIntentsRequired:

        logger.critical(

            (

                "Privileged intents are required "

                "but are not enabled."

            )

        )


    except Exception:

        logger.exception(

            (

                "Fatal bot runtime error."

            )

        )


    finally:

        if not bot.is_closed():

            await bot.close()


# ============================================================
# ENTRY POINT
# ============================================================


def main(

) -> None:

    """
    Synchronous application entry point.
    """

    try:

        asyncio.run(

            run_bot()

        )


    except KeyboardInterrupt:

        logger.info(

            "Application stopped by user."

        )


    except Exception:

        logger.exception(

            (

                "Fatal application error."

            )

        )


        sys.exit(

            1

        )


if __name__ == "__main__":

    main()