"""
PAG Core
Top 10 Service

This service manages the manually controlled PAG Top 10 ranking.

The ranking system is intentionally manual.

The lower the position number,
the higher the player's ranking.

Example:

    Position 1
        ↓
    Best player

    Position 5
        ↓
    Fifth best player


Main responsibilities:

    - Create the Top 10 database table
    - Add players
    - Update players
    - Remove players
    - Move players
    - Retrieve rankings
    - Validate positions
    - Retrieve Roblox information
    - Store Roblox avatar URLs
    - Prevent duplicate players


Architecture:

    Top10Cog
        |
        v
    Top10Service
        |
        ├── Database
        |
        └── RobloxService
                |
                v
            Roblox API


Example:

    Username
        |
        v
    RobloxService
        |
        ├── Roblox User ID
        ├── Display Name
        ├── Avatar URL
        └── Profile URL
        |
        v
    Top10Service
        |
        v
    SQLite Database
"""


from __future__ import annotations


import asyncio


import sqlite3


from dataclasses import dataclass


from datetime import datetime, timezone


from pathlib import Path


from typing import Any


from core.logger import logger


class Top10Error(
    Exception
):
    """
    Base exception for Top 10 errors.
    """


class InvalidPositionError(
    Top10Error
):
    """
    Raised when an invalid Top 10 position
    is provided.
    """


class PlayerAlreadyExistsError(
    Top10Error
):
    """
    Raised when a player already exists
    in the Top 10.
    """


class PlayerNotFoundError(
    Top10Error
):
    """
    Raised when a player cannot be found.
    """


class PositionOccupiedError(
    Top10Error
):
    """
    Raised when a position is occupied.

    The service can optionally move the existing
    player automatically.
    """


@dataclass(
    slots=True,
)
class Top10Entry:
    """
    Represents one Top 10 entry.
    """


    id: int


    position: int


    roblox_username: str


    roblox_display_name: str


    roblox_user_id: int


    avatar_url: str | None


    profile_url: str | None


    rank: str


    notes: str | None


    added_by: int


    updated_by: int


    created_at: str


    updated_at: str


    @property
    def is_first_place(
        self,
    ) -> bool:
        """
        Return whether this is the highest-ranked
        player.
        """

        return self.position == 1


