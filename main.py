from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
import time
from types import FrameType
from typing import Final

from flask import Flask
from flask import Response
from flask import jsonify

from config.config import load_config
from core.bot import PAGBot
from core.logger import setup_logger


# ============================================================
# APPLICATION CONSTANTS
# ============================================================

DEFAULT_PORT: Final[int] = 10000

WEB_SERVER_START_TIMEOUT: Final[float] = 10.0

BOT_RESTART_DELAY: Final[float] = 10.0

MAX_BOT_RESTART_DELAY: Final[float] = 60.0

SHUTDOWN_TIMEOUT: Final[float] = 20.0

LOG_BUFFER_SIZE: Final[int] = 100


# ============================================================
# GLOBAL APPLICATION STATE
# ============================================================

_shutdown_event: asyncio.Event | None = None

_bot: PAGBot | None = None

_logger: logging.Logger | None = None

_application_started_at: float | None = None

_bot_started_at: float | None = None

_bot_ready: bool = False

_shutdown_requested: bool = False

_web_server_started: bool = False


# ============================================================
# IN-MEMORY LOG BUFFER
# ============================================================

class MemoryLogHandler(logging.Handler):
    """
    Son log kayıtlarını RAM içerisinde tutar.

    Amaç:
        /logs endpoint'i üzerinden
        küçük bir debug çıktısı sunmak.

    Disk kullanımını artırmaz.
    """

    def __init__(
        self,
        max_entries: int = LOG_BUFFER_SIZE,
    ) -> None:

        super().__init__()

        self._records: list[str] = []

        self._max_entries = max(
            1,
            max_entries,
        )

        self._lock = threading.RLock()

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:

        try:

            message = self.format(
                record,
            )

        except Exception:

            message = (
                "Unable to format log record."
            )

        with self._lock:

            self._records.append(
                message,
            )

            if len(
                self._records,
            ) > self._max_entries:

                del self._records[
                    :-self._max_entries
                ]

    def get_records(
        self,
    ) -> list[str]:

        with self._lock:

            return list(
                self._records,
            )

    def clear(self) -> None:

        with self._lock:

            self._records.clear()


# ============================================================
# RUNTIME LOGGING
# ============================================================

_memory_log_handler: MemoryLogHandler | None = None


def initialize_logger(
    log_file=None,
) -> logging.Logger:
    """
    PAG logger'ını başlatır.

    core.logger.setup_logger mevcut sistemin
    ana logger setup fonksiyonudur.

    Burada yalnızca RAM log buffer eklenir.
    """

    global _logger
    global _memory_log_handler

    if _logger is not None:

        return _logger

    logger = setup_logger(
        name="PAG",
        log_file=log_file,
    )

    memory_handler = (
        MemoryLogHandler(
            max_entries=LOG_BUFFER_SIZE,
        )
    )

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)-8s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt=(
            "%Y-%m-%d %H:%M:%S"
        ),
    )

    memory_handler.setFormatter(
        formatter,
    )

    logger.addHandler(
        memory_handler,
    )

    _memory_log_handler = (
        memory_handler
    )

    _logger = logger

    return logger


def get_logger() -> logging.Logger:
    """
    Başlatılmış PAG logger'ını döndürür.
    """

    if _logger is None:

        raise RuntimeError(
            "PAG logger has not been initialized."
        )

    return _logger


# ============================================================
# ENVIRONMENT
# ============================================================

def get_port() -> int:
    """
    Hosting platformunun PORT değişkenini alır.

    Render:
        PORT=10000

    Local:
        PORT yoksa 10000 kullanılır.
    """

    import os

    raw_port = os.getenv(
        "PORT",
        str(DEFAULT_PORT),
    ).strip()

    try:

        port = int(
            raw_port,
        )

    except (
        TypeError,
        ValueError,
    ):

        return DEFAULT_PORT

    if not 1 <= port <= 65535:

        return DEFAULT_PORT

    return port


# ============================================================
# UPTIME
# ============================================================

def get_uptime() -> int:
    """
    Uygulamanın çalışma süresini saniye
    olarak döndürür.
    """

    if _application_started_at is None:

        return 0

    return max(
        0,
        int(
            time.monotonic()
            - _application_started_at,
        ),
    )


# ============================================================
# FLASK HEALTH SERVER
# ============================================================

app = Flask(
    "pag-health",
)


@app.get("/")
def index() -> Response:
    """
    Ana health endpoint.
    """

    return jsonify(
        {
            "service": "PAG Bot",
            "status": (
                "online"
                if _bot_ready
                else "starting"
            ),
            "bot_ready": _bot_ready,
            "uptime": get_uptime(),
        }
    )


@app.get("/health")
def health() -> Response:
    """
    Hosting health check endpoint'i.
    """

    if _bot_ready:

        return jsonify(
            {
                "status": "healthy",
                "bot": "ready",
                "uptime": get_uptime(),
            }
        ), 200

    return jsonify(
        {
            "status": "starting",
            "bot": "starting",
            "uptime": get_uptime(),
        }
    ), 200


