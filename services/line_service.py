from __future__ import annotations

import logging
from typing import Any, Iterable

import discord


class LineService:
    """SQLite-backed TSBCC line/match/application state service."""

    def __init__(self, *, database: Any, logger: logging.Logger) -> None:
        self.database = database
        self.logger = logger

    async def ensure_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS line_settings (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                log_channel_id INTEGER,
                locked INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS main_line (
                guild_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                roblox_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, slot),
                UNIQUE (guild_id, discord_id),
                UNIQUE (guild_id, roblox_id),
                CHECK (slot BETWEEN 1 AND 5)
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS cw_line (
                guild_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                roblox_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, slot),
                UNIQUE (guild_id, discord_id),
                UNIQUE (guild_id, roblox_id),
                CHECK (slot BETWEEN 1 AND 5)
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS line_matches (
                guild_id INTEGER PRIMARY KEY,
                match_type TEXT,
                opponent TEXT,
                status TEXT NOT NULL DEFAULT 'IDLE',
                started_at TEXT,
                ended_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS line_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                roblox_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                UNIQUE (guild_id, discord_id, status)
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS line_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_line_logs_guild_created ON line_logs(guild_id, created_at DESC)"
        )
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_line_applications_guild_status ON line_applications(guild_id, status)"
        )
        await self.database.commit()

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        row = await self.database.fetchone(
            "SELECT * FROM line_settings WHERE guild_id = ?",
            (guild_id,),
        )
        if row is None:
            return {"guild_id": guild_id, "locked": False}
        data = dict(row)
        data["locked"] = bool(data.get("locked"))
        return data

    async def upsert_settings(self, guild_id: int, **fields: Any) -> None:
        current = await self.get_settings(guild_id)
        current.update(fields)
        now = discord.utils.utcnow().isoformat()
        await self.database.execute(
            """
            INSERT INTO line_settings (
                guild_id, panel_channel_id, panel_message_id, log_channel_id, locked, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                panel_channel_id=excluded.panel_channel_id,
                panel_message_id=excluded.panel_message_id,
                log_channel_id=excluded.log_channel_id,
                locked=excluded.locked,
                updated_at=excluded.updated_at
            """,
            (
                guild_id,
                current.get("panel_channel_id"),
                current.get("panel_message_id"),
                current.get("log_channel_id"),
                int(bool(current.get("locked", False))),
                now,
            ),
        )
        await self.database.commit()

    async def get_line(self, guild_id: int, table: str) -> list[dict[str, Any]]:
        if table not in {"main_line", "cw_line"}:
            raise ValueError("Invalid line table")
        rows = await self.database.fetchall(
            f"SELECT * FROM {table} WHERE guild_id = ? ORDER BY slot ASC",
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def set_line(self, guild_id: int, table: str, players: Iterable[dict[str, int | str]]) -> None:
        if table not in {"main_line", "cw_line"}:
            raise ValueError("Invalid line table")
        players_list = list(players)
        if len(players_list) > 5:
            raise ValueError("A line can contain at most 5 players.")
        now = discord.utils.utcnow().isoformat()
        queries = [(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))]
        for index, player in enumerate(players_list, start=1):
            queries.append(
                (
                    f"""
                    INSERT INTO {table} (
                        guild_id, slot, discord_id, roblox_id, roblox_username, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        index,
                        int(player["discord_id"]),
                        int(player["roblox_id"]),
                        str(player["roblox_username"]),
                        now,
                    ),
                )
            )
        await self.database.transaction(queries)

    async def clear_line(self, guild_id: int, table: str) -> None:
        if table not in {"main_line", "cw_line"}:
            raise ValueError("Invalid line table")
        await self.database.execute(
            f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,)
        )
        await self.database.commit()

    async def replace_slot(self, guild_id: int, table: str, slot: int, player: dict[str, Any] | None) -> None:
        if table not in {"main_line", "cw_line"}:
            raise ValueError("Invalid line table")
        if slot not in range(1, 6):
            raise ValueError("Slot must be between 1 and 5.")
        await self.database.execute(
            f"DELETE FROM {table} WHERE guild_id = ? AND slot = ?",
            (guild_id, slot),
        )
        if player is not None:
            await self.database.execute(
                f"""
                INSERT INTO {table} (
                    guild_id, slot, discord_id, roblox_id, roblox_username, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    slot,
                    int(player["discord_id"]),
                    int(player["roblox_id"]),
                    str(player["roblox_username"]),
                    discord.utils.utcnow().isoformat(),
                ),
            )
        await self.database.commit()

    async def get_match(self, guild_id: int) -> dict[str, Any]:
        row = await self.database.fetchone(
            "SELECT * FROM line_matches WHERE guild_id = ?", (guild_id,)
        )
        if row is None:
            return {"status": "IDLE"}
        return dict(row)

    async def set_match(self, guild_id: int, *, match_type: str, opponent: str, status: str) -> None:
        now = discord.utils.utcnow().isoformat()
        existing = await self.get_match(guild_id)
        started_at = existing.get("started_at") if status == "ENDED" else now
        await self.database.execute(
            """
            INSERT INTO line_matches (
                guild_id, match_type, opponent, status, started_at, ended_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                match_type=excluded.match_type,
                opponent=excluded.opponent,
                status=excluded.status,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                updated_at=excluded.updated_at
            """,
            (
                guild_id,
                match_type,
                opponent,
                status,
                started_at if status != "ENDED" else existing.get("started_at"),
                now if status == "ENDED" else None,
                now,
            ),
        )
        await self.database.commit()

    async def reset_match(self, guild_id: int) -> None:
        await self.database.execute(
            "DELETE FROM line_matches WHERE guild_id = ?", (guild_id,)
        )
        await self.database.commit()

    async def create_application(self, guild_id: int, player: dict[str, Any]) -> bool:
        row = await self.database.fetchone(
            """
            SELECT id FROM line_applications
            WHERE guild_id = ? AND discord_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (guild_id, int(player["discord_id"])),
        )
        if row is not None:
            return False
        await self.database.execute(
            """
            INSERT INTO line_applications (
                guild_id, discord_id, roblox_id, roblox_username, status, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                guild_id,
                int(player["discord_id"]),
                int(player["roblox_id"]),
                str(player["roblox_username"]),
                discord.utils.utcnow().isoformat(),
            ),
        )
        await self.database.commit()
        return True

    async def get_pending_applications(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM line_applications
            WHERE guild_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def review_application(self, application_id: int, actor_id: int, status: str) -> None:
        if status not in {"accepted", "rejected"}:
            raise ValueError("Invalid application status")
        await self.database.execute(
            """
            UPDATE line_applications
            SET status = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (
                status,
                discord.utils.utcnow().isoformat(),
                actor_id,
                application_id,
            ),
        )
        await self.database.commit()

    async def log(self, guild_id: int, actor_id: int, action: str, details: str = "") -> None:
        await self.database.execute(
            """
            INSERT INTO line_logs (guild_id, actor_id, action, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                actor_id,
                action,
                details[:1800],
                discord.utils.utcnow().isoformat(),
            ),
        )
        await self.database.commit()
