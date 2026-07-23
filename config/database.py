"""
PAG Core
Database Manager

This module provides the central asynchronous SQLite database
manager used by the PAG Core application.

The database layer is responsible for:

- Creating and maintaining the SQLite connection
- Enabling SQLite foreign key support
- Initializing the database schema
- Executing parameterized SQL queries
- Fetching one or multiple records
- Managing database transactions
- Safely closing the database connection

The database layer intentionally does not contain business logic.

Business logic should be implemented in services and repositories.

Architecture:

    Discord Cog
        |
        v
    Service Layer
        |
        v
    Repository Layer
        |
        v
    Database Manager
        |
        v
    SQLite Database
"""


from __future__ import annotations


from pathlib import Path
from typing import Any


import aiosqlite


from config.settings import settings
from core.logger import logger


class Database:
    """
    Central asynchronous SQLite database manager.

    A single Database instance is created by the main PAGBot
    instance and shared with the rest of the application.

    The Database class is responsible for low-level database
    communication only.

    It should not contain:

    - Discord command logic
    - Roblox API logic
    - Image generation logic
    - Rank business logic
    - Event business logic

    Those responsibilities belong to other parts of the system.

    Example:

        database = Database()

        await database.connect()

        await database.initialize()

        user = await database.fetch_one(
            "SELECT * FROM users WHERE discord_id = ?",
            (123456789,),
        )
    """


    def __init__(self) -> None:
        """
        Initialize the database manager.

        The database connection is not opened during object
        initialization.

        Connection initialization is handled asynchronously
        through the connect() method.
        """

        self.path: Path = Path(
            settings.database_path
        )

        self.connection: (
            aiosqlite.Connection | None
        ) = None

        self.is_connected: bool = False


    async def connect(self) -> None:
        """
        Open a connection to the SQLite database.

        This method:

        1. Creates the parent directory if necessary.
        2. Opens the SQLite database.
        3. Configures row factory support.
        4. Enables foreign key enforcement.
        5. Marks the database as connected.
        """

        if self.is_connected:
            logger.warning(
                "Database connection already exists."
            )

            return


        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )


        self.connection = await aiosqlite.connect(
            self.path
        )


        self.connection.row_factory = (
            aiosqlite.Row
        )


        await self.connection.execute(
            "PRAGMA foreign_keys = ON;"
        )


        self.is_connected = True


        logger.info(
            "Database connected: %s",
            self.path,
        )


    async def initialize(self) -> None:
        """
        Initialize the complete PAG Core database schema.

        The schema contains the main systems required by PAG Core:

        - Users
        - Roblox accounts
        - Achievements
        - Events
        - Event participants
        - Member activity
        - PAG history
        - Milestones
        - System messages
        - Server configuration
        - Rank history

        Existing data is preserved because all tables use:

            CREATE TABLE IF NOT EXISTS
        """

        self._require_connection()


        await self.connection.executescript(
            """

            CREATE TABLE IF NOT EXISTS users (

                discord_id INTEGER PRIMARY KEY,

                roblox_id INTEGER UNIQUE,

                roblox_username TEXT,

                roblox_display_name TEXT,

                avatar_url TEXT,

                rank TEXT NOT NULL DEFAULT 'RT',

                joined_at TEXT,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL

            );


            CREATE TABLE IF NOT EXISTS achievements (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                discord_id INTEGER NOT NULL,

                name TEXT NOT NULL,

                description TEXT,

                achievement_type TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS events (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                description TEXT,

                status TEXT NOT NULL DEFAULT 'upcoming',

                winner_id INTEGER,

                start_time TEXT,

                end_time TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (
                    winner_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE SET NULL

            );


            CREATE TABLE IF NOT EXISTS event_participants (

                event_id INTEGER NOT NULL,

                discord_id INTEGER NOT NULL,

                joined_at TEXT NOT NULL,

                PRIMARY KEY (
                    event_id,
                    discord_id
                ),

                FOREIGN KEY (
                    event_id
                )
                REFERENCES events (
                    id
                )
                ON DELETE CASCADE,

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS activity (

                discord_id INTEGER PRIMARY KEY,

                messages INTEGER NOT NULL DEFAULT 0,

                voice_minutes INTEGER NOT NULL DEFAULT 0,

                events_joined INTEGER NOT NULL DEFAULT 0,

                events_won INTEGER NOT NULL DEFAULT 0,

                activity_points INTEGER NOT NULL DEFAULT 0,

                last_activity TEXT,

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS pag_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                event_type TEXT NOT NULL,

                title TEXT NOT NULL,

                description TEXT,

                discord_id INTEGER,

                created_at TEXT NOT NULL,

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE SET NULL

            );


            CREATE TABLE IF NOT EXISTS milestones (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                discord_id INTEGER NOT NULL,

                milestone_type TEXT NOT NULL,

                milestone_value INTEGER,

                created_at TEXT NOT NULL,

                UNIQUE (
                    discord_id,
                    milestone_type
                ),

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS system_messages (

                message_type TEXT PRIMARY KEY,

                guild_id INTEGER NOT NULL,

                channel_id INTEGER NOT NULL,

                message_id INTEGER NOT NULL,

                updated_at TEXT NOT NULL

            );


            CREATE TABLE IF NOT EXISTS server_config (

                guild_id INTEGER PRIMARY KEY,

                role_info_channel_id INTEGER,

                top_10_channel_id INTEGER,

                spotlight_channel_id INTEGER,

                achievements_channel_id INTEGER,

                history_channel_id INTEGER,

                events_channel_id INTEGER,

                updated_at TEXT NOT NULL

            );


            CREATE TABLE IF NOT EXISTS rank_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                discord_id INTEGER NOT NULL,

                old_rank TEXT,

                new_rank TEXT NOT NULL,

                changed_at TEXT NOT NULL,

                FOREIGN KEY (
                    discord_id
                )
                REFERENCES users (
                    discord_id
                )
                ON DELETE CASCADE

            );


            CREATE INDEX IF NOT EXISTS idx_users_rank

            ON users (
                rank
            );


            CREATE INDEX IF NOT EXISTS idx_achievements_user

            ON achievements (
                discord_id
            );


            CREATE INDEX IF NOT EXISTS idx_history_user

            ON pag_history (
                discord_id
            );


            CREATE INDEX IF NOT EXISTS idx_activity_points

            ON activity (
                activity_points
            );


            CREATE INDEX IF NOT EXISTS idx_events_status

            ON events (
                status
            );


            CREATE INDEX IF NOT EXISTS idx_rank_history_user

            ON rank_history (
                discord_id
            );

            """
        )


        await self.connection.commit()


        logger.info(
            "Database schema initialized."
        )


    async def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> None:
        """
        Execute an INSERT, UPDATE, or DELETE query.

        Parameters:

            query:
                SQL query to execute.

            parameters:
                Values passed to the query.

        Example:

            await database.execute(
                """
                INSERT INTO users (
                    discord_id,
                    rank,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    discord_id,
                    "RT",
                    timestamp,
                    timestamp,
                ),
            )
        """

        self._require_connection()


        await self.connection.execute(
            query,
            parameters,
        )


        await self.connection.commit()


    async def executemany(
        self,
        query: str,
        parameters: list[tuple[Any, ...]],
    ) -> None:
        """
        Execute the same query with multiple parameter sets.

        This is useful when inserting or updating multiple records
        at the same time.
        """

        self._require_connection()


        await self.connection.executemany(
            query,
            parameters,
        )


        await self.connection.commit()


    async def fetch_one(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> aiosqlite.Row | None:
        """
        Fetch a single row from the database.

        Returns:

            aiosqlite.Row:
                If a matching row exists.

            None:
                If no matching row exists.
        """

        self._require_connection()


        async with self.connection.execute(
            query,
            parameters,
        ) as cursor:

            result = await cursor.fetchone()


        return result


    async def fetch_all(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[aiosqlite.Row]:
        """
        Fetch all matching rows from the database.
        """

        self._require_connection()


        async with self.connection.execute(
            query,
            parameters,
        ) as cursor:

            results = await cursor.fetchall()


        return results


    async def fetch_value(
        self,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> Any:
        """
        Fetch a single value from the first column of the
        first matching row.

        Example:

            count = await database.fetch_value(
                "SELECT COUNT(*) FROM users"
            )
        """

        row = await self.fetch_one(
            query,
            parameters,
        )


        if row is None:
            return None


        return row[0]


    async def commit(self) -> None:
        """
        Commit the current transaction.
        """

        self._require_connection()


        await self.connection.commit()


    async def rollback(self) -> None:
        """
        Roll back the current transaction.

        This can be used when a transaction fails and changes
        must be reverted.
        """

        self._require_connection()


        await self.connection.rollback()


    def _require_connection(self) -> None:
        """
        Ensure that the database is connected.

        Raises:

            RuntimeError:
                If a database operation is attempted before
                connecting to the database.
        """

        if (
            self.connection is None
            or not self.is_connected
        ):

            raise RuntimeError(
                "Database is not connected."
            )


    async def close(self) -> None:
        """
        Close the SQLite database connection safely.

        Calling this method multiple times is safe.
        """

        if self.connection is None:
            return


        await self.connection.close()


        self.connection = None


        self.is_connected = False


        logger.info(
            "Database connection closed."
        )