@app.get("/status")
def status() -> Response:
    """
    Botun mevcut durumunu döndürür.
    """

    return jsonify(
        {
            "service": "PAG Bot",
            "bot_created": (
                _bot is not None
            ),
            "bot_ready": _bot_ready,
            "shutdown_requested": (
                _shutdown_requested
            ),
            "web_server_started": (
                _web_server_started
            ),
            "uptime": get_uptime(),
        }
    )


@app.get("/logs")
def logs() -> Response:
    """
    Son RAM loglarını döndürür.
    """

    if _memory_log_handler is None:

        return jsonify(
            {
                "logs": [],
            }
        )

    return jsonify(
        {
            "logs": (
                _memory_log_handler
                .get_records()
            ),
        }
    )


def run_web_server(
    port: int,
) -> None:
    """
    Health server'ı çalıştırır.

    Reloader kapalıdır.
    Böylece ikinci bir process oluşturulmaz.
    """

    global _web_server_started

    try:

        _web_server_started = True

        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    except Exception as error:

        _web_server_started = False

        logger = _logger

        if logger is not None:

            logger.exception(
                "Health server crashed: %s",
                error,
            )


def start_web_server() -> threading.Thread:
    """
    Flask health server'ını daemon thread olarak başlatır.
    """

    port = get_port()

    web_thread = threading.Thread(
        target=run_web_server,
        args=(
            port,
        ),
        name="PAG-Health-Server",
        daemon=True,
    )

    web_thread.start()

    return web_thread


# ============================================================
# SIGNAL HANDLING
# ============================================================

def _handle_shutdown_signal(
    signal_number: int,
    frame: FrameType | None,
) -> None:
    """
    SIGINT / SIGTERM sinyallerini yakalar.
    """

    global _shutdown_requested

    _shutdown_requested = True

    event = _shutdown_event

    if event is None:

        return

    try:

        loop = event._loop

    except AttributeError:

        return

    if loop.is_closed():

        return

    try:

        loop.call_soon_threadsafe(
            event.set,
        )

    except RuntimeError:

        return


