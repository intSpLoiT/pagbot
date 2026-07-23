from __future__ import annotations

import asyncio
import logging
import signal
import sys
from types import FrameType

from config.config import load_config
from core.bot import PAGBot
from core.logger import setup_logger


# ============================================================
# GLOBAL STATE
# ============================================================

_shutdown_event: asyncio.Event | None = None
_bot: PAGBot | None = None


# ============================================================
# SIGNAL HANDLER
# ============================================================

def _handle_shutdown_signal(
    signal_number: int,
    frame: FrameType | None,
) -> None:
    """
    İşletim sistemi kapanış sinyallerini yakalar.
    """

    if _shutdown_event is None:
        return

    _shutdown_event.set()


# ============================================================
# SIGNAL REGISTRATION
# ============================================================

def _register_signal_handlers(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Kontrollü kapanış sinyallerini kaydeder.
    """

    signals = (
        signal.SIGINT,
        signal.SIGTERM,
    )

    for sig in signals:

        try:

            loop.add_signal_handler(
                sig,
                _shutdown_event.set,
            )

        except (
            NotImplementedError,
            RuntimeError,
        ):

            signal.signal(
                sig,
                _handle_shutdown_signal,
            )


# ============================================================
# BOT RUNNER
# ============================================================

async def run_bot() -> None:
    """
    PAG Bot ana çalışma akışı.

    Config
        ↓
    Logger
        ↓
    PAGBot
        ↓
    Discord
        ↓
    Kontrollü kapanış
    """

    global _shutdown_event
    global _bot

    # ========================================================
    # CONFIG
    # ========================================================

    config = load_config()

    # ========================================================
    # LOGGER
    # ========================================================

    logger: logging.Logger = setup_logger(
        name="PAG",
        log_file=config.log_file_path,
    )

    logger.info(
        "Starting PAG Bot...",
    )

    # ========================================================
    # SHUTDOWN EVENT
    # ========================================================

    _shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    _register_signal_handlers(
        loop,
    )

    # ========================================================
    # BOT
    # ========================================================

    _bot = PAGBot(
        config=config,
        logger=logger,
    )

    try:

        logger.info(
            "Connecting to Discord...",
        )

        await _bot.start(
            config.discord_token,
        )

    except asyncio.CancelledError:

        logger.info(
            "Bot task cancelled.",
        )

        raise

    except KeyboardInterrupt:

        logger.info(
            "Keyboard interrupt received.",
        )

    except Exception:

        logger.exception(
            "Fatal bot error.",
        )

        raise

    finally:

        if _bot is not None:

            try:

                await _bot.close()

            except Exception:

                logger.exception(
                    "Failed to close bot cleanly.",
                )

        logger.info(
            "PAG Bot stopped.",
        )


# ============================================================
# APPLICATION ENTRYPOINT
# ============================================================

def main() -> None:
    """
    Uygulamanın ana giriş noktası.
    """

    try:

        asyncio.run(
            run_bot(),
        )

    except KeyboardInterrupt:

        sys.exit(
            0,
        )

    except Exception:

        sys.exit(
            1,
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()