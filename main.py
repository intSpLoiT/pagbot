from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Final

from flask import Flask, jsonify


# ============================================================
# PROJECT CONSTANTS
# ============================================================

PROJECT_ROOT: Final[Path] = (
    Path(__file__).resolve().parent
)

REQUIREMENTS_FILE: Final[Path] = (
    PROJECT_ROOT / "requirements.txt"
)

DEFAULT_PORT: Final[int] = 10000

LOG_BUFFER_SIZE: Final[int] = 100

STARTUP_TIMEOUT: Final[float] = 120.0

SHUTDOWN_TIMEOUT: Final[float] = 20.0


# ============================================================
# ENVIRONMENT HELPERS
# ============================================================

def get_port() -> int:
    """
    Render tarafından verilen PORT değişkenini alır.

    Render:
        PORT=10000

    Local:
        PORT yoksa 10000 kullanılır.
    """

    raw_port = os.getenv(
        "PORT",
        str(DEFAULT_PORT),
    ).strip()

    try:

        port = int(raw_port)

    except ValueError:

        port = DEFAULT_PORT

    if not 1 <= port <= 65535:

        return DEFAULT_PORT

    return port


# ============================================================
# RUNTIME DEPENDENCY BOOTSTRAP
# ============================================================

@dataclass(slots=True, frozen=True)
class DependencySpec:
    """
    Runtime dependency bilgisi.
    """

    package_name: str
    import_name: str


RUNTIME_DEPENDENCIES: Final[
    tuple[DependencySpec, ...]
] = (
    DependencySpec(
        package_name="flask",
        import_name="flask",
    ),
    DependencySpec(
        package_name="discord.py",
        import_name="discord",
    ),
    DependencySpec(
        package_name="aiosqlite",
        import_name="aiosqlite",
    ),
    DependencySpec(
        package_name="httpx",
        import_name="httpx",
    ),
    DependencySpec(
        package_name="python-dotenv",
        import_name="dotenv",
    ),
)


def _is_package_available(
    import_name: str,
) -> bool:
    """
    Bir Python paketinin import edilebilir olup
    olmadığını kontrol eder.
    """

    return (
        importlib.util.find_spec(
            import_name,
        )
        is not None
    )


def _install_package(
    package_name: str,
) -> None:
    """
    Eksik paketi mevcut Python interpreter'ı
    kullanarak yükler.
    """

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            package_name,
        ],
        cwd=PROJECT_ROOT,
    )


def ensure_runtime_dependencies() -> None:
    """
    Kritik paketler eksikse yüklemeyi dener.

    Öncelik:
        1. requirements.txt
        2. Eksik temel paketler için fallback

    Render'da normalde requirements.txt build
    sırasında kurulacağı için bu fonksiyon çoğunlukla
    herhangi bir işlem yapmaz.
    """

    missing_packages: list[str] = []

    for dependency in RUNTIME_DEPENDENCIES:

        if not _is_package_available(
            dependency.import_name,
        ):

            missing_packages.append(
                dependency.package_name,
            )

    if not missing_packages:

        return

    print(
        "Missing runtime dependencies detected:",
        ", ".join(missing_packages),
        flush=True,
    )

    # Öncelik requirements.txt
    if REQUIREMENTS_FILE.exists():

        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "-r",
                str(REQUIREMENTS_FILE),
            ],
            cwd=PROJECT_ROOT,
        )

    else:

        for package in missing_packages:

            _install_package(
                package,
            )


# ============================================================
# DEPENDENCY BOOTSTRAP
# ============================================================

# Flask import edilmeden önce dependency kontrolü
ensure_runtime_dependencies()


# ============================================================
# APPLICATION IMPORTS
# ============================================================

from flask import Response


# ============================================================
# LOG BUFFER
# ============================================================

