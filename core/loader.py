# core/loader.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from discord.ext import commands


if TYPE_CHECKING:

    from core.bot import PAGBot


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT: Final[
    Path
] = Path(__file__).resolve().parent.parent


COGS_DIR: Final[
    Path
] = PROJECT_ROOT / "cogs"


# ============================================================
# COG LOADER
# ============================================================

class CogLoader:
    """
    PAG Bot otomatik Cog Loader.

    cogs/ klasöründeki Python dosyalarını
    otomatik olarak bulur ve yükler.

    Örnek:

        cogs/
        ├── announcement.py
        ├── blacklist.py
        ├── general.py
        ├── profile.py
        ├── roblox.py
        ├── role_info.py
        ├── say.py
        ├── system.py
        ├── top_10.py
        ├── verify.py
        ├── write.py
        └── top10_service.py

    Otomatik olarak:

        cogs.announcement
        cogs.blacklist
        cogs.general
        cogs.profile
        cogs.roblox
        cogs.role_info
        cogs.say
        cogs.system
        cogs.top_10
        cogs.verify
        cogs.write

    yüklenir.

    Service dosyaları:

        top10_service.py
        event_service.py
        roblox_service.py

    gibi dosyalar Cog olmadığı için atlanır.
    """

    # ========================================================
    # IGNORED FILES
    # ========================================================

    IGNORED_FILES: Final[
        frozenset[str]
    ] = frozenset(
        {
            "__init__.py",
        }
    )

    # ========================================================
    # IGNORED KEYWORDS
    # ========================================================

    IGNORED_KEYWORDS: Final[
        tuple[str, ...]
    ] = (
        "service",
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

        self._extensions: tuple[
            str,
            ...
        ] = ()

    # ========================================================
    # DISCOVER COGS
    # ========================================================

    def discover_cogs(
        self,
    ) -> tuple[str, ...]:
        """
        cogs/ klasöründeki geçerli Cog dosyalarını
        otomatik olarak bulur.

        Sadece:

            *.py

        dosyaları değerlendirilir.

        Atlananlar:

            __init__.py
            service içeren dosyalar
            özel Python dosyaları
            klasörler
        """

        if not COGS_DIR.exists():

            self.logger.warning(
                "Cogs directory does not exist: %s",
                COGS_DIR,
            )

            return ()

        if not COGS_DIR.is_dir():

            self.logger.error(
                "Cogs path is not a directory: %s",
                COGS_DIR,
            )

            return ()

        discovered: list[str] = []

        for file_path in sorted(
            COGS_DIR.iterdir(),
            key=lambda path: path.name.lower(),
        ):

            # ------------------------------------------------
            # ONLY FILES
            # ------------------------------------------------

            if not file_path.is_file():

                continue

            # ------------------------------------------------
            # ONLY PYTHON FILES
            # ------------------------------------------------

            if file_path.suffix != ".py":

                continue

            file_name = file_path.name

            # ------------------------------------------------
            # IGNORED FILES
            # ------------------------------------------------

            if file_name in self.IGNORED_FILES:

                self.logger.debug(
                    "Ignoring special file: %s",
                    file_name,
                )

                continue

            # ------------------------------------------------
            # SERVICE FILES
            # ------------------------------------------------

            file_name_lower = (
                file_name.lower()
            )

            if any(
                keyword in file_name_lower
                for keyword in self.IGNORED_KEYWORDS
            ):

                self.logger.debug(
                    "Ignoring service file: %s",
                    file_name,
                )

                continue

            # ------------------------------------------------
            # MODULE NAME
            # ------------------------------------------------

            module_name = (
                file_path.stem
            )

            # ------------------------------------------------
            # PYTHON MODULE VALIDATION
            # ------------------------------------------------

            if not module_name.isidentifier():

                self.logger.warning(
                    (
                        "Ignoring invalid Python "
                        "module filename: %s"
                    ),
                    file_name,
                )

                continue

            extension = (
                f"cogs.{module_name}"
            )

            discovered.append(
                extension,
            )

        extensions = tuple(
            discovered,
        )

        self._extensions = extensions

        self.logger.info(
            "Discovered %s Cog(s).",
            len(extensions),
        )

        for extension in extensions:

            self.logger.debug(
                "Discovered Cog: %s",
                extension,
            )

        return extensions

    # ========================================================
    # LOAD ALL
    # ========================================================

    async def load_all(
        self,
    ) -> None:
        """
        Bulunan bütün Cog'ları sırayla yükler.

        Aynı Cog daha önce yüklenmişse
        tekrar yüklenmez.

        Böylece:

            CommandAlreadyRegistered

        gibi gereksiz duplicate yükleme hataları
        engellenir.
        """

        extensions = (
            self.discover_cogs()
        )

        if not extensions:

            self.logger.warning(
                "No Cog files discovered.",
            )

            return

        for extension in extensions:

            # ------------------------------------------------
            # ALREADY LOADED
            # ------------------------------------------------

            if extension in self.bot.extensions:

                self.logger.warning(
                    "Cog already loaded: %s",
                    extension,
                )

                continue

            # ------------------------------------------------
            # LOAD
            # ------------------------------------------------

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

                continue

            except commands.NoEntryPointError:

                self.logger.exception(
                    (
                        "Cog setup() not found: "
                        "%s"
                    ),
                    extension,
                )

                continue

            except commands.ExtensionFailed:

                self.logger.exception(
                    (
                        "Cog failed to load: "
                        "%s"
                    ),
                    extension,
                )

                continue

            except Exception:

                self.logger.exception(
                    (
                        "Unexpected error while "
                        "loading Cog: %s"
                    ),
                    extension,
                )

                continue

    # ========================================================
    # UNLOAD ALL
    # ========================================================

    async def unload_all(
        self,
    ) -> None:
        """
        Yüklenmiş bütün Cog'ları ters sırayla
        güvenli şekilde kaldırır.
        """

        extensions = (
            self._extensions
        )

        for extension in reversed(
            extensions,
        ):

            if (
                extension
                not in self.bot.extensions
            ):

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
                    (
                        "Failed to unload "
                        "Cog: %s"
                    ),
                    extension,
                )

    # ========================================================
    # LOADED COG COUNT
    # ========================================================

    def loaded_count(
        self,
    ) -> int:
        """
        Aktif yüklenmiş Cog sayısını döndürür.
        """

        return len(
            self.bot.extensions,
        )

    # ========================================================
    # DISCOVERED COG COUNT
    # ========================================================

    def discovered_count(
        self,
    ) -> int:
        """
        Son taramada bulunan Cog sayısını
        döndürür.
        """

        return len(
            self._extensions,
        )

    # ========================================================
    # LOADED EXTENSIONS
    # ========================================================

    def loaded_extensions(
        self,
    ) -> tuple[str, ...]:
        """
        Aktif yüklü Cog listesini döndürür.
        """

        return tuple(
            self.bot.extensions.keys(),
        )