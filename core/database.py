from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite


class Database:
    """
    PAG Bot SQLite database manager.

    Özellikler:
    - Async database işlemleri
    - WAL journal mode
    - Foreign key desteği
    - Busy timeout
    - Parametreli SQL sorguları
    - Kontrollü bağlantı yönetimi
    """

    def __init__(
        self,
        database_path: str | Path,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.logger = logger

        self._connection: aiosqlite.Connection | None = None
        self._initialized = False

    # =========================================================
    # CONNECTION
    # =========================================================

    async def connect(self) -> None:
        """
        Database bağlantısını açar ve SQLite ayarlarını uygular.
        """

        if self._connection is not None:
            return

        # Database klasörünü oluştur
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._connection = await aiosqlite.connect(
            self.database_path,
            timeout=10.0,
        )

        # Sonuçları tuple yerine dict benzeri Row olarak alabilmek için
        self._connection.row_factory = aiosqlite.Row

        # SQLite optimizasyonları
        await self._connection.execute(
            "PRAGMA foreign_keys = ON;"
        )

        await self._connection.execute(
            "PRAGMA journal_mode = WAL;"
        )

        await self._connection.execute(
            "PRAGMA synchronous = NORMAL;"
        )

        await self._connection.execute(
            "PRAGMA busy_timeout = 10000;"
        )

        await self._connection.commit()

        self._initialized = True

        self._log(
            logging.INFO,
            "Database connection established: %s",
            self.database_path,
        )

    # =========================================================
    # CLOSE
    # =========================================================

    async def close(self) -> None:
        """
        Database bağlantısını güvenli şekilde kapatır.
        """

        if self._connection is None:
            return

        await self._connection.close()

        self._connection = None
        self._initialized = False

        self._log(
            logging.INFO,
            "Database connection closed.",
        )

    # =========================================================
    # EXECUTE
    # =========================================================

    async def execute(
        self,
        query: str,
        parameters: Iterable[Any] = (),
    ) -> aiosqlite.Cursor:
        """
        INSERT, UPDATE, DELETE ve CREATE gibi işlemler için kullanılır.

        Örnek:

            await db.execute(
                "INSERT INTO members (user_id) VALUES (?)",
                (123456789,),
            )
        """

        connection = self._get_connection()

        cursor = await connection.execute(
            query,
            tuple(parameters),
        )

        await connection.commit()

        return cursor

    # =========================================================
    # EXECUTEMANY
    # =========================================================

    async def executemany(
        self,
        query: str,
        parameters: Iterable[Iterable[Any]],
    ) -> None:
        """
        Aynı sorguyu birden fazla veri için çalıştırır.
        """

        connection = self._get_connection()

        await connection.executemany(
            query,
            parameters,
        )

        await connection.commit()

    # =========================================================
    # FETCH ONE
    # =========================================================

    async def fetchone(
        self,
        query: str,
        parameters: Iterable[Any] = (),
    ) -> Optional[aiosqlite.Row]:
        """
        Tek bir satır döndürür.
        """

        connection = self._get_connection()

        async with connection.execute(
            query,
            tuple(parameters),
        ) as cursor:
            return await cursor.fetchone()

    # =========================================================
    # FETCH ALL
    # =========================================================

    async def fetchall(
        self,
        query: str,
        parameters: Iterable[Any] = (),
    ) -> list[aiosqlite.Row]:
        """
        Birden fazla satır döndürür.
        """

        connection = self._get_connection()

        async with connection.execute(
            query,
            tuple(parameters),
        ) as cursor:
            return await cursor.fetchall()

    # =========================================================
    # TRANSACTION
    # =========================================================

    async def transaction(
        self,
        queries: Iterable[
            tuple[str, Iterable[Any]]
        ],
    ) -> None:
        """
        Birden fazla sorguyu tek transaction içinde çalıştırır.

        Hepsi başarılı olursa:
            COMMIT

        Hata olursa:
            ROLLBACK
        """

        connection = self._get_connection()

        try:
            await connection.execute("BEGIN")

            for query, parameters in queries:
                await connection.execute(
                    query,
                    tuple(parameters),
                )

            await connection.commit()

        except Exception:
            await connection.rollback()

            self._log(
                logging.ERROR,
                "Database transaction failed.",
            )

            raise

    # =========================================================
    # COMMIT
    # =========================================================

    async def commit(self) -> None:
        """
        Açık transaction varsa commit eder.
        """

        connection = self._get_connection()

        await connection.commit()

    # =========================================================
    # INTERNAL CONNECTION
    # =========================================================

    def _get_connection(self) -> aiosqlite.Connection:
        """
        Aktif database bağlantısını döndürür.
        """

        if self._connection is None or not self._initialized:
            raise RuntimeError(
                "Database is not connected. "
                "Call 'await database.connect()' first."
            )

        return self._connection

    # =========================================================
    # INTERNAL LOGGER
    # =========================================================

    def _log(
        self,
        level: int,
        message: str,
        *args: Any,
    ) -> None:
        """
        Logger varsa loglar.
        Logger yoksa database sistemi çalışmaya devam eder.
        """

        if self.logger is not None:
            self.logger.log(
                level,
                message,
                *args,
            )