def register_signal_handlers(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    İşletim sistemi sinyallerini kaydeder.
    """

    event = _shutdown_event

    if event is None:

        return

    for sig in (
        signal.SIGINT,
        signal.SIGTERM,
    ):

        try:

            loop.add_signal_handler(
                sig,
                event.set,
            )

        except (
            NotImplementedError,
            RuntimeError,
        ):

            try:

                signal.signal(
                    sig,
                    _handle_shutdown_signal,
                )

            except (
                ValueError,
                OSError,
            ):

                # Bazı hosting ortamlarında
                # signal kurulumu desteklenmeyebilir.
                pass


# ============================================================
# BOT STATE
# ============================================================

def update_bot_ready_state() -> bool:
    """
    Botun hazır olup olmadığını kontrol eder.
    """

    global _bot_ready

    if _bot is None:

        _bot_ready = False

        return False

    try:

        is_ready = getattr(
            _bot,
            "is_ready",
            None,
        )

        if callable(
            is_ready,
        ):

            _bot_ready = bool(
                is_ready(),
            )

            return _bot_ready

    except Exception:

        _bot_ready = False

        return False

    _bot_ready = False

    return False


# ============================================================
# BOT SHUTDOWN
# ============================================================

async def close_bot() -> None:
    """
    Botu güvenli şekilde kapatır.
    """

    global _bot
    global _bot_ready

    _bot_ready = False

    if _bot is None:

        return

    try:

        is_closed = getattr(
            _bot,
            "is_closed",
            None,
        )

        if callable(
            is_closed,
        ):

            if is_closed():

                return

        await asyncio.wait_for(
            _bot.close(),
            timeout=SHUTDOWN_TIMEOUT,
        )

    except asyncio.TimeoutError:

        logger = _logger

        if logger is not None:

            logger.error(
                "Bot shutdown timed out.",
            )

    except asyncio.CancelledError:

        raise

    except Exception:

        logger = _logger

        if logger is not None:

            logger.exception(
                "Failed to close bot cleanly.",
            )


# ============================================================
# BOT RUNNER
# ============================================================

async def run_bot_once() -> None:
    """
    Botu tek bir kez başlatır.

    Bot class'ı burada oluşturulur.
    """

    global _bot
    global _bot_ready
    global _bot_started_at

    config = load_config()

    logger = get_logger()

    logger.info(
        "Creating PAG Bot instance...",
    )

    _bot = PAGBot(
        config=config,
        logger=logger,
    )

    _bot_started_at = (
        time.monotonic()
    )

    logger.info(
        "Connecting to Discord...",
    )

    try:

        await _bot.start(
            config.discord_token,
        )

    except asyncio.CancelledError:

        logger.info(
            "Bot task cancelled.",
        )

        raise

    except Exception:

        logger.exception(
            "PAG Bot encountered an unexpected error.",
        )

        raise

    finally:

        _bot_ready = False

        await close_bot()

        logger.info(
            "PAG Bot stopped.",
        )


# ============================================================
# BOT SUPERVISOR
# ============================================================

async def run_bot_supervisor() -> None:
    """
    Botu izler.

    Beklenmedik kapanma olursa:
        10 saniye bekler.
        Sonra tekrar başlatır.

    Her başarısız denemede bekleme süresi
    kontrollü şekilde artırılır.

    Shutdown sinyali geldiyse yeniden başlatmaz.
    """

    logger = get_logger()

    restart_delay = BOT_RESTART_DELAY

    while not _shutdown_requested:

        try:

            logger.info(
                "Starting PAG Bot...",
            )

            await run_bot_once()

            if _shutdown_requested:

                break

            logger.warning(
                "PAG Bot stopped unexpectedly.",
            )

        except asyncio.CancelledError:

            logger.info(
                "PAG Bot supervisor cancelled.",
            )

            raise

        except Exception:

            logger.exception(
                "PAG Bot crashed unexpectedly.",
            )

        if _shutdown_requested:

            break

        logger.warning(
            "Bot will restart in %.1f seconds.",
            restart_delay,
        )

        try:

            await asyncio.sleep(
                restart_delay,
            )

        except asyncio.CancelledError:

            raise

        restart_delay = min(
            restart_delay * 2,
            MAX_BOT_RESTART_DELAY,
        )

    logger.info(
        "PAG Bot supervisor stopped.",
    )


# ============================================================
# BOT READY MONITOR
# ============================================================

async def ready_monitor() -> None:
    """
    Botun hazır durumunu takip eder.

    Discord bağlantısı hazır olduğunda:
        /health -> healthy
    """

    global _bot_ready

    while not _shutdown_requested:

        update_bot_ready_state()

        try:

            await asyncio.sleep(
                1.0,
            )

        except asyncio.CancelledError:

            break

    _bot_ready = False


# ============================================================
# ASYNC APPLICATION
# ============================================================

async def run_application() -> None:
    """
    PAG Bot uygulamasının ana async lifecycle'ı.
    """

    global _shutdown_event
    global _application_started_at

    _application_started_at = (
        time.monotonic()
    )

    _shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    register_signal_handlers(
        loop,
    )

    config = load_config()

    logger = initialize_logger(
        log_file=config.log_file_path,
    )

    logger.info(
        "========================================",
    )

    logger.info(
        "Starting PAG Bot",
    )

    logger.info(
        "Python: %s",
        sys.version.split()[0],
    )

    logger.info(
        "Port: %s",
        get_port(),
    )

    logger.info(
        "========================================",
    )

    # --------------------------------------------------------
    # WEB SERVER
    # --------------------------------------------------------

    web_thread = start_web_server()

    logger.info(
        "Health server started.",
    )

    # --------------------------------------------------------
    # BOT TASK
    # --------------------------------------------------------

    bot_task = asyncio.create_task(
        run_bot_supervisor(),
        name="PAG-Bot-Supervisor",
    )

    ready_task = asyncio.create_task(
        ready_monitor(),
        name="PAG-Bot-Ready-Monitor",
    )

    shutdown_task = asyncio.create_task(
        _shutdown_event.wait(),
        name="PAG-Shutdown-Watcher",
    )

    try:

        done, pending = await asyncio.wait(
            (
                bot_task,
                ready_task,
                shutdown_task,
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_task in done:

            logger.info(
                "Shutdown signal received.",
            )

        if bot_task in done:

            if not bot_task.cancelled():

                exception = (
                    bot_task.exception()
                )

                if exception is not None:

                    logger.exception(
                        "Bot supervisor stopped.",
                        exc_info=exception,
                    )

        if ready_task in done:

            if not ready_task.cancelled():

                exception = (
                    ready_task.exception()
                )

                if exception is not None:

                    logger.exception(
                        "Ready monitor stopped.",
                        exc_info=exception,
                    )

    except asyncio.CancelledError:

        logger.info(
            "Application task cancelled.",
        )

        raise

    except Exception:

        logger.exception(
            "Unexpected application error.",
        )

    finally:

        global _shutdown_requested

        _shutdown_requested = True

        _shutdown_event.set()

        logger.info(
            "Beginning graceful shutdown...",
        )

        tasks = (
            bot_task,
            ready_task,
            shutdown_task,
        )

        for task in tasks:

            if not task.done():

                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        await close_bot()

        if web_thread.is_alive():

            logger.info(
                "Health server thread is still running "
                "as daemon.",
            )

        logger.info(
            "PAG Bot shutdown completed.",
        )


# ============================================================
# SYNCHRONOUS ENTRYPOINT
# ============================================================

def main() -> None:
    """
    Uygulamanın ana giriş noktası.
    """

    try:

        asyncio.run(
            run_application(),
        )

    except KeyboardInterrupt:

        print(
            "PAG Bot stopped by user.",
            flush=True,
        )

        raise SystemExit(
            0,
        )

    except SystemExit:

        raise

    except Exception as error:

        print(
            (
                "PAG Bot encountered an unrecoverable "
                f"startup error: {error}"
            ),
            file=sys.stderr,
            flush=True,
        )

        raise SystemExit(
            1,
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()