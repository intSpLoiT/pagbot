from __future__ import annotations

import logging

from core.database import Database


# ============================================================
# MIGRATION ERROR
# ============================================================

class MigrationError(Exception):
    """
    Database migration işlemleri sırasında oluşan hata.
    """

    pass


# ============================================================
# MIGRATION MANAGER
# ============================================================

class MigrationManager:
    """
    PAG Bot database migration yöneticisi.

    Migration'lar versiyon sırasına göre çalışır.

    Örnek:

        Version 0
            ↓
        Migration V1
            ↓
        Version 1
            ↓
        Migration V2
            ↓
        Version 2
    """

    CURRENT_VERSION = 2

    def __init__(
        self,
        database: Database,
        logger: logging.Logger | None = None,
    ) -> None:

        self.database = database

        self.logger = logger

    # ========================================================
    # RUN
    # ========================================================

    async def run(
        self,
    ) -> None:
        """
        Gerekli migration'ları sırayla çalıştırır.
        """

        try:

            # ------------------------------------------------
            # VERSION TABLE
            # ------------------------------------------------

            await self._ensure_version_table()

            # ------------------------------------------------
            # CURRENT VERSION
            # ------------------------------------------------

            current_version = (
                await self._get_current_version()
            )

            # ------------------------------------------------
            # DATABASE VERSION CHECK
            # ------------------------------------------------

            if current_version > self.CURRENT_VERSION:

                raise MigrationError(
                    "Database version is newer than "
                    "the supported bot version."
                )

            # ------------------------------------------------
            # MIGRATION V1
            # ------------------------------------------------

            if current_version < 1:

                self._log(
                    logging.INFO,
                    "Running database migration V1.",
                )

                await self._migration_v1()

                await self._set_version(
                    1,
                )

                current_version = 1

            # ------------------------------------------------
            # MIGRATION V2
            # ------------------------------------------------

            if current_version < 2:

                self._log(
                    logging.INFO,
                    "Running database migration V2.",
                )

                await self._migration_v2()

                await self._set_version(
                    2,
                )

                current_version = 2

            # ------------------------------------------------
            # COMPLETED
            # ------------------------------------------------

            self._log(
                logging.INFO,
                "Database migrations completed. "
                "Version: %s",
                current_version,
            )

        except MigrationError:

            raise

        except Exception as error:

            self._log(
                logging.ERROR,
                "Database migration failed: %s",
                error,
            )

            raise MigrationError(
                "Database migration failed."
            ) from error

    # ========================================================
    # VERSION TABLE
    # ========================================================

    async def _ensure_version_table(
        self,
    ) -> None:
        """
        Migration versiyon tablosunu oluşturur.

        Bu işlem idempotent'tir.

        Yani tablo daha önce oluşturulmuşsa
        tekrar hata vermez.
        """

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
            """
        )

    # ========================================================
    # CURRENT VERSION
    # ========================================================

    async def _get_current_version(
        self,
    ) -> int:
        """
        Mevcut schema versiyonunu döndürür.

        Eğer database daha önce migration
        almamışsa Version 0 kabul edilir.
        """

        row = await self.database.fetchone(
            """
            SELECT version
            FROM schema_version
            LIMIT 1
            """
        )

        # ----------------------------------------------------
        # FIRST RUN
        # ----------------------------------------------------

        if row is None:

            await self.database.execute(
                """
                INSERT INTO schema_version (
                    version
                )
                VALUES (?)
                """,
                (
                    0,
                ),
            )

            return 0

        # ----------------------------------------------------
        # EXISTING DATABASE
        # ----------------------------------------------------

        try:

            return int(
                row["version"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            raise MigrationError(
                "Invalid database schema version."
            ) from error

    # ========================================================
    # SET VERSION
    # ========================================================

    async def _set_version(
        self,
        version: int,
    ) -> None:
        """
        Schema versiyonunu günceller.
        """

        if version < 0:

            raise MigrationError(
                "Database schema version cannot "
                "be negative."
            )

        await self.database.execute(
            """
            UPDATE schema_version
            SET version = ?
            """,
            (
                version,
            ),
        )

    # ========================================================
    # MIGRATION V1
    # ========================================================

    async def _migration_v1(
        self,
    ) -> None:
        """
        PAG Bot ilk database schema'sı.

        Oluşturulan tablolar:

            events
            event_participants
        """

        # ----------------------------------------------------
        # EVENTS TABLE
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS events (

                id INTEGER
                    PRIMARY KEY
                    AUTOINCREMENT,

                name TEXT
                    NOT NULL,

                description TEXT
                    NOT NULL
                    DEFAULT '',

                event_type TEXT
                    NOT NULL,

                status TEXT
                    NOT NULL
                    DEFAULT 'active',

                created_by INTEGER
                    NOT NULL,

                start_time TEXT,

                end_time TEXT,

                max_participants INTEGER,

                image_url TEXT,

                thumbnail_url TEXT,

                created_at TEXT
                    NOT NULL,

                CHECK (
                    max_participants IS NULL
                    OR max_participants > 0
                )
            )
            """
        )

        # ----------------------------------------------------
        # EVENT PARTICIPANTS TABLE
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS event_participants (

                event_id INTEGER
                    NOT NULL,

                user_id INTEGER
                    NOT NULL,

                registered_at TEXT
                    NOT NULL,

                PRIMARY KEY (
                    event_id,
                    user_id
                ),

                FOREIGN KEY (
                    event_id
                )
                REFERENCES events(id)
                ON DELETE CASCADE
            )
            """
        )

        # ----------------------------------------------------
        # EVENTS STATUS INDEX
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_events_status
            ON events(status)
            """
        )

        # ----------------------------------------------------
        # EVENTS CREATED AT INDEX
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_events_created_at
            ON events(created_at)
            """
        )

        # ----------------------------------------------------
        # PARTICIPANTS EVENT ID INDEX
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_event_participants_event_id
            ON event_participants(event_id)
            """
        )

    # ========================================================
    # MIGRATION V2
    # ========================================================

    async def _migration_v2(
        self,
    ) -> None:
        """
        Verification sistemi için gerekli
        database schema'sı.

        Oluşturulan tablo:

            verifications
        """

        # ----------------------------------------------------
        # VERIFICATIONS TABLE
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS verifications (

                discord_id INTEGER
                    PRIMARY KEY,

                roblox_id INTEGER
                    NOT NULL
                    UNIQUE,

                roblox_username TEXT
                    NOT NULL,

                verified_at TEXT
                    NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # ROBLOX ID INDEX
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_verifications_roblox_id
            ON verifications(roblox_id)
            """
        )

        # ----------------------------------------------------
        # VERIFIED AT INDEX
        # ----------------------------------------------------

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_verifications_verified_at
            ON verifications(verified_at)
            """
        )

    # ========================================================
    # LOGGER
    # ========================================================

    def _log(
        self,
        level: int,
        message: str,
        *args: object,
    ) -> None:
        """
        Logger varsa loglar.

        Logger verilmemişse migration sistemi
        çalışmaya devam eder.
        """

        if self.logger is None:

            return

        self.logger.log(
            level,
            message,
            *args,
        )