class LogBuffer(logging.Handler):
    """
    Son log kayıtlarını RAM içinde tutar.

    Amaç:
        /logs endpoint'i üzerinden
        küçük bir debug çıktısı göstermek.
    """

    def __init__(
        self,
        max_entries: int = LOG_BUFFER_SIZE,
    ) -> None:

        super().__init__()

        self._records: deque[str] = deque(
            maxlen=max_entries,
        )

        self._lock = threading.Lock()

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
                "Failed to format log record."
            )

        with self._lock:

            self._records.append(
                message,
            )

    def get_logs(
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
# LOGGER
# ============================================================

class RuntimeLogger:
    """
    Console + RAM log buffer kullanan logger sistemi.
    """

    def __init__(self) -> None:

        self.logger = logging.getLogger(
            "PAG",
        )

        self.logger.setLevel(
            logging.INFO,
        )

        self.logger.propagate = False

        self.log_buffer = LogBuffer(
            max_entries=LOG_BUFFER_SIZE,
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

        self.log_buffer.setFormatter(
            formatter,
        )

        # Duplicate handler önleme
        if not self.logger.handlers:

            console_handler = (
                logging.StreamHandler(
                    sys.stdout,
                )
            )

            console_handler.setLevel(
                logging.INFO,
            )

            console_handler.setFormatter(
                formatter,
            )

            self.logger.addHandler(
                console_handler,
            )

            self.logger.addHandler(
                self.log_buffer,
            )

        else:

            # Eğer logger daha önce oluşturulduysa
            # log buffer handler'ını eksikse ekle.
            if self.log_buffer not in (
                self.logger.handlers
            ):

                self.logger.addHandler(
                    self.log_buffer,
                )


# ============================================================
# GLOBAL APPLICATION STATE
# ============================================================

_runtime_logger: RuntimeLogger | None = None

_shutdown_event: asyncio.Event | None = None

_bot = None

_bot_ready: bool = False

_bot_started_at: float | None = None

_http_server_started_at: float | None = None


# ============================================================
# LOGGER ACCESSOR
# ============================================================

def get_logger() -> logging.Logger:
    """
    PAG logger'ını döndürür.
    """

    if _runtime_logger is None:

        raise RuntimeError(
            "Runtime logger has not been initialized."
        )

    return _runtime_logger.logger


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(
    "pag-bot-health",
)


# ============================================================
# HEALTH ROUTE
# ============================================================

@app.get("/")
def index() -> Response:
    """
    Ana health endpoint.
    """

    return jsonify(
        {
            "service": "PAG Bot",
            "status": "online",
            "bot_ready": _bot_ready,
            "uptime": _get_uptime(),
        }
    )


# ============================================================
# HEALTH ROUTE
# ============================================================

@app.get("/health")
def health() -> Response:
    """
    Render health check endpoint'i.
    """

    if _bot_ready:

        return jsonify(
            {
                "status": "healthy",
                "bot": "ready",
                "uptime": _get_uptime(),
            }
        ), 200

    return jsonify(
        {
            "status": "starting",
            "bot": "starting",
            "uptime": _get_uptime(),
        }
    ), 200


# ============================================================
# LOG ROUTE
# ============================================================

@app.get("/logs")
def logs() -> Response:
    """
    Son RAM loglarını döndürür.
    """

    if _runtime_logger is None:

        return jsonify(
            {
                "logs": [],
            }
        )

    return jsonify(
        {
            "logs": (
                _runtime_logger
                .log_buffer
                .get_logs()
            ),
        }
    )


# ============================================================
# STATUS ROUTE
# ============================================================

@app.get("/status")
def status() -> Response:
    """
    Botun mevcut durumunu döndürür.
    """

    return jsonify(
        {
            "service": "PAG Bot",
            "bot_ready": _bot_ready,
            "bot_started": (
                _bot is not None
            ),
            "uptime": _get_uptime(),
        }
    )


# ============================================================
# UPTIME
# ============================================================

def _get_uptime() -> int:
    """
    Process uptime'ını saniye olarak döndürür.
    """

    if _http_server_started_at is None:

        return 0

    return max(
        0,
        int(
            time.monotonic()
            - _http_server_started_at
        ),
    )


# ============================================================
# WEB SERVER
# ============================================================

def run_web_server(
    port: int,
) -> None:
    """
    Flask health server'ını başlatır.

    Flask development reloader kapalıdır.
    Aksi halde Render'da ikinci process oluşabilir.
    """

    global _http_server_started_at

    _http_server_started_at = (
        time.monotonic()
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# ============================================================
# SIGNAL HANDLER
# ============================================================

def _handle_shutdown_signal(
    signal_number: int,
    frame: FrameType | None,
) -> None:
    """
    SIGINT / SIGTERM sinyallerini yakalar.
    """

    event = _shutdown_event

    if event is None:

        return

    if event.is_set():

        return

    event.set()


# ============================================================
# SIGNAL REGISTRATION
# ============================================================

def _register_signal_handlers(
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

            signal.signal(
                sig,
                _handle_shutdown_signal,
            )


# ============================================================
# BOT CREATION
# ============================================================

def _create_bot(
    config,
    logger: logging.Logger,
):
    """
    PAGBot instance'ı oluşturur.

    Import burada yapılır.
    Böylece başlangıçta bütün bot modülleri
    main.py import edilir edilmez yüklenmez.
    """

    from core.bot import PAGBot

    return PAGBot(
        config=config,
        logger=logger,
    )


# ============================================================
# BOT RUNNER
# ============================================================

async def run_bot() -> None:
    """
    Discord bot yaşam döngüsü.
    """

    global _bot
    global _bot_ready
    global _bot_started_at

    from config.config import load_config

    config = load_config()

    logger = get_logger()

    logger.info(
        "Loading PAG Bot...",
    )

    _bot = _create_bot(
        config=config,
        logger=logger,
    )

    _bot_started_at = (
        time.monotonic()
    )

    try:

        logger.info(
            "Connecting to Discord...",
        )

        await _bot.start(
            config.discord_token,
        )

        _bot_ready = False

    except asyncio.CancelledError:

        logger.info(
            "Bot task cancelled.",
        )

        raise

    except Exception:

        _bot_ready = False

        logger.exception(
            "Fatal bot error.",
        )

        raise

    finally:

        _bot_ready = False

        if _bot is not None:

            try:

                await asyncio.wait_for(
                    _bot.close(),
                    timeout=SHUTDOWN_TIMEOUT,
                )

            except asyncio.TimeoutError:

                logger.error(
                    "Bot shutdown timed out.",
                )

            except Exception:

                logger.exception(
                    "Failed to close bot cleanly.",
                )

        logger.info(
            "PAG Bot stopped.",
        )


# ============================================================
# MAIN ASYNC APPLICATION
# ============================================================

async def async_main() -> None:
    """
    Ana async uygulama.
    """

    global _shutdown_event

    _shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    _register_signal_handlers(
        loop,
    )

    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    from config.config import load_config

    config = load_config()

    # --------------------------------------------------------
    # LOGGER
    # --------------------------------------------------------

    logger = get_logger()

    logger.info(
        "Starting PAG Bot application...",
    )

    logger.info(
        "Python version: %s",
        sys.version.split()[0],
    )

    logger.info(
        "HTTP health server will listen on port %s.",
        get_port(),
    )

    # --------------------------------------------------------
    # WEB SERVER
    # --------------------------------------------------------

    web_thread = threading.Thread(
        target=run_web_server,
        args=(
            get_port(),
        ),
        name="PAG-Health-Server",
        daemon=True,
    )

    web_thread.start()

    logger.info(
        "Health server started.",
    )

    # --------------------------------------------------------
    # BOT TASK
    # --------------------------------------------------------

    bot_task = asyncio.create_task(
        run_bot(),
        name="PAG-Discord-Bot",
    )

    shutdown_task = asyncio.create_task(
        _shutdown_event.wait(),
        name="PAG-Shutdown-Watcher",
    )

    try:

        done, pending = await asyncio.wait(
            (
                bot_task,
                shutdown_task,
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )

        # ----------------------------------------------------
        # BOT CRASHED
        # ----------------------------------------------------

        if bot_task in done:

            exception = (
                bot_task.exception()
            )

            if exception is not None:

                logger.error(
                    "Discord bot stopped unexpectedly.",
                )

                raise exception

        # ----------------------------------------------------
        # SHUTDOWN SIGNAL
        # ----------------------------------------------------

        if shutdown_task in done:

            logger.info(
                "Shutdown signal received.",
            )

            if not bot_task.done():

                bot_task.cancel()

                try:

                    await asyncio.wait_for(
                        bot_task,
                        timeout=SHUTDOWN_TIMEOUT,
                    )

                except (
                    asyncio.CancelledError,
                    asyncio.TimeoutError,
                ):

                    pass

    finally:

        for task in (
            bot_task,
            shutdown_task,
        ):

            if not task.done():

                task.cancel()

        await asyncio.gather(
            bot_task,
            shutdown_task,
            return_exceptions=True,
        )

        logger.info(
            "Application shutdown completed.",
        )


# ============================================================
# SYNCHRONOUS ENTRYPOINT
# ============================================================

def main() -> None:
    """
    Uygulama giriş noktası.
    """

    try:

        ensure_runtime_dependencies()

        asyncio.run(
            async_main(),
        )

    except KeyboardInterrupt:

        print(
            "PAG Bot stopped by user.",
            flush=True,
        )

        raise SystemExit(
            0,
        )

    except Exception as error:

        print(
            f"PAG Bot startup failed: {error}",
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