class Top10Service:
    """
    Service responsible for the PAG Top 10 system.

    The service is intentionally independent from Discord.

    This means that the same service can later be used by:

        - Discord commands
        - Web dashboards
        - Admin panels
        - Automated ranking tools
    """


    MAX_ENTRIES = 10


    def __init__(
        self,

        database_path: str | Path,

        roblox_service: Any = None,

    ) -> None:
        """
        Initialize the Top 10 service.

        Parameters
        ----------
        database_path:
            Location of the SQLite database.

        roblox_service:
            Optional RobloxService instance.

        The RobloxService is used to retrieve:

            - Roblox user ID
            - Display name
            - Avatar
            - Profile URL
        """

        self.database_path = Path(
            database_path
        )


        self.roblox_service = (
            roblox_service
        )


        self._database_lock = (
            asyncio.Lock()
        )


        self.database_path.parent.mkdir(

            parents=True,

            exist_ok=True,

        )


        self._initialize_database()


        logger.info(

            "Top10Service initialized."

        )


    def _connect(
        self,
    ) -> sqlite3.Connection:
        """
        Create a SQLite connection.

        Row factory is enabled so that database
        rows can be accessed using column names.
        """

        connection = sqlite3.connect(

            self.database_path,

            timeout=30,

        )


        connection.row_factory = (
            sqlite3.Row
        )


        connection.execute(

            "PRAGMA foreign_keys = ON"

        )


        return connection


    def _initialize_database(
        self,
    ) -> None:
        """
        Create the Top 10 table.

        The position column is unique.

        This guarantees that two players cannot
        occupy the same ranking position.
        """

        connection = self._connect()


        try:

            connection.execute(

                """

                CREATE TABLE IF NOT EXISTS top10_entries (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    position INTEGER NOT NULL UNIQUE,

                    roblox_username TEXT NOT NULL,

                    roblox_display_name TEXT NOT NULL,

                    roblox_user_id INTEGER NOT NULL UNIQUE,

                    avatar_url TEXT,

                    profile_url TEXT,

                    rank TEXT NOT NULL,

                    notes TEXT,

                    added_by INTEGER NOT NULL,

                    updated_by INTEGER NOT NULL,

                    created_at TEXT NOT NULL,

                    updated_at TEXT NOT NULL

                )

                """

            )


            connection.execute(

                """

                CREATE INDEX IF NOT EXISTS

                idx_top10_position

                ON top10_entries(position)

                """

            )


            connection.execute(

                """

                CREATE INDEX IF NOT EXISTS

                idx_top10_roblox_user_id

                ON top10_entries(roblox_user_id)

                """

            )


            connection.commit()


        finally:

            connection.close()


        logger.info(

            "Top 10 database initialized."

        )


    @staticmethod
    def _validate_position(
        position: int,
    ) -> None:
        """
        Validate a Top 10 position.

        Valid positions:

            1
            2
            3
            ...
            10
        """

        if not isinstance(

            position,

            int,

        ):

            raise InvalidPositionError(

                "Position must be an integer."

            )


        if not (

            1

            <=

            position

            <=

            Top10Service.MAX_ENTRIES

        ):

            raise InvalidPositionError(

                "Position must be between 1 and 10."

            )


    @staticmethod
    def _utc_now(
    ) -> str:
        """
        Return the current UTC timestamp.
        """

        return datetime.now(

            timezone.utc

        ).isoformat()


    @staticmethod
    def _row_to_entry(
        row: sqlite3.Row,
    ) -> Top10Entry:
        """
        Convert a SQLite row into Top10Entry.
        """

        return Top10Entry(

            id=row["id"],

            position=row["position"],

            roblox_username=(

                row["roblox_username"]

            ),

            roblox_display_name=(

                row["roblox_display_name"]

            ),

            roblox_user_id=(

                row["roblox_user_id"]

            ),

            avatar_url=(

                row["avatar_url"]

            ),

            profile_url=(

                row["profile_url"]

            ),

            rank=row["rank"],

            notes=row["notes"],

            added_by=row["added_by"],

            updated_by=row["updated_by"],

            created_at=row["created_at"],

            updated_at=row["updated_at"],

        )


    async def _resolve_roblox_user(
        self,
        username: str,
    ) -> dict[str, Any]:
        """
        Resolve a Roblox username.

        This method attempts to work with multiple possible
        RobloxService response formats.

        This keeps Top10Service flexible while the RobloxService
        continues to evolve.
        """

        if self.roblox_service is None:

            raise Top10Error(

                "RobloxService is not configured."

            )


        profile = (

            await self.roblox_service.get_profile(

                username

            )

        )


        if profile is None:

            raise PlayerNotFoundError(

                f"Roblox user '{username}' was not found."

            )


        def get_value(

            key: str,

            default: Any = None,

        ) -> Any:

            if isinstance(

                profile,

                dict,

            ):

                return profile.get(

                    key,

                    default,

                )


            return getattr(

                profile,

                key,

                default,

            )


        user_id = get_value(

            "user_id",

        )


        if user_id is None:

            user_id = get_value(

                "id",

            )


        if user_id is None:

            raise Top10Error(

                "Roblox profile did not contain a user ID."

            )


        resolved_username = get_value(

            "username",

            username,

        )


        display_name = get_value(

            "display_name",

            resolved_username,

        )


        avatar_url = get_value(

            "avatar_url",

        )


        profile_url = get_value(

            "profile_url",

        )


        return {

            "username": str(

                resolved_username

            ),

            "display_name": str(

                display_name

            ),

            "user_id": int(

                user_id

            ),

            "avatar_url": avatar_url,

            "profile_url": profile_url,

        }


    async def get_all(
        self,
    ) -> list[Top10Entry]:
        """
        Return all Top 10 entries.

        Results are always sorted by position.

        Position 1 appears first.
        """

        async with self._database_lock:

            connection = self._connect()


            try:

                rows = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    ORDER BY position ASC

                    """

                ).fetchall()


            finally:

                connection.close()


        return [

            self._row_to_entry(

                row

            )

            for row in rows

        ]


    async def get_by_position(
        self,

        position: int,

    ) -> Top10Entry | None:
        """
        Retrieve the player at a specific position.
        """

        self._validate_position(

            position

        )


        async with self._database_lock:

            connection = self._connect()


            try:

                row = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE position = ?

                    """,

                    (

                        position,

                    ),

                ).fetchone()


            finally:

                connection.close()


        if row is None:

            return None


        return self._row_to_entry(

            row

        )


    async def get_by_user_id(
        self,

        roblox_user_id: int,

    ) -> Top10Entry | None:
        """
        Retrieve an entry by Roblox User ID.
        """

        async with self._database_lock:

            connection = self._connect()


            try:

                row = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE roblox_user_id = ?

                    """,

                    (

                        roblox_user_id,

                    ),

                ).fetchone()


            finally:

                connection.close()


        if row is None:

            return None


        return self._row_to_entry(

            row

        )


    async def add(
        self,

        position: int,

        username: str,

        rank: str,

        added_by: int,

        notes: str | None = None,

        replace_existing: bool = False,

    ) -> Top10Entry:
        """
        Add a new player to the Top 10.

        Parameters
        ----------

        position:
            Ranking position from 1 to 10.

        username:
            Roblox username.

        rank:
            PAG rank, for example PT1 or ET3.

        added_by:
            Discord ID of the administrator.

        notes:
            Optional notes about the player.

        replace_existing:
            If True, an existing player at the position
            will be replaced.

        Example:

            await service.add(

                position=1,

                username="Velgrath",

                rank="PT1",

                added_by=123456789,

            )
        """

        self._validate_position(

            position

        )


        username = username.strip()


        rank = rank.strip()


        if not username:

            raise Top10Error(

                "Username cannot be empty."

            )


        if not rank:

            raise Top10Error(

                "Rank cannot be empty."

            )


        profile = (

            await self._resolve_roblox_user(

                username

            )

        )


        async with self._database_lock:

            connection = self._connect()


            try:

                existing_position = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE position = ?

                    """,

                    (

                        position,

                    ),

                ).fetchone()


                existing_user = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE roblox_user_id = ?

                    """,

                    (

                        profile["user_id"],

                    ),

                ).fetchone()


                if existing_user is not None:

                    raise PlayerAlreadyExistsError(

                        (

                            f"{profile['username']} "

                            "is already in the Top 10."

                        )

                    )


                if (

                    existing_position is not None

                    and

                    not replace_existing

                ):

                    raise PositionOccupiedError(

                        (

                            f"Position {position} "

                            "is already occupied."

                        )

                    )


                now = self._utc_now()


                if existing_position is not None:

                    connection.execute(

                        """

                        DELETE FROM top10_entries

                        WHERE position = ?

                        """,

                        (

                            position,

                        ),

                    )


                connection.execute(

                    """

                    INSERT INTO top10_entries (

                        position,

                        roblox_username,

                        roblox_display_name,

                        roblox_user_id,

                        avatar_url,

                        profile_url,

                        rank,

                        notes,

                        added_by,

                        updated_by,

                        created_at,

                        updated_at

                    )

                    VALUES (

                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?

                    )

                    """,

                    (

                        position,

                        profile["username"],

                        profile["display_name"],

                        profile["user_id"],

                        profile["avatar_url"],

                        profile["profile_url"],

                        rank,

                        notes,

                        added_by,

                        added_by,

                        now,

                        now,

                    ),

                )


                connection.commit()


                row = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE position = ?

                    """,

                    (

                        position,

                    ),

                ).fetchone()


            finally:

                connection.close()


        logger.info(

            "Top 10 player added: %s at #%s",

            profile["username"],

            position,

        )


        return self._row_to_entry(

            row

        )


    async def update(
        self,

        position: int,

        updated_by: int,

        username: str | None = None,

        rank: str | None = None,

        notes: str | None = None,

        new_position: int | None = None,

    ) -> Top10Entry:
        """
        Update an existing Top 10 entry.

        Any provided field will be updated.

        Example:

            await service.update(

                position=1,

                updated_by=123456789,

                rank="PT2",

            )

        """

        self._validate_position(

            position

        )


        if new_position is not None:

            self._validate_position(

                new_position

            )


        current = await self.get_by_position(

            position

        )


        if current is None:

            raise PlayerNotFoundError(

                (

                    f"No player exists at "

                    f"position {position}."

                )

            )


        profile = None


        if username is not None:

            profile = (

                await self._resolve_roblox_user(

                    username.strip()

                )

            )


        target_position = (

            new_position

            if new_position is not None

            else position

        )


        async with self._database_lock:

            connection = self._connect()


            try:

                if (

                    target_position

                    !=

                    position

                ):

                    occupied = connection.execute(

                        """

                        SELECT id

                        FROM top10_entries

                        WHERE position = ?

                        """,

                        (

                            target_position,

                        ),

                    ).fetchone()


                    if occupied is not None:

                        raise PositionOccupiedError(

                            (

                                f"Position "

                                f"{target_position} "

                                "is already occupied."

                            )

                        )


                if profile is not None:

                    new_username = (

                        profile["username"]

                    )


                    new_display_name = (

                        profile["display_name"]

                    )


                    new_user_id = (

                        profile["user_id"]

                    )


                    new_avatar_url = (

                        profile["avatar_url"]

                    )


                    new_profile_url = (

                        profile["profile_url"]

                    )


                else:

                    new_username = (

                        current.roblox_username

                    )


                    new_display_name = (

                        current.roblox_display_name

                    )


                    new_user_id = (

                        current.roblox_user_id

                    )


                    new_avatar_url = (

                        current.avatar_url

                    )


                    new_profile_url = (

                        current.profile_url

                    )


                new_rank = (

                    rank.strip()

                    if rank is not None

                    else current.rank

                )


                new_notes = (

                    notes

                    if notes is not None

                    else current.notes

                )


                now = self._utc_now()


                connection.execute(

                    """

                    UPDATE top10_entries

                    SET

                        position = ?,

                        roblox_username = ?,

                        roblox_display_name = ?,

                        roblox_user_id = ?,

                        avatar_url = ?,

                        profile_url = ?,

                        rank = ?,

                        notes = ?,

                        updated_by = ?,

                        updated_at = ?

                    WHERE id = ?

                    """,

                    (

                        target_position,

                        new_username,

                        new_display_name,

                        new_user_id,

                        new_avatar_url,

                        new_profile_url,

                        new_rank,

                        new_notes,

                        updated_by,

                        now,

                        current.id,

                    ),

                )


                connection.commit()


                row = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE id = ?

                    """,

                    (

                        current.id,

                    ),

                ).fetchone()


            finally:

                connection.close()


        logger.info(

            "Top 10 player updated: #%s",

            target_position,

        )


        return self._row_to_entry(

            row

        )


    async def remove(
        self,

        position: int,

    ) -> Top10Entry:
        """
        Remove a player from the Top 10.
        """

        self._validate_position(

            position

        )


        async with self._database_lock:

            connection = self._connect()


            try:

                row = connection.execute(

                    """

                    SELECT *

                    FROM top10_entries

                    WHERE position = ?

                    """,

                    (

                        position,

                    ),

                ).fetchone()


                if row is None:

                    raise PlayerNotFoundError(

                        (

                            f"No player exists at "

                            f"position {position}."

                        )

                    )


                connection.execute(

                    """

                    DELETE FROM top10_entries

                    WHERE position = ?

                    """,

                    (

                        position,

                    ),

                )


                connection.commit()


            finally:

                connection.close()


        removed_entry = self._row_to_entry(

            row

        )


        logger.info(

            "Top 10 player removed: #%s %s",

            removed_entry.position,

            removed_entry.roblox_username,

        )


        return removed_entry


    async def clear(
        self,
    ) -> int:
        """
        Remove all Top 10 entries.

        Returns the number of deleted entries.
        """

        async with self._database_lock:

            connection = self._connect()


            try:

                cursor = connection.execute(

                    """

                    DELETE FROM top10_entries

                    """

                )


                deleted_count = (

                    cursor.rowcount

                )


                connection.commit()


            finally:

                connection.close()


        logger.warning(

            "Top 10 database cleared. Removed %s entries.",

            deleted_count,

        )


        return deleted_count


    async def count(
        self,
    ) -> int:
        """
        Return the current number of Top 10 entries.
        """

        async with self._database_lock:

            connection = self._connect()


            try:

                row = connection.execute(

                    """

                    SELECT COUNT(*)

                    AS count

                    FROM top10_entries

                    """

                ).fetchone()


            finally:

                connection.close()


        return int(

            row["count"]

        )


    async def is_full(
        self,
    ) -> bool:
        """
        Return whether all ten positions are occupied.
        """

        current_count = await self.count()


        return (

            current_count

            >=

            self.MAX_ENTRIES

        )