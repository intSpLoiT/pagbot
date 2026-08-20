from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import discord
from discord.ext import commands


# ============================================================
# PAG BOT — RAID SYSTEM
# ============================================================
# All public commands are prefix commands beginning with !.
# This cog intentionally uses the project's shared Database
# (bot.database). It does NOT create another SQLite connection.
# ============================================================

LOGGER_NAME = "PAG.Raid"

RAID_FORMAT = "3v3"
TEAM_SIZE = 3

STATUS_RECRUITING = "recruiting"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

REPORT_PENDING = "pending"
REPORT_VERIFIED = "verified"
REPORT_REJECTED = "rejected"

RESULT_PAG_WIN = "pag_win"
RESULT_PAG_LOSS = "pag_loss"
RESULT_DRAW = "draw"

RESULT_LABELS = {
    RESULT_PAG_WIN: "PAG VICTORY",
    RESULT_PAG_LOSS: "PAG DEFEAT",
    RESULT_DRAW: "DRAW",
}

VALID_RESULTS = {
    RESULT_PAG_WIN,
    RESULT_PAG_LOSS,
    RESULT_DRAW,
}

MAX_HISTORY_ROWS = 100
MAX_RANKING_ROWS = 10
MAX_TEXT = 1000


# ============================================================
# HELPERS
# ============================================================


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def short_text(value: Any, limit: int = 1024) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def clean_text(value: str | None, limit: int = MAX_TEXT) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:limit]


def user_mention(user_id: int) -> str:
    return f"<@{user_id}>"


def result_label(result: str | None) -> str:
    return RESULT_LABELS.get(result or "", "UNKNOWN")


def status_label(status: str) -> str:
    return {
        STATUS_RECRUITING: "🟡 RECRUITING",
        STATUS_ACTIVE: "🟢 ACTIVE",
        STATUS_COMPLETED: "🏁 COMPLETED",
        STATUS_CANCELLED: "🔴 CANCELLED",
    }.get(status, status.upper())


def extract_user_ids(raw: str) -> list[int]:
    """Accept mentions, raw IDs and comma/space separated IDs."""
    found: list[int] = []
    for token in re.findall(r"(?:<@!?(\d+)>|(\d{15,25}))", raw or ""):
        value = token[0] or token[1]
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id not in found:
            found.append(user_id)
    return found


def safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


# ============================================================
# EMBEDS
# ============================================================


class RaidEmbeds:
    @staticmethod
    def base(title: str, description: str, color: discord.Color) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return RaidEmbeds.base(title, description, discord.Color.red())

    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return RaidEmbeds.base(title, description, discord.Color.green())

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return RaidEmbeds.base(title, description, discord.Color.orange())

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return RaidEmbeds.base(title, description, discord.Color.blurple())

    @staticmethod
    def center() -> discord.Embed:
        embed = RaidEmbeds.base(
            "⚔️ PAG RAID CENTER",
            (
                "Clanlar arası Raid oluştur, oyuncularını topla, rakip çağır "
                "ve sonuçları güvenli şekilde kaydet.\n\n"
                "**Normal format:** `3v3`\n"
                "**Başlangıç:** `1v3` durumunda bile rakip çağrılabilir.\n"
                "**İstatistik:** Yalnızca doğrulanmış sonuçlar sayılır."
            ),
            discord.Color.dark_teal(),
        )
        embed.add_field(
            name="⚔️ Raid Akışı",
            value="`CREATE` → `JOIN` → `3v3` → `ACTIVE` → `RESULT` → `VERIFIED`",
            inline=False,
        )
        embed.add_field(
            name="🛡️ Manuel Report",
            value="Proof Link zorunludur. Staff/Raid Manager onayından sonra istatistiklere işlenir.",
            inline=False,
        )
        embed.set_footer(text="PAG RAID SYSTEM • Persistent Panel")
        return embed

    @staticmethod
    def raid(row: Any, pag_players: list[int], opponent_players: list[int], guild: discord.Guild) -> discord.Embed:
        opponent = short_text(row["opponent_clan"] or "Rival Clan", 80)
        lines_pag = "\n".join(f"{i}. {user_mention(uid)}" for i, uid in enumerate(pag_players, 1)) or "—"
        lines_opp = "\n".join(f"{i}. {user_mention(uid)}" for i, uid in enumerate(opponent_players, 1)) or "—"
        embed = RaidEmbeds.base(
            f"⚔️ RAID #{row['id']} • PAG × {opponent}",
            f"**Status:** {status_label(row['status'])}\n**Format:** `3v3`",
            discord.Color.green() if row["status"] == STATUS_ACTIVE else discord.Color.blurple(),
        )
        embed.add_field(name=f"PAG • {len(pag_players)}/{TEAM_SIZE}", value=lines_pag, inline=True)
        embed.add_field(name=f"RIVAL • {len(opponent_players)}/{TEAM_SIZE}", value=lines_opp, inline=True)
        embed.add_field(
            name="📌 Bilgi",
            value=(
                f"**Host:** {user_mention(int(row['creator_id']))}\n"
                f"**Oluşturulma:** <t:{int(parse_iso(row['created_at']).timestamp())}:R>"
            ),
            inline=False,
        )
        if row["note"]:
            embed.add_field(name="📝 Not", value=short_text(row["note"], 1024), inline=False)
        embed.set_footer(text="PAG RAID SYSTEM")
        return embed

    @staticmethod
    def result(row: Any, mvp_id: int | None) -> discord.Embed:
        result = result_label(row["result"])
        color = discord.Color.green() if row["result"] == RESULT_PAG_WIN else discord.Color.red() if row["result"] == RESULT_PAG_LOSS else discord.Color.gold()
        embed = RaidEmbeds.base(
            "🏁 RAID RESULT",
            f"**PAG × {short_text(row['opponent_clan'], 80)}**",
            color,
        )
        embed.add_field(name="RESULT", value=f"**{result}**", inline=True)
        embed.add_field(name="FORMAT", value="`3v3`", inline=True)
        embed.add_field(name="STATUS", value="**VERIFIED**", inline=True)
        embed.add_field(name="MVP", value=user_mention(mvp_id) if mvp_id else "Not selected", inline=True)
        if row["started_at"] and row["ended_at"]:
            start = parse_iso(row["started_at"])
            end = parse_iso(row["ended_at"])
            if start and end:
                seconds = max(0, int((end - start).total_seconds()))
                embed.add_field(
                    name="DURATION",
                    value=f"`{seconds // 60:02d}:{seconds % 60:02d}`",
                    inline=True,
                )
        embed.set_footer(text="PAG RAID SYSTEM")
        return embed

    @staticmethod
    def profile(user_id: int, stats: Any) -> discord.Embed:
        raids = int(stats["raids"] or 0)
        wins = int(stats["wins"] or 0)
        losses = int(stats["losses"] or 0)
        mvp = int(stats["mvp"] or 0)
        rate = (wins / raids * 100) if raids else 0.0
        embed = RaidEmbeds.base(
            "👤 RAID PROFILE",
            f"Player: {user_mention(user_id)}",
            discord.Color.blurple(),
        )
        embed.add_field(name="Raids", value=f"`{raids}`", inline=True)
        embed.add_field(name="Victories", value=f"`{wins}`", inline=True)
        embed.add_field(name="Defeats", value=f"`{losses}`", inline=True)
        embed.add_field(name="MVP", value=f"`{mvp}`", inline=True)
        embed.add_field(name="Win Rate", value=f"`{rate:.1f}%`", inline=True)
        embed.add_field(name="Best Streak", value=f"`{int(stats['best_streak'] or 0)}`", inline=True)
        embed.add_field(name="Current Streak", value=f"`{int(stats['current_streak'] or 0)}`", inline=True)
        embed.set_footer(text="Yalnızca VERIFIED raidler bu istatistiklere dahil edilir.")
        return embed


# ============================================================
# DATABASE LAYER
# ============================================================


class RaidStore:
    """All raid persistence through the project's shared async Database."""

    def __init__(self, database: Any, logger: logging.Logger) -> None:
        self.db = database
        self.logger = logger

    async def ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS raid_config (
                guild_id INTEGER PRIMARY KEY,
                board_channel_id INTEGER,
                category_id INTEGER,
                manager_role_id INTEGER,
                staff_role_id INTEGER,
                archive_channels INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                opponent_clan TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT '3v3',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'recruiting',
                result TEXT,
                mvp_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                created_at TEXT NOT NULL,
                channel_id INTEGER,
                message_id INTEGER,
                proof_url TEXT,
                verified_by INTEGER,
                verified_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raid_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raid_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('pag', 'opponent')),
                joined_at TEXT NOT NULL,
                left_at TEXT,
                UNIQUE(raid_id, user_id),
                FOREIGN KEY(raid_id) REFERENCES raids(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raid_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raid_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                inviter_id INTEGER NOT NULL,
                invitee_id INTEGER NOT NULL,
                side TEXT NOT NULL DEFAULT 'pag',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                UNIQUE(raid_id, invitee_id),
                FOREIGN KEY(raid_id) REFERENCES raids(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raid_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                raid_id INTEGER,
                reporter_id INTEGER NOT NULL,
                opponent_clan TEXT NOT NULL,
                players_json TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT '3v3',
                result TEXT NOT NULL,
                mvp_id INTEGER,
                raid_date TEXT NOT NULL,
                proof_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                review_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                reviewed_by INTEGER,
                reviewed_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raid_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                raid_id INTEGER,
                report_id INTEGER,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raid_stats (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                raids INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0,
                mvp INTEGER NOT NULL DEFAULT 0,
                current_streak INTEGER NOT NULL DEFAULT 0,
                best_streak INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, user_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_raids_guild_status ON raids(guild_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_raid_players_raid_side ON raid_players(raid_id, side)",
            "CREATE INDEX IF NOT EXISTS idx_raid_players_user ON raid_players(guild_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reports_status ON raid_reports(guild_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_stats_rank ON raid_stats(guild_id, wins DESC, raids DESC)",
        ]
        for statement in statements:
            await self.db.execute(statement)

    async def get_config(self, guild_id: int) -> Any:
        return await self.db.fetchone("SELECT * FROM raid_config WHERE guild_id = ?", (guild_id,))

    async def set_config(
        self,
        guild_id: int,
        *,
        board_channel_id: int | None = None,
        category_id: int | None = None,
        manager_role_id: int | None = None,
        staff_role_id: int | None = None,
        archive_channels: bool = True,
    ) -> None:
        existing = await self.get_config(guild_id)
        if existing:
            await self.db.execute(
                """
                UPDATE raid_config
                SET board_channel_id = ?, category_id = ?, manager_role_id = ?,
                    staff_role_id = ?, archive_channels = ?, updated_at = ?
                WHERE guild_id = ?
                """,
                (
                    board_channel_id,
                    category_id,
                    manager_role_id,
                    staff_role_id,
                    int(archive_channels),
                    utc_now(),
                    guild_id,
                ),
            )
        else:
            await self.db.execute(
                """
                INSERT INTO raid_config
                (guild_id, board_channel_id, category_id, manager_role_id,
                 staff_role_id, archive_channels, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    board_channel_id,
                    category_id,
                    manager_role_id,
                    staff_role_id,
                    int(archive_channels),
                    utc_now(),
                ),
            )

    async def create_raid(self, guild_id: int, creator_id: int, opponent_clan: str, note: str) -> int:
        cursor = await self.db.execute(
            """
            INSERT INTO raids
            (guild_id, creator_id, opponent_clan, format, note, status, created_at)
            VALUES (?, ?, ?, '3v3', ?, 'recruiting', ?)
            """,
            (guild_id, creator_id, opponent_clan, note, utc_now()),
        )
        return int(cursor.lastrowid)

    async def get_raid(self, raid_id: int, guild_id: int) -> Any:
        return await self.db.fetchone(
            "SELECT * FROM raids WHERE id = ? AND guild_id = ?",
            (raid_id, guild_id),
        )

    async def get_active_raids(self, guild_id: int) -> list[Any]:
        return await self.db.fetchall(
            """
            SELECT * FROM raids
            WHERE guild_id = ? AND status IN ('recruiting', 'active')
            ORDER BY created_at DESC LIMIT 25
            """,
            (guild_id,),
        )

    async def get_recent_raids(self, guild_id: int, user_id: int, limit: int = 10) -> list[Any]:
        return await self.db.fetchall(
            """
            SELECT DISTINCT r.*
            FROM raids r
            JOIN raid_players p ON p.raid_id = r.id
            WHERE r.guild_id = ? AND p.user_id = ?
            ORDER BY COALESCE(r.ended_at, r.created_at) DESC
            LIMIT ?
            """,
            (guild_id, user_id, max(1, min(limit, MAX_HISTORY_ROWS))),
        )

    async def get_players(self, raid_id: int, side: str | None = None) -> list[Any]:
        if side:
            return await self.db.fetchall(
                "SELECT * FROM raid_players WHERE raid_id = ? AND side = ? ORDER BY joined_at ASC",
                (raid_id, side),
            )
        return await self.db.fetchall(
            "SELECT * FROM raid_players WHERE raid_id = ? ORDER BY joined_at ASC",
            (raid_id,),
        )

    async def get_player_ids(self, raid_id: int, side: str) -> list[int]:
        rows = await self.get_players(raid_id, side)
        return [int(row["user_id"]) for row in rows if row["left_at"] is None]

    async def is_player_in_raid(self, raid_id: int, user_id: int) -> Any:
        return await self.db.fetchone(
            "SELECT * FROM raid_players WHERE raid_id = ? AND user_id = ? AND left_at IS NULL",
            (raid_id, user_id),
        )

    async def add_player(self, raid_id: int, guild_id: int, user_id: int, side: str) -> None:
        existing = await self.db.fetchone(
            "SELECT * FROM raid_players WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )
        if existing:
            if existing["left_at"] is None:
                return
            await self.db.execute(
                """
                UPDATE raid_players
                SET side = ?, joined_at = ?, left_at = NULL
                WHERE raid_id = ? AND user_id = ?
                """,
                (side, utc_now(), raid_id, user_id),
            )
            return
        await self.db.execute(
            """
            INSERT INTO raid_players
            (raid_id, guild_id, user_id, side, joined_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (raid_id, guild_id, user_id, side, utc_now()),
        )

    async def remove_player(self, raid_id: int, user_id: int) -> None:
        await self.db.execute(
            "UPDATE raid_players SET left_at = ? WHERE raid_id = ? AND user_id = ? AND left_at IS NULL",
            (utc_now(), raid_id, user_id),
        )

    async def update_raid_message(self, raid_id: int, channel_id: int | None, message_id: int | None) -> None:
        await self.db.execute(
            "UPDATE raids SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, raid_id),
        )

    async def update_status(self, raid_id: int, status: str, started_at: str | None = None) -> None:
        await self.db.execute(
            "UPDATE raids SET status = ?, started_at = COALESCE(?, started_at) WHERE id = ?",
            (status, started_at, raid_id),
        )

    async def finish_raid(
        self,
        raid_id: int,
        result: str,
        mvp_id: int | None,
        ended_at: str,
        verified_by: int,
        proof_url: str | None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE raids
            SET status = 'completed', result = ?, mvp_id = ?, ended_at = ?,
                verified_by = ?, verified_at = ?, proof_url = ?
            WHERE id = ?
            """,
            (result, mvp_id, ended_at, verified_by, ended_at, proof_url, raid_id),
        )

    async def cancel_raid(self, raid_id: int) -> None:
        await self.db.execute(
            "UPDATE raids SET status = 'cancelled', ended_at = ? WHERE id = ?",
            (utc_now(), raid_id),
        )

    async def add_invite(self, raid_id: int, guild_id: int, inviter_id: int, invitee_id: int, side: str) -> None:
        await self.db.execute(
            """
            INSERT INTO raid_invites
            (raid_id, guild_id, inviter_id, invitee_id, side, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(raid_id, invitee_id)
            DO UPDATE SET inviter_id = excluded.inviter_id, side = excluded.side,
                          status = 'pending', created_at = excluded.created_at,
                          responded_at = NULL
            """,
            (raid_id, guild_id, inviter_id, invitee_id, side, utc_now()),
        )

    async def get_invite(self, invite_id: int) -> Any:
        return await self.db.fetchone("SELECT * FROM raid_invites WHERE id = ?", (invite_id,))

    async def set_invite_status(self, invite_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE raid_invites SET status = ?, responded_at = ? WHERE id = ?",
            (status, utc_now(), invite_id),
        )

    async def create_report(
        self,
        guild_id: int,
        reporter_id: int,
        opponent_clan: str,
        player_ids: list[int],
        result: str,
        mvp_id: int | None,
        raid_date: str,
        proof_url: str,
    ) -> int:
        cursor = await self.db.execute(
            """
            INSERT INTO raid_reports
            (guild_id, reporter_id, opponent_clan, players_json, format,
             result, mvp_id, raid_date, proof_url, status, created_at)
            VALUES (?, ?, ?, ?, '3v3', ?, ?, ?, ?, 'pending', ?)
            """,
            (
                guild_id,
                reporter_id,
                opponent_clan,
                safe_json(player_ids),
                result,
                mvp_id,
                raid_date,
                proof_url,
                utc_now(),
            ),
        )
        return int(cursor.lastrowid)

    async def get_report(self, report_id: int, guild_id: int) -> Any:
        return await self.db.fetchone(
            "SELECT * FROM raid_reports WHERE id = ? AND guild_id = ?",
            (report_id, guild_id),
        )

    async def get_pending_reports(self, guild_id: int, limit: int = 10) -> list[Any]:
        return await self.db.fetchall(
            """
            SELECT * FROM raid_reports
            WHERE guild_id = ? AND status = 'pending'
            ORDER BY created_at ASC LIMIT ?
            """,
            (guild_id, min(max(limit, 1), 25)),
        )

    async def review_report(self, report_id: int, status: str, reviewer_id: int, note: str) -> None:
        await self.db.execute(
            """
            UPDATE raid_reports
            SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?
            WHERE id = ?
            """,
            (status, reviewer_id, utc_now(), note, report_id),
        )

    async def get_stats(self, guild_id: int, user_id: int) -> Any:
        row = await self.db.fetchone(
            "SELECT * FROM raid_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row:
            return row
        await self.db.execute(
            """
            INSERT OR IGNORE INTO raid_stats
            (guild_id, user_id, updated_at)
            VALUES (?, ?, ?)
            """,
            (guild_id, user_id, utc_now()),
        )
        return await self.db.fetchone(
            "SELECT * FROM raid_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def apply_verified_stat(self, guild_id: int, user_id: int, result: str, is_mvp: bool) -> None:
        await self.get_stats(guild_id, user_id)
        row = await self.db.fetchone(
            "SELECT * FROM raid_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        raids = int(row["raids"] or 0) + 1
        wins = int(row["wins"] or 0) + (1 if result == RESULT_PAG_WIN else 0)
        losses = int(row["losses"] or 0) + (1 if result == RESULT_PAG_LOSS else 0)
        draws = int(row["draws"] or 0) + (1 if result == RESULT_DRAW else 0)
        mvp = int(row["mvp"] or 0) + (1 if is_mvp else 0)
        current = int(row["current_streak"] or 0)
        best = int(row["best_streak"] or 0)
        if result == RESULT_PAG_WIN:
            current += 1
            best = max(best, current)
        elif result == RESULT_PAG_LOSS:
            current = 0
        await self.db.execute(
            """
            UPDATE raid_stats
            SET raids = ?, wins = ?, losses = ?, draws = ?, mvp = ?,
                current_streak = ?, best_streak = ?, updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (raids, wins, losses, draws, mvp, current, best, utc_now(), guild_id, user_id),
        )

    async def rankings(self, guild_id: int, order: str, limit: int = 10) -> list[Any]:
        if order == "mvp":
            query = """
                SELECT * FROM raid_stats WHERE guild_id = ?
                ORDER BY mvp DESC, wins DESC, raids DESC LIMIT ?
            """
        else:
            query = """
                SELECT * FROM raid_stats WHERE guild_id = ?
                ORDER BY wins DESC, (wins * 1.0 / NULLIF(raids, 0)) DESC,
                         raids DESC LIMIT ?
            """
        return await self.db.fetchall(query, (guild_id, min(max(limit, 1), MAX_RANKING_ROWS)))

    async def audit(
        self,
        guild_id: int,
        actor_id: int,
        action: str,
        raid_id: int | None = None,
        report_id: int | None = None,
        details: str = "",
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO raid_audit_logs
            (guild_id, raid_id, report_id, actor_id, action, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, raid_id, report_id, actor_id, action, short_text(details, 2000), utc_now()),
        )


# ============================================================
# MODALS
# ============================================================


class RaidCreateModal(discord.ui.Modal, title="⚔️ Create Raid"):
    opponent_clan = discord.ui.TextInput(
        label="Opponent Clan",
        placeholder="Örn. RIVAL",
        min_length=1,
        max_length=80,
        required=True,
    )
    note = discord.ui.TextInput(
        label="Not / Saat / Ek bilgi",
        placeholder="İsteğe bağlı",
        max_length=500,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: "Raid", author_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.create_raid_from_modal(
            interaction,
            self.author_id,
            clean_text(self.opponent_clan.value, 80),
            clean_text(self.note.value, 500),
        )


class InvitePlayerModal(discord.ui.Modal, title="👥 Invite Player"):
    user_id = discord.ui.TextInput(
        label="Discord ID / Mention",
        placeholder="123456789012345678",
        min_length=15,
        max_length=25,
        required=True,
    )

    def __init__(self, cog: "Raid", raid_id: int, inviter_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.raid_id = raid_id
        self.inviter_id = inviter_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ids = extract_user_ids(self.user_id.value)
        if len(ids) != 1:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Geçersiz ID", "Tek bir Discord kullanıcı ID'si veya mention gir."),
                ephemeral=True,
            )
            return
        await self.cog.invite_player(interaction, self.raid_id, self.inviter_id, ids[0])


class RivalPlayersModal(discord.ui.Modal, title="⚔️ Add Rival Players"):
    players = discord.ui.TextInput(
        label="Rival oyuncuları",
        placeholder="ID, ID, ID",
        min_length=15,
        max_length=300,
        required=True,
    )

    def __init__(self, cog: "Raid", raid_id: int, actor_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.raid_id = raid_id
        self.actor_id = actor_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ids = extract_user_ids(self.players.value)
        await self.cog.add_rival_players(interaction, self.raid_id, self.actor_id, ids)


class RaidResultModal(discord.ui.Modal, title="🏁 Finish Raid"):
    result = discord.ui.TextInput(
        label="Result",
        placeholder="win / loss / draw",
        min_length=3,
        max_length=10,
        required=True,
    )
    mvp = discord.ui.TextInput(
        label="MVP Discord ID / Mention",
        placeholder="İsteğe bağlı",
        max_length=25,
        required=False,
    )
    proof = discord.ui.TextInput(
        label="Proof Link",
        placeholder="Discord / video / evidence link — zorunlu",
        min_length=8,
        max_length=500,
        required=True,
    )

    def __init__(self, cog: "Raid", raid_id: int, actor_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.raid_id = raid_id
        self.actor_id = actor_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_result = self.result.value.strip().casefold()
        result = {
            "win": RESULT_PAG_WIN,
            "victory": RESULT_PAG_WIN,
            "pag win": RESULT_PAG_WIN,
            "loss": RESULT_PAG_LOSS,
            "defeat": RESULT_PAG_LOSS,
            "pag loss": RESULT_PAG_LOSS,
            "draw": RESULT_DRAW,
        }.get(raw_result)
        if not result:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Sonuç geçersiz", "`win`, `loss` veya `draw` kullan."),
                ephemeral=True,
            )
            return
        ids = extract_user_ids(self.mvp.value)
        if len(ids) > 1:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ MVP geçersiz", "MVP alanına yalnızca tek kullanıcı girilebilir."),
                ephemeral=True,
            )
            return
        await self.cog.finish_raid_from_modal(
            interaction,
            self.raid_id,
            self.actor_id,
            result,
            ids[0] if ids else None,
            self.proof.value.strip(),
        )


class RaidReportModal(discord.ui.Modal, title="📝 Report Raid"):
    # The first field accepts `OPPONENT | YYYY-MM-DD`, keeping the report
    # inside Discord's five-TextInput modal limit while retaining an explicit
    # raid date in the database.
    opponent_clan = discord.ui.TextInput(
        label="Opponent Clan | Date",
        placeholder="RIVAL | 2026-08-19",
        max_length=100,
        required=True,
    )
    players = discord.ui.TextInput(
        label="PAG Players — ID / mention listesi",
        placeholder="ID, ID, ID",
        min_length=15,
        max_length=300,
        required=True,
    )
    result = discord.ui.TextInput(
        label="Result — win / loss / draw",
        max_length=10,
        required=True,
    )
    mvp = discord.ui.TextInput(
        label="MVP ID / mention — opsiyonel",
        max_length=25,
        required=False,
    )
    proof_url = discord.ui.TextInput(
        label="Proof Link — ZORUNLU",
        placeholder="Discord message / video / evidence URL",
        min_length=8,
        max_length=500,
        required=True,
    )

    def __init__(self, cog: "Raid", reporter_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.reporter_id = reporter_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = {
            "win": RESULT_PAG_WIN,
            "victory": RESULT_PAG_WIN,
            "loss": RESULT_PAG_LOSS,
            "defeat": RESULT_PAG_LOSS,
            "draw": RESULT_DRAW,
        }.get(self.result.value.strip().casefold())
        players = extract_user_ids(self.players.value)
        mvp_ids = extract_user_ids(self.mvp.value)
        proof = self.proof_url.value.strip()
        raw_opponent_date = self.opponent_clan.value.strip()
        if "|" in raw_opponent_date:
            opponent_clan, raid_date = [part.strip() for part in raw_opponent_date.split("|", 1)]
        else:
            opponent_clan = raw_opponent_date
            raid_date = datetime.now(timezone.utc).date().isoformat()
        try:
            datetime.fromisoformat(raid_date)
        except ValueError:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Tarih geçersiz", "Tarihi `YYYY-MM-DD` formatında gir. Örn: `2026-08-19`."),
                ephemeral=True,
            )
            return

        if not result:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Result geçersiz", "`win`, `loss` veya `draw` kullan."),
                ephemeral=True,
            )
            return
        if not players or len(players) > TEAM_SIZE:
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Oyuncu listesi geçersiz", "1–3 PAG oyuncusu girmelisin."),
                ephemeral=True,
            )
            return
        if len(mvp_ids) > 1 or (mvp_ids and mvp_ids[0] not in players):
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ MVP geçersiz", "MVP, gönderdiğin PAG oyuncularından biri olmalı."),
                ephemeral=True,
            )
            return
        if not re.match(r"^https?://\S+$", proof):
            await interaction.response.send_message(
                embed=RaidEmbeds.error("❌ Proof Link zorunlu", "Geçerli bir `http://` veya `https://` kanıt bağlantısı gir."),
                ephemeral=True,
            )
            return

        await self.cog.create_report_from_modal(
            interaction,
            self.reporter_id,
            clean_text(opponent_clan, 80),
            players,
            result,
            mvp_ids[0] if mvp_ids else None,
            proof,
            raid_date,
        )


class RaidReviewNoteModal(discord.ui.Modal, title="🛡️ Raid Review"):
    note = discord.ui.TextInput(
        label="Review note",
        placeholder="Onay/reddetme gerekçesi",
        max_length=500,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: "Raid", report_id: int, reviewer_id: int, approve: bool) -> None:
        super().__init__()
        self.cog = cog
        self.report_id = report_id
        self.reviewer_id = reviewer_id
        self.approve = approve

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.review_report(
            interaction,
            self.report_id,
            self.reviewer_id,
            self.approve,
            clean_text(self.note.value, 500),
        )


# ============================================================
# PERSISTENT / INTERACTIVE VIEWS
# ============================================================


class RaidPanelView(discord.ui.View):
    def __init__(self, cog: "Raid") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="⚔ CREATE RAID", style=discord.ButtonStyle.success, custom_id="pagraid:panel:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RaidCreateModal(self.cog, interaction.user.id))

    @discord.ui.button(label="JOIN RAID", style=discord.ButtonStyle.primary, custom_id="pagraid:panel:active")
    async def active(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.send_active_raids(interaction)

    @discord.ui.button(label="🏆 MVP RANKING", style=discord.ButtonStyle.secondary, custom_id="pagraid:panel:mvp")
    async def mvp(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.send_ranking(interaction, "mvp")

    @discord.ui.button(label="📊 RAID RANKING", style=discord.ButtonStyle.secondary, custom_id="pagraid:panel:ranking")
    async def ranking(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.send_ranking(interaction, "wins")

    @discord.ui.button(label="👤 MY PROFILE", style=discord.ButtonStyle.secondary, custom_id="pagraid:panel:profile")
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.send_profile(interaction, interaction.user.id)

    @discord.ui.button(label="📜 RAID HISTORY", style=discord.ButtonStyle.secondary, custom_id="pagraid:panel:history", row=1)
    async def history(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.send_history(interaction, interaction.user.id)

    @discord.ui.button(label="📝 REPORT RAID", style=discord.ButtonStyle.danger, custom_id="pagraid:panel:report", row=1)
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RaidReportModal(self.cog, interaction.user.id))


class RaidActionButton(discord.ui.Button):
    def __init__(self, cog: "Raid", raid_id: int, action: str, *, row: int = 0) -> None:
        labels = {
            "join": ("JOIN", discord.ButtonStyle.success),
            "leave": ("LEAVE", discord.ButtonStyle.secondary),
            "invite": ("INVITE", discord.ButtonStyle.primary),
            "rivals": ("CALL PLAYER", discord.ButtonStyle.secondary),
            "finish": ("FINISH", discord.ButtonStyle.success),
            "cancel": ("CANCEL", discord.ButtonStyle.danger),
        }
        label, style = labels[action]
        super().__init__(
            label=f"⚔ {label}" if action == "join" else label,
            style=style,
            custom_id=f"pagraid:raid:{raid_id}:{action}",
            row=row,
        )
        self.cog = cog
        self.raid_id = raid_id
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        handlers = {
            "join": self.cog.join_raid,
            "leave": self.cog.leave_raid,
            "invite": self.cog.open_invite_modal,
            "rivals": self.cog.open_rival_modal,
            "finish": self.cog.open_finish_modal,
            "cancel": self.cog.cancel_raid_interaction,
        }
        handler = handlers[self.action]
        await handler(interaction, self.raid_id)


class RaidActionView(discord.ui.View):
    def __init__(self, cog: "Raid", raid_id: int, is_manager: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.raid_id = raid_id
        self.add_item(RaidActionButton(cog, raid_id, "join", row=0))
        self.add_item(RaidActionButton(cog, raid_id, "leave", row=0))
        self.add_item(RaidActionButton(cog, raid_id, "invite", row=0))
        self.add_item(RaidActionButton(cog, raid_id, "rivals", row=1))
        self.add_item(RaidActionButton(cog, raid_id, "finish", row=1))
        # Permission is checked inside the callback. Keeping the button present
        # also makes the persistent message identical after a bot restart.
        self.add_item(RaidActionButton(cog, raid_id, "cancel", row=1))


class InviteActionButton(discord.ui.Button):
    def __init__(self, cog: "Raid", invite_id: int, accept: bool) -> None:
        self.cog = cog
        self.invite_id = invite_id
        self.accept_action = accept
        super().__init__(
            label="ACCEPT" if accept else "DECLINE",
            style=discord.ButtonStyle.success if accept else discord.ButtonStyle.danger,
            custom_id=f"pagraid:invite:{invite_id}:{'accept' if accept else 'decline'}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.respond_invite(interaction, self.invite_id, self.accept_action)


class InviteView(discord.ui.View):
    def __init__(self, cog: "Raid", invite_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(InviteActionButton(cog, invite_id, True))
        self.add_item(InviteActionButton(cog, invite_id, False))


# ============================================================
# RAID COG
# ============================================================


class Raid(commands.Cog):
    """Production-oriented PAG Raid system."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger: logging.Logger = getattr(bot, "logger", logging.getLogger(LOGGER_NAME))
        self.database = getattr(bot, "database", None)
        if self.database is None:
            raise RuntimeError("PAGBot.database is required by Raid cog.")
        self.store = RaidStore(self.database, self.logger)
        self._guild_locks: dict[int, asyncio.Lock] = {}
        self._persistent_raid_views: set[int] = set()

    async def cog_load(self) -> None:
        await self.store.ensure_schema()
        self.bot.add_view(RaidPanelView(self))
        await self.restore_persistent_raid_views()
        self.logger.info("Raid cog loaded; persistent views restored.")

    # ========================================================
    # LOCKING / PERMISSIONS
    # ========================================================

    def guild_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._guild_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._guild_locks[guild_id] = lock
        return lock

    async def get_config(self, guild_id: int) -> Any:
        return await self.store.get_config(guild_id)

    async def is_manager(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        config = await self.get_config(member.guild.id)
        if not config:
            return False
        allowed = {int(config["manager_role_id"] or 0), int(config["staff_role_id"] or 0)}
        return any(role.id in allowed for role in member.roles if role.id in allowed)

    async def require_manager(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await self.safe_interaction_error(interaction, "Bu işlem yalnızca sunucuda kullanılabilir.")
            return False
        if await self.is_manager(interaction.user):
            return True
        await self.safe_interaction_error(interaction, "Bu işlem için Raid Manager / Staff yetkisi gerekiyor.")
        return False

    async def safe_interaction_error(self, interaction: discord.Interaction, message: str) -> None:
        embed = RaidEmbeds.error("❌ Raid System", message)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass

    async def ensure_guild(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await self.safe_interaction_error(interaction, "Raid sistemi DM üzerinden kullanılamaz.")
            return False
        return True

    # ========================================================
    # CHANNEL MANAGEMENT
    # ========================================================

    async def get_or_create_category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        config = await self.get_config(guild.id)
        category_id = int(config["category_id"] or 0) if config else 0
        if category_id:
            channel = guild.get_channel(category_id)
            if isinstance(channel, discord.CategoryChannel):
                return channel
        try:
            return await guild.create_category("⚔ RAID NETWORK", reason="PAG Raid System category")
        except discord.Forbidden:
            self.logger.warning("Cannot create raid category in guild %s", guild.id)
            return None

    async def create_raid_channel(self, guild: discord.Guild, raid_id: int, player_ids: Iterable[int]) -> discord.TextChannel | None:
        category = await self.get_or_create_category(guild)
        config = await self.get_config(guild.id)
        manager_role_id = int(config["manager_role_id"] or 0) if config else 0
        staff_role_id = int(config["staff_role_id"] or 0) if config else 0

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
            )
        for user_id in set(player_ids):
            member = guild.get_member(user_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
        for role_id in (manager_role_id, staff_role_id):
            role = guild.get_role(role_id) if role_id else None
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                )
        try:
            channel = await guild.create_text_channel(
                f"raid-chat-{raid_id:02d}",
                category=category,
                overwrites=overwrites,
                topic=f"PAG RAID #{raid_id} • Private raid room",
                reason=f"PAG Raid #{raid_id}",
            )
            return channel
        except (discord.Forbidden, discord.HTTPException) as exc:
            self.logger.error("Raid channel creation failed for #%s: %s", raid_id, exc)
            return None

    async def sync_raid_channel_permissions(self, raid: Any) -> None:
        guild = self.bot.get_guild(int(raid["guild_id"]))
        if not guild or not raid["channel_id"]:
            return
        channel = guild.get_channel(int(raid["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        players = await self.store.get_players(int(raid["id"]))
        desired_ids = {int(row["user_id"]) for row in players if row["left_at"] is None}
        for member in list(channel.members):
            if member.id not in desired_ids and member != guild.me:
                try:
                    await channel.set_permissions(member, overwrite=None, reason="Raid membership sync")
                except discord.HTTPException:
                    pass
        for user_id in desired_ids:
            member = guild.get_member(user_id)
            if member:
                try:
                    await channel.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="Raid membership sync",
                    )
                except discord.HTTPException:
                    pass

    async def archive_or_delete_channel(self, raid: Any) -> None:
        guild = self.bot.get_guild(int(raid["guild_id"]))
        if not guild or not raid["channel_id"]:
            return
        channel = guild.get_channel(int(raid["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        config = await self.get_config(guild.id)
        archive = bool(config["archive_channels"]) if config else True
        try:
            if archive:
                await channel.edit(name=f"archived-raid-{int(raid['id']):02d}", sync_permissions=False, reason="Raid completed")
                await channel.set_permissions(guild.default_role, view_channel=False)
            else:
                await channel.delete(reason="Raid completed")
        except discord.HTTPException as exc:
            self.logger.warning("Raid channel archive/delete failed: %s", exc)

    # ========================================================
    # PANEL
    # ========================================================

    async def raidpanel(self, interaction: discord.Interaction) -> None:
        if not await self.ensure_guild(interaction):
            return
        if not await self.require_manager(interaction):
            return
        await interaction.response.send_message(embed=RaidEmbeds.center(), view=RaidPanelView(self))
        message = await interaction.original_response()
        await self.store.set_config(
            interaction.guild.id,
            board_channel_id=message.channel.id,
            category_id=(await self.get_config(interaction.guild.id))["category_id"] if await self.get_config(interaction.guild.id) else None,
            manager_role_id=(await self.get_config(interaction.guild.id))["manager_role_id"] if await self.get_config(interaction.guild.id) else None,
            staff_role_id=(await self.get_config(interaction.guild.id))["staff_role_id"] if await self.get_config(interaction.guild.id) else None,
            archive_channels=bool((await self.get_config(interaction.guild.id))["archive_channels"]) if await self.get_config(interaction.guild.id) else True,
        )

    async def raidsetup(
        self,
        interaction: discord.Interaction,
        board_channel: discord.TextChannel,
        category: discord.CategoryChannel,
        manager_role: discord.Role,
        staff_role: discord.Role | None = None,
        archive: bool = True,
    ) -> None:
        if not await self.ensure_guild(interaction) or not await self.require_manager(interaction):
            return
        await self.store.set_config(
            interaction.guild.id,
            board_channel_id=board_channel.id,
            category_id=category.id,
            manager_role_id=manager_role.id,
            staff_role_id=staff_role.id if staff_role else None,
            archive_channels=archive,
        )
        await interaction.response.send_message(
            embed=RaidEmbeds.success(
                "✅ Raid Setup",
                f"Board: {board_channel.mention}\nKategori: `{category.name}`\nManager: {manager_role.mention}\nStaff: {staff_role.mention if staff_role else 'Ayarlanmadı'}\nArşiv: `{archive}`",
            ),
            ephemeral=True,
        )

    # ========================================================
    # CREATE / JOIN
    # ========================================================

    async def create_raid_from_modal(self, interaction: discord.Interaction, creator_id: int, opponent_clan: str, note: str) -> None:
        if not await self.ensure_guild(interaction):
            return
        guild = interaction.guild
        lock = self.guild_lock(guild.id)
        async with lock:
            existing = await self.store.get_active_raids(guild.id)
            if any(int(row["creator_id"]) == creator_id for row in existing):
                await self.safe_interaction_error(interaction, "Zaten aktif bir Raid'in var. Önce onu tamamla veya ayrıl.")
                return
            raid_id = await self.store.create_raid(guild.id, creator_id, opponent_clan, note)
            await self.store.add_player(raid_id, guild.id, creator_id, "pag")
            await self.store.audit(guild.id, creator_id, "raid_created", raid_id, details=opponent_clan)
            raid = await self.store.get_raid(raid_id, guild.id)
            channel = await self.create_raid_channel(guild, raid_id, [creator_id])
            if channel:
                await self.store.update_raid_message(raid_id, channel.id, None)
            raid = await self.store.get_raid(raid_id, guild.id)
            pag = await self.store.get_player_ids(raid_id, "pag")
            opp = await self.store.get_player_ids(raid_id, "opponent")
            embed = RaidEmbeds.raid(raid, pag, opp, guild)
            view = RaidActionView(self, raid_id, await self.is_manager(guild.get_member(creator_id) or guild.me))
            if channel:
                message = await channel.send(embed=embed, view=view)
                await self.store.update_raid_message(raid_id, channel.id, message.id)
                self.bot.add_view(view, message_id=message.id)
                self._persistent_raid_views.add(raid_id)
            await interaction.response.send_message(
                embed=RaidEmbeds.success("⚔️ Raid oluşturuldu", f"Raid **#{raid_id}** hazır. {channel.mention if channel else 'Özel raid kanalı oluşturulamadı.'}"),
                ephemeral=True,
            )

    async def join_raid(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        guild = interaction.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self.safe_interaction_error(interaction, "Bu Raid artık katılıma açık değil.")
                return
            if await self.store.is_player_in_raid(raid_id, interaction.user.id):
                await self.safe_interaction_error(interaction, "Zaten bu Raid'desin.")
                return
            active = await self.store.get_active_raids(guild.id)
            for other in active:
                if int(other["id"]) != raid_id and await self.store.is_player_in_raid(int(other["id"]), interaction.user.id):
                    await self.safe_interaction_error(interaction, f"Zaten **#{other['id']}** Raid'inde bulunuyorsun.")
                    return
            pag = await self.store.get_player_ids(raid_id, "pag")
            if len(pag) >= TEAM_SIZE:
                await self.safe_interaction_error(interaction, "PAG tarafı 3/3 dolu. Rakip taraf için Raid Manager oyuncu ekleyebilir.")
                return
            await self.store.add_player(raid_id, guild.id, interaction.user.id, "pag")
            await self.store.audit(guild.id, interaction.user.id, "raid_joined", raid_id)
            await self.maybe_activate_raid(raid_id, guild)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(await self.store.get_raid(raid_id, guild.id))
            await interaction.response.send_message(
                embed=RaidEmbeds.success("✅ Raid'e katıldın", f"Raid **#{raid_id}** kadrosuna eklendin."),
                ephemeral=True,
            )

    async def leave_raid(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        guild = interaction.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            player = await self.store.is_player_in_raid(raid_id, interaction.user.id)
            if not raid or not player or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self.safe_interaction_error(interaction, "Bu Raid'den ayrılamazsın.")
                return
            if int(raid["creator_id"]) == interaction.user.id and raid["status"] == STATUS_ACTIVE:
                await self.safe_interaction_error(interaction, "Aktif Raid hostu aktif Raid'den ayrılamaz; Raid'i bitir veya yöneticiye devret.")
                return
            await self.store.remove_player(raid_id, interaction.user.id)
            await self.store.audit(guild.id, interaction.user.id, "raid_left", raid_id)
            if raid["status"] == STATUS_ACTIVE:
                await self.store.update_status(raid_id, STATUS_RECRUITING)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(await self.store.get_raid(raid_id, guild.id))
            await interaction.response.send_message(embed=RaidEmbeds.success("👋 Ayrıldın", "Raid kadrosundan çıkarıldın."), ephemeral=True)

    async def maybe_activate_raid(self, raid_id: int, guild: discord.Guild) -> None:
        pag = await self.store.get_player_ids(raid_id, "pag")
        opp = await self.store.get_player_ids(raid_id, "opponent")
        raid = await self.store.get_raid(raid_id, guild.id)
        if not raid:
            return
        if len(pag) >= TEAM_SIZE and len(opp) >= TEAM_SIZE and raid["status"] != STATUS_ACTIVE:
            await self.store.update_status(raid_id, STATUS_ACTIVE, utc_now())
            await self.store.audit(guild.id, int(raid["creator_id"]), "raid_activated", raid_id)

    async def invite_player(self, interaction: discord.Interaction, raid_id: int, inviter_id: int, invitee_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        guild = interaction.guild
        raid = await self.store.get_raid(raid_id, guild.id)
        if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
            await self.safe_interaction_error(interaction, "Raid artık aktif/recruiting değil.")
            return
        if not (await self.store.is_player_in_raid(raid_id, inviter_id)):
            await self.safe_interaction_error(interaction, "Önce Raid'e katılmalısın.")
            return
        pag = await self.store.get_player_ids(raid_id, "pag")
        if len(pag) >= TEAM_SIZE:
            await self.safe_interaction_error(interaction, "PAG kadrosu dolu.")
            return
        member = guild.get_member(invitee_id)
        if not member or member.bot:
            await self.safe_interaction_error(interaction, "Geçerli bir sunucu üyesi bulunamadı.")
            return
        if await self.store.is_player_in_raid(raid_id, invitee_id):
            await self.safe_interaction_error(interaction, "Bu oyuncu zaten Raid'de.")
            return
        await self.store.add_invite(raid_id, guild.id, inviter_id, invitee_id, "pag")
        invite_row = await self.database.fetchone(
            "SELECT * FROM raid_invites WHERE raid_id = ? AND invitee_id = ?",
            (raid_id, invitee_id),
        )
        if not invite_row:
            await self.safe_interaction_error(interaction, "Davet kaydedilemedi.")
            return
        invite_id = int(invite_row["id"])
        try:
            await member.send(
                embed=RaidEmbeds.info(
                    "⚔️ PAG Raid Invitation",
                    f"**#{raid_id}** numaralı Raid'e davet edildin.\n\nOpponent: **{raid['opponent_clan']}**\nFormat: `3v3`",
                ),
                view=InviteView(self, invite_id),
            )
        except discord.Forbidden:
            await self.safe_interaction_error(interaction, "Oyuncunun DM'i kapalı. Davet kaydedildi ancak DM gönderilemedi.")
            return
        self.bot.add_view(InviteView(self, invite_id))
        await self.store.audit(guild.id, inviter_id, "player_invited", raid_id, details=str(invitee_id))
        await interaction.response.send_message(embed=RaidEmbeds.success("📨 Davet gönderildi", f"{member.mention} oyuncusuna davet gönderildi."), ephemeral=True)

    async def respond_invite(self, interaction: discord.Interaction, invite_id: int, accept: bool) -> None:
        invite = await self.store.get_invite(invite_id)
        if not invite:
            await self.safe_interaction_error(interaction, "Davet bulunamadı.")
            return
        if int(invite["invitee_id"]) != interaction.user.id:
            await self.safe_interaction_error(interaction, "Bu davet sana ait değil.")
            return
        if invite["status"] != "pending":
            await self.safe_interaction_error(interaction, "Bu davet daha önce cevaplanmış.")
            return
        guild = self.bot.get_guild(int(invite["guild_id"]))
        if not guild:
            await self.safe_interaction_error(interaction, "Sunucu bulunamadı.")
            return
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(int(invite["raid_id"]), guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self.store.set_invite_status(invite_id, "expired")
                await self.safe_interaction_error(interaction, "Raid artık aktif değil.")
                return
            if not accept:
                await self.store.set_invite_status(invite_id, "declined")
                await interaction.response.send_message(embed=RaidEmbeds.warning("Davet reddedildi", "Raid davetini reddettin."), ephemeral=True)
                return
            pag = await self.store.get_player_ids(int(invite["raid_id"]), "pag")
            if len(pag) >= TEAM_SIZE:
                await self.safe_interaction_error(interaction, "PAG kadrosu dolmuş.")
                return
            if await self.store.is_player_in_raid(int(invite["raid_id"]), interaction.user.id):
                await self.store.set_invite_status(invite_id, "accepted")
                await self.safe_interaction_error(interaction, "Zaten bu Raid'desin.")
                return
            await self.store.add_player(int(invite["raid_id"]), guild.id, interaction.user.id, "pag")
            await self.store.set_invite_status(invite_id, "accepted")
            await self.maybe_activate_raid(int(invite["raid_id"]), guild)
            await self.refresh_raid_message(int(invite["raid_id"]), guild)
            await self.sync_raid_channel_permissions(await self.store.get_raid(int(invite["raid_id"]), guild.id))
            await interaction.response.send_message(embed=RaidEmbeds.success("✅ Raid daveti kabul edildi", f"**#{invite['raid_id']}** Raid'ine katıldın."), ephemeral=True)

    # ========================================================
    # RIVAL / RESULT
    # ========================================================

    async def add_rival_players(self, interaction: discord.Interaction, raid_id: int, actor_id: int, ids: list[int]) -> None:
        if not await self.require_manager(interaction):
            return
        if not ids or len(ids) > TEAM_SIZE:
            await self.safe_interaction_error(interaction, "1–3 rakip oyuncu ID'si gir.")
            return
        guild = interaction.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self.safe_interaction_error(interaction, "Raid artık kadro düzenlemeye açık değil.")
                return
            current = await self.store.get_player_ids(raid_id, "opponent")
            if len(current) + len(ids) > TEAM_SIZE:
                await self.safe_interaction_error(interaction, "Rival tarafında 3 oyuncu sınırı var.")
                return
            added = 0
            for user_id in ids:
                member = guild.get_member(user_id)
                if not member or member.bot:
                    continue
                if await self.store.is_player_in_raid(raid_id, user_id):
                    continue
                await self.store.add_player(raid_id, guild.id, user_id, "opponent")
                added += 1
            if not added:
                await self.safe_interaction_error(interaction, "Eklenebilecek geçerli rakip oyuncu bulunamadı.")
                return
            await self.maybe_activate_raid(raid_id, guild)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(await self.store.get_raid(raid_id, guild.id))
            await self.store.audit(guild.id, actor_id, "rival_players_added", raid_id, details=",".join(map(str, ids)))
            await interaction.response.send_message(embed=RaidEmbeds.success("⚔️ Rival oyuncular eklendi", f"**{added}** oyuncu rakip tarafına eklendi."), ephemeral=True)

    async def finish_raid_from_modal(
        self,
        interaction: discord.Interaction,
        raid_id: int,
        actor_id: int,
        result: str,
        mvp_id: int | None,
        proof_url: str,
    ) -> None:
        guild = interaction.guild
        if not guild:
            await self.safe_interaction_error(interaction, "Sunucu bulunamadı.")
            return
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_ACTIVE, STATUS_RECRUITING}:
                await self.safe_interaction_error(interaction, "Bu Raid bitirilemez.")
                return
            pag = await self.store.get_player_ids(raid_id, "pag")
            opp = await self.store.get_player_ids(raid_id, "opponent")
            if not pag:
                await self.safe_interaction_error(interaction, "Raid'de en az bir PAG oyuncusu olmalı.")
                return
            if mvp_id is not None and mvp_id not in pag:
                await self.safe_interaction_error(interaction, "MVP PAG kadrosunda olmalı.")
                return
            if not re.match(r"^https?://\S+$", proof_url):
                await self.safe_interaction_error(interaction, "Proof Link geçerli bir HTTP(S) bağlantısı olmalı.")
                return
            if len(pag) < TEAM_SIZE or len(opp) < TEAM_SIZE:
                if not await self.is_manager(interaction.user):
                    await self.safe_interaction_error(interaction, "3v3 tamamlanmadan Raid'i yalnızca Raid Manager/Staff bitirebilir.")
                    return
            await self.store.finish_raid(raid_id, result, mvp_id, utc_now(), actor_id, proof_url)
            # Live raids are explicitly completed by an authorized actor, so they
            # are treated as verified at completion. Stats are applied exactly once
            # because status was still recruiting/active here.
            for user_id in pag:
                await self.store.apply_verified_stat(guild.id, user_id, result, user_id == mvp_id)
            await self.store.audit(guild.id, actor_id, "raid_verified_completed", raid_id, details=result)
            await self.refresh_raid_message(raid_id, guild)
            await self.archive_or_delete_channel(await self.store.get_raid(raid_id, guild.id))
            await interaction.response.send_message(embed=RaidEmbeds.success("🏁 Raid tamamlandı", f"Raid **#{raid_id}** sonucu `{result_label(result)}` olarak doğrulandı."), ephemeral=True)

    async def cancel_raid_interaction(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not await self.require_manager(interaction):
            return
        guild = interaction.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] in {STATUS_COMPLETED, STATUS_CANCELLED}:
                await self.safe_interaction_error(interaction, "Bu Raid zaten kapanmış.")
                return
            await self.store.cancel_raid(raid_id)
            await self.store.audit(guild.id, interaction.user.id, "raid_cancelled", raid_id)
            await self.refresh_raid_message(raid_id, guild)
            await self.archive_or_delete_channel(await self.store.get_raid(raid_id, guild.id))
            await interaction.response.send_message(embed=RaidEmbeds.success("🔴 Raid iptal edildi", f"Raid **#{raid_id}** iptal edildi."), ephemeral=True)

    async def open_invite_modal(self, interaction: discord.Interaction, raid_id: int) -> None:
        await interaction.response.send_modal(InvitePlayerModal(self, raid_id, interaction.user.id))

    async def open_rival_modal(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not await self.require_manager(interaction):
            return
        await interaction.response.send_modal(RivalPlayersModal(self, raid_id, interaction.user.id))

    async def open_finish_modal(self, interaction: discord.Interaction, raid_id: int) -> None:
        await interaction.response.send_modal(RaidResultModal(self, raid_id, interaction.user.id))

    # ========================================================
    # REFRESH / RESTORE
    # ========================================================

    async def refresh_raid_message(self, raid_id: int, guild: discord.Guild) -> None:
        raid = await self.store.get_raid(raid_id, guild.id)
        if not raid or not raid["channel_id"] or not raid["message_id"]:
            return
        channel = guild.get_channel(int(raid["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(raid["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        pag = await self.store.get_player_ids(raid_id, "pag")
        opp = await self.store.get_player_ids(raid_id, "opponent")
        try:
            await message.edit(
                embed=RaidEmbeds.raid(raid, pag, opp, guild),
                view=RaidActionView(self, raid_id),
            )
        except discord.HTTPException:
            pass

    async def restore_persistent_raid_views(self) -> None:
        guilds = list(self.bot.guilds)
        for guild in guilds:
            try:
                rows = await self.store.get_active_raids(guild.id)
            except Exception:
                self.logger.exception("Failed to load active raids for guild %s", guild.id)
                continue
            for row in rows:
                message_id = row["message_id"]
                if not message_id:
                    continue
                view = RaidActionView(self, int(row["id"]))
                try:
                    self.bot.add_view(view, message_id=int(message_id))
                    self._persistent_raid_views.add(int(row["id"]))
                except (ValueError, discord.HTTPException):
                    self.logger.warning("Could not restore persistent raid view #%s", row["id"])

            try:
                invites = await self.database.fetchall(
                    """
                    SELECT id FROM raid_invites
                    WHERE guild_id = ? AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 100
                    """,
                    (guild.id,),
                )
                for invite in invites:
                    self.bot.add_view(InviteView(self, int(invite["id"])))
            except Exception:
                self.logger.exception("Failed to restore pending raid invites for guild %s", guild.id)

    # ========================================================
    # ACTIVE / RANKING / PROFILE / HISTORY
    # ========================================================

    async def send_active_raids(self, interaction: discord.Interaction) -> None:
        if not await self.ensure_guild(interaction):
            return
        rows = await self.store.get_active_raids(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(
                embed=RaidEmbeds.info("⚔️ Active Raids", "Şu anda açık Raid yok."),
                ephemeral=True,
            )
            return
        embeds: list[discord.Embed] = []
        for row in rows[:10]:
            pag = await self.store.get_player_ids(int(row["id"]), "pag")
            opp = await self.store.get_player_ids(int(row["id"]), "opponent")
            embeds.append(RaidEmbeds.raid(row, pag, opp, interaction.guild))
        await interaction.response.send_message(embeds=embeds[:10], ephemeral=True)

    async def send_ranking(self, interaction: discord.Interaction, order: str) -> None:
        if not await self.ensure_guild(interaction):
            return
        rows = await self.store.rankings(interaction.guild.id, order)
        if not rows:
            await interaction.response.send_message(embed=RaidEmbeds.info("🏆 RAID RANKING", "Henüz doğrulanmış raid istatistiği yok."), ephemeral=True)
            return
        lines: list[str] = []
        for index, row in enumerate(rows, 1):
            if order == "mvp":
                lines.append(f"**#{index}** {user_mention(int(row['user_id']))} — ★ `{int(row['mvp'])}` MVP")
            else:
                lines.append(f"**#{index}** {user_mention(int(row['user_id']))} — `{int(row['wins'])} W • {int(row['losses'])} L`")
        title = "🏆 MVP RANKING" if order == "mvp" else "📊 RAID RANKING"
        await interaction.response.send_message(embed=RaidEmbeds.info(title, "\n".join(lines)), ephemeral=True)

    async def send_profile(self, interaction: discord.Interaction, user_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        stats = await self.store.get_stats(interaction.guild.id, user_id)
        await interaction.response.send_message(embed=RaidEmbeds.profile(user_id, stats), ephemeral=True)

    async def send_history(self, interaction: discord.Interaction, user_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        rows = await self.store.get_recent_raids(interaction.guild.id, user_id, 10)
        if not rows:
            await interaction.response.send_message(embed=RaidEmbeds.info("📜 RAID HISTORY", "Henüz Raid geçmişin yok."), ephemeral=True)
            return
        lines: list[str] = []
        for row in rows:
            date = parse_iso(row["ended_at"] or row["created_at"])
            stamp = f"<t:{int(date.timestamp())}:d>" if date else "—"
            lines.append(
                f"**#{row['id']}** • `{result_label(row['result']) if row['result'] else status_label(row['status'])}` • **{short_text(row['opponent_clan'], 40)}** • {stamp}"
            )
        await interaction.response.send_message(embed=RaidEmbeds.info("📜 RAID HISTORY", "\n".join(lines)), ephemeral=True)

    # ========================================================
    # REPORT / VERIFICATION
    # ========================================================

    async def create_report_from_modal(
        self,
        interaction: discord.Interaction,
        reporter_id: int,
        opponent_clan: str,
        players: list[int],
        result: str,
        mvp_id: int | None,
        proof_url: str,
        raid_date: str,
    ) -> None:
        if not await self.ensure_guild(interaction):
            return
        guild = interaction.guild
        # The reporter must be one of the reported PAG players. This prevents
        # someone from manufacturing another member's raid history anonymously.
        if reporter_id not in players:
            await self.safe_interaction_error(interaction, "Report gönderen kişi PAG Players listesinde olmalı.")
            return
        for user_id in players:
            if not guild.get_member(user_id):
                await self.safe_interaction_error(interaction, f"Oyuncu sunucuda bulunamadı: `{user_id}`")
                return
        if mvp_id and mvp_id not in players:
            await self.safe_interaction_error(interaction, "MVP, PAG Players listesindeki bir oyuncu olmalı.")
            return
        duplicate = await self.database.fetchone(
            """
            SELECT id FROM raid_reports
            WHERE guild_id = ? AND reporter_id = ? AND proof_url = ?
              AND status != 'rejected'
            LIMIT 1
            """,
            (guild.id, reporter_id, proof_url),
        )
        live_duplicate = await self.database.fetchone(
            """
            SELECT id FROM raids
            WHERE guild_id = ? AND proof_url = ? AND status = 'completed'
            LIMIT 1
            """,
            (guild.id, proof_url),
        )
        if duplicate or live_duplicate:
            await self.safe_interaction_error(interaction, "Bu Proof Link daha önce bir Raid kaydında kullanılmış.")
            return
        report_id = await self.store.create_report(
            guild.id,
            reporter_id,
            opponent_clan,
            players,
            result,
            mvp_id,
            raid_date,
            proof_url,
        )
        await self.store.audit(guild.id, reporter_id, "report_created", report_id=report_id, details=proof_url)
        await interaction.response.send_message(
            embed=RaidEmbeds.success(
                "📝 Raid Report alındı",
                f"Report **#{report_id}** `PENDING` durumunda. Staff/Raid Manager doğrulamasından sonra istatistiklere işlenecek.\n\n🔗 Proof: {proof_url}",
            ),
            ephemeral=True,
        )
        await self.notify_pending_report(guild, report_id)

    async def notify_pending_report(self, guild: discord.Guild, report_id: int) -> None:
        config = await self.get_config(guild.id)
        if not config or not config["board_channel_id"]:
            return
        channel = guild.get_channel(int(config["board_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        report = await self.store.get_report(report_id, guild.id)
        if not report:
            return
        await channel.send(
            embed=RaidEmbeds.warning(
                "🛡️ PENDING RAID REPORT",
                f"Report **#{report_id}** doğrulama bekliyor.\nReporter: {user_mention(int(report['reporter_id']))}\nOpponent: **{short_text(report['opponent_clan'], 80)}**\nResult: **{result_label(report['result'])}**\n🔗 {report['proof_url']}",
            ),
            view=RaidReportReviewView(self, report_id),
        )

    async def review_report(self, interaction: discord.Interaction, report_id: int, reviewer_id: int, approve: bool, note: str) -> None:
        if not await self.require_manager(interaction):
            return
        guild = interaction.guild
        async with self.guild_lock(guild.id):
            report = await self.store.get_report(report_id, guild.id)
            if not report:
                await self.safe_interaction_error(interaction, "Report bulunamadı.")
                return
            if report["status"] != REPORT_PENDING:
                await self.safe_interaction_error(interaction, f"Report zaten `{report['status']}` durumda.")
                return
            if not approve:
                await self.store.review_report(report_id, REPORT_REJECTED, reviewer_id, note or "Staff tarafından reddedildi.")
                await self.store.audit(guild.id, reviewer_id, "report_rejected", report_id=report_id, details=note)
                await interaction.response.send_message(embed=RaidEmbeds.warning("❌ Report reddedildi", f"Report **#{report_id}** reddedildi."), ephemeral=True)
                return
            try:
                players = [int(value) for value in json.loads(report["players_json"])]
            except (TypeError, ValueError, json.JSONDecodeError):
                await self.safe_interaction_error(interaction, "Report oyuncu verisi bozuk. Güvenlik için onaylanmadı.")
                return
            if not players or len(players) > TEAM_SIZE:
                await self.safe_interaction_error(interaction, "Report oyuncu verisi geçersiz.")
                return
            if report["mvp_id"] and int(report["mvp_id"]) not in players:
                await self.safe_interaction_error(interaction, "Report MVP verisi geçersiz.")
                return
            await self.store.review_report(report_id, REPORT_VERIFIED, reviewer_id, note or "Verified")
            for user_id in players:
                await self.store.apply_verified_stat(guild.id, user_id, report["result"], int(report["mvp_id"] or 0) == user_id)
            await self.store.audit(guild.id, reviewer_id, "report_verified", report_id=report_id, details=note)
            await interaction.response.send_message(
                embed=RaidEmbeds.success("✅ Report VERIFIED", f"Report **#{report_id}** doğrulandı ve **{len(players)}** oyuncunun istatistiğine işlendi."),
                ephemeral=True,
            )

    async def raidreview(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        rows = await self.store.get_pending_reports(interaction.guild.id, 10)
        if not rows:
            await interaction.response.send_message(embed=RaidEmbeds.info("🛡️ RAID REVIEW", "Bekleyen report yok."), ephemeral=True)
            return
        lines = [
            f"**#{row['id']}** • {user_mention(int(row['reporter_id']))} • **{short_text(row['opponent_clan'], 50)}** • `{result_label(row['result'])}`\n🔗 {row['proof_url']}"
            for row in rows
        ]
        await interaction.response.send_message(
            embed=RaidEmbeds.warning("🛡️ RAID REVIEW", "\n\n".join(lines)),
            view=RaidReviewListView(self, [int(row["id"]) for row in rows]),
            ephemeral=True,
        )

    # ========================================================
    # ADMIN / DIRECT COMMANDS
    # ========================================================

    async def raidfinish(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not await self.ensure_guild(interaction):
            return
        raid = await self.store.get_raid(raid_id, interaction.guild.id)
        if not raid:
            await self.safe_interaction_error(interaction, "Raid bulunamadı.")
            return
        if int(raid["creator_id"]) != interaction.user.id and not await self.is_manager(interaction.user):
            await self.safe_interaction_error(interaction, "Raid'i yalnızca host veya Raid Manager bitirebilir.")
            return
        await interaction.response.send_modal(RaidResultModal(self, raid_id, interaction.user.id))

    async def raidcancel(self, interaction: discord.Interaction, raid_id: int) -> None:
        await self.cancel_raid_interaction(interaction, raid_id)

    async def raidprofile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await self.send_profile(interaction, (member or interaction.user).id)

    async def raidactive(self, interaction: discord.Interaction) -> None:
        await self.send_active_raids(interaction)

    # ========================================================
    # PREFIX COMMANDS — ! ONLY
    # ========================================================

    async def _prefix_send(self, ctx: commands.Context, *, embed: discord.Embed, delete_after: float | None = None):
        try:
            return await ctx.send(embed=embed, delete_after=delete_after)
        except discord.HTTPException as exc:
            self.logger.warning("Raid prefix send failed: %s", exc)
            return None

    async def _prefix_manager(self, ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Sunucu Komutu", "Bu komut yalnızca sunucuda kullanılabilir."))
            return False
        if await self.is_manager(ctx.author):
            return True
        await self._prefix_send(ctx, embed=RaidEmbeds.error("🛡️ Yetki Gerekli", "Bu işlem yalnızca Raid Manager / Staff / yetkili kullanıcılar tarafından kullanılabilir."))
        return False

    @commands.command(name="raidhelp", aliases=["raidcommands", "raidmenu"])
    @commands.guild_only()
    async def raidhelp_prefix(self, ctx: commands.Context) -> None:
        embed = RaidEmbeds.info(
            "⚔️ PAG RAID COMMAND CENTER",
            "Tüm RAID işlemleri `!` prefix ile kullanılabilir. Buton paneli yardımcı arayüz olarak da kullanılabilir.",
        )
        embed.add_field(
            name="👥 Üye Komutları",
            value=(
                "`!raidcreate clan | Not` — Raid oluştur\n"
                "`!raidjoin <id>` — Raid'e katıl\n"
                "`!raidleave <id>` — Raid'den ayrıl\n"
                "`!raidinvite <id> @üye` — Oyuncu davet et\n"
                "`!raidaccept <invite_id>` / `!raiddecline <invite_id>` — Davet cevapla\n"
                "`!raidactive` — Aktif Raidler\n"
                "`!raidprofile [@üye]` — Profil\n"
                "`!raidhistory [@üye]` — Geçmiş\n"
                "`!raidreport ...` — Manuel Report\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️ Raid Manager / Staff",
            value=(
                "`!raidpanel` — Raid Center gönder\n"
                "`!raidsetup #kanal #kategori @manager [@staff] [archive]`\n"
                "`!raidaddopponents <id> @a @b @c`\n"
                "`!raidfinish <id> <win|loss|draw> [@mvp] <proof>`\n"
                "`!raidcancel <id>`\n"
                "`!raidreview` — Pending reportlar\n"
                "`!raidreview <id> <verify|reject> [not]`\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏆 İstatistik",
            value="`!raidmvp` • `!raidranking` • `!raidprofile` • `!raidhistory`",
            inline=False,
        )
        embed.add_field(
            name="🧾 Manuel Report Formatı",
            value=(
                "`!raidreport RIVAL | 2026-08-20 | @P1 @P2 @P3 | win | @MVP | https://proof`\n"
                "Proof Link **zorunlu**. Report önce `PENDING`, sonra staff doğrulamasıyla `VERIFIED` olur."
            ),
            inline=False,
        )
        embed.set_footer(text="PAG RAID SYSTEM • Prefix Mode • !raidhelp")
        await self._prefix_send(ctx, embed=embed)

    @commands.command(name="raidpanel")
    @commands.guild_only()
    async def raidpanel_prefix(self, ctx: commands.Context) -> None:
        if not await self._prefix_manager(ctx):
            return
        config = await self.get_config(ctx.guild.id)
        message = await ctx.send(embed=RaidEmbeds.center(), view=RaidPanelView(self))
        await self.store.set_config(
            ctx.guild.id,
            board_channel_id=message.channel.id,
            category_id=int(config["category_id"]) if config and config["category_id"] else None,
            manager_role_id=int(config["manager_role_id"]) if config and config["manager_role_id"] else None,
            staff_role_id=int(config["staff_role_id"]) if config and config["staff_role_id"] else None,
            archive_channels=bool(config["archive_channels"]) if config else True,
        )
        self.logger.info("Raid panel sent in guild %s by %s", ctx.guild.id, ctx.author.id)

    @commands.command(name="raidsetup")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def raidsetup_prefix(
        self,
        ctx: commands.Context,
        board_channel: discord.TextChannel,
        category: discord.CategoryChannel,
        manager_role: discord.Role,
        *options: str,
    ) -> None:
        if not await self._prefix_manager(ctx):
            return
        # Optional staff role + archive switch are deliberately parsed from the
        # message instead of relying on fragile optional converters.
        staff_role = None
        mentioned_roles = [r for r in ctx.message.role_mentions if r.id != manager_role.id]
        if mentioned_roles:
            staff_role = mentioned_roles[0]
        lowered = {str(option).casefold() for option in options}
        archive_value = not bool(lowered & {"false", "0", "no", "off", "delete", "sil", "--delete"})
        await self.store.set_config(
            ctx.guild.id,
            board_channel_id=board_channel.id,
            category_id=category.id,
            manager_role_id=manager_role.id,
            staff_role_id=staff_role.id if staff_role else None,
            archive_channels=archive_value,
        )
        await self._prefix_send(
            ctx,
            embed=RaidEmbeds.success(
                "✅ Raid Setup Tamamlandı",
                (
                    f"**Board:** {board_channel.mention}\n"
                    f"**Kategori:** `{category.name}`\n"
                    f"**Manager:** {manager_role.mention}\n"
                    f"**Staff:** {staff_role.mention if staff_role else 'Ayarlanmadı'}\n"
                    f"**Bitince arşivle:** `{archive_value}`"
                ),
            ),
        )

    @commands.command(name="raidcreate", aliases=["createraid", "raidnew"])
    @commands.guild_only()
    async def raidcreate_prefix(self, ctx: commands.Context, *, raw: str = "") -> None:
        opponent, sep, note = raw.partition("|")
        opponent = clean_text(opponent, 80)
        note = clean_text(note if sep else "", 500)
        if not opponent:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Eksik Bilgi", "Kullanım: `!raidcreate clan | isteğe bağlı not`"))
            return
        guild = ctx.guild
        creator = ctx.author
        lock = self.guild_lock(guild.id)
        async with lock:
            existing = await self.store.get_active_raids(guild.id)
            if any(await self.store.is_player_in_raid(int(row["id"]), creator.id) for row in existing):
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Zaten Aktif Raid", "Aynı anda birden fazla Raid'e katılamazsın."))
                return
            raid_id = await self.store.create_raid(guild.id, creator.id, opponent, note)
            await self.store.add_player(raid_id, guild.id, creator.id, "pag")
            await self.store.audit(guild.id, creator.id, "raid_created", raid_id, details=opponent)
            raid = await self.store.get_raid(raid_id, guild.id)
            channel = await self.create_raid_channel(guild, raid_id, [creator.id])
            if channel:
                await self.store.update_raid_message(raid_id, channel.id, None)
                raid = await self.store.get_raid(raid_id, guild.id)
                pag = await self.store.get_player_ids(raid_id, "pag")
                opp = await self.store.get_player_ids(raid_id, "opponent")
                view = RaidActionView(self, raid_id, await self.is_manager(creator))
                message = await channel.send(embed=RaidEmbeds.raid(raid, pag, opp, guild), view=view)
                await self.store.update_raid_message(raid_id, channel.id, message.id)
                try:
                    self.bot.add_view(view, message_id=message.id)
                except (discord.HTTPException, ValueError):
                    pass
            await self._prefix_send(
                ctx,
                embed=RaidEmbeds.success(
                    "⚔️ Raid Oluşturuldu",
                    f"**Raid:** `#{raid_id}`\n**Opponent:** `{opponent}`\n**Format:** `3v3`\n**Room:** {channel.mention if channel else 'oluşturulamadı'}",
                ),
            )

    @commands.command(name="raidjoin", aliases=["joinraid"])
    @commands.guild_only()
    async def raidjoin_prefix(self, ctx: commands.Context, raid_id: int) -> None:
        guild = ctx.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Bulunamadı", "Raid yok, kapalı veya artık katılıma açık değil."))
                return
            if await self.store.is_player_in_raid(raid_id, ctx.author.id):
                await self._prefix_send(ctx, embed=RaidEmbeds.warning("ℹ️ Zaten İçeridesin", f"**#{raid_id}** Raid'inde zaten bulunuyorsun."))
                return
            for other in await self.store.get_active_raids(guild.id):
                if int(other["id"]) != raid_id and await self.store.is_player_in_raid(int(other["id"]), ctx.author.id):
                    await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Başka Raid'desin", f"Önce **#{other['id']}** Raid'inden ayrıl."))
                    return
            pag = await self.store.get_player_ids(raid_id, "pag")
            if len(pag) >= TEAM_SIZE:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ PAG Takımı Dolu", "3/3 PAG slotu zaten dolu."))
                return
            await self.store.add_player(raid_id, guild.id, ctx.author.id, "pag")
            await self.store.audit(guild.id, ctx.author.id, "raid_joined", raid_id)
            await self.maybe_activate_raid(raid_id, guild)
            raid = await self.store.get_raid(raid_id, guild.id)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(raid)
            await self._prefix_send(ctx, embed=RaidEmbeds.success("✅ Raid'e Katıldın", f"**#{raid_id}** kadrosuna eklendin."))

    @commands.command(name="raidleave", aliases=["leaveraid"])
    @commands.guild_only()
    async def raidleave_prefix(self, ctx: commands.Context, raid_id: int) -> None:
        guild = ctx.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            player = await self.store.is_player_in_raid(raid_id, ctx.author.id)
            if not raid or not player or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Ayrılamadın", "Bu Raid'e kayıtlı değilsin veya Raid kapanmış."))
                return
            if int(raid["creator_id"]) == ctx.author.id and raid["status"] == STATUS_ACTIVE:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Host Ayrılamaz", "Aktif Raid hostu Raid'i bitirmeli veya yöneticiden destek almalı."))
                return
            await self.store.remove_player(raid_id, ctx.author.id)
            if raid["status"] == STATUS_ACTIVE:
                await self.store.update_status(raid_id, STATUS_RECRUITING)
            await self.store.audit(guild.id, ctx.author.id, "raid_left", raid_id)
            raid = await self.store.get_raid(raid_id, guild.id)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(raid)
            await self._prefix_send(ctx, embed=RaidEmbeds.success("👋 Raid'den Ayrıldın", f"**#{raid_id}** kadrosundan çıkarıldın."))

    @commands.command(name="raidinvite", aliases=["inviteRaid"])
    @commands.guild_only()
    async def raidinvite_prefix(self, ctx: commands.Context, raid_id: int, member: discord.Member) -> None:
        guild = ctx.guild
        raid = await self.store.get_raid(raid_id, guild.id)
        if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Kapalı", "Bu Raid'e davet gönderilemez."))
            return
        if not isinstance(ctx.author, discord.Member):
            return
        if ctx.author.id != int(raid["creator_id"]) and not await self.is_manager(ctx.author):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("🛡️ Yetki Gerekli", "Davet göndermek için Raid hostu veya Manager olmalısın."))
            return
        # Direct prefix invite is equivalent to the interactive invitation flow.
        if member.bot or member.id == ctx.author.id:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Geçersiz Oyuncu", "Bot veya kendin için Raid daveti gönderemezsin."))
            return
        if await self.store.is_player_in_raid(raid_id, member.id):
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("ℹ️ Zaten Kadroda", f"{member.mention} zaten Raid'de."))
            return
        pag = await self.store.get_player_ids(raid_id, "pag")
        if len(pag) >= TEAM_SIZE:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ PAG Dolu", "3/3 PAG slotu dolu."))
            return
        active = await self.store.get_active_raids(guild.id)
        for other in active:
            if int(other["id"]) != raid_id and await self.store.is_player_in_raid(int(other["id"]), member.id):
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Oyuncu Meşgul", f"{member.mention} başka bir aktif Raid'de."))
                return
        await self.store.add_invite(raid_id, guild.id, ctx.author.id, member.id, "pag")
        invite_row = await self.store.db.fetchone(
            "SELECT id FROM raid_invites WHERE raid_id = ? AND invitee_id = ? LIMIT 1",
            (raid_id, member.id),
        )
        if not invite_row:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Davet Hatası", "Raid daveti veritabanına kaydedilemedi."))
            return
        invite_id = int(invite_row["id"])
        await self.store.audit(guild.id, ctx.author.id, "player_invited", raid_id, details=str(member.id))
        try:
            dm = await member.send(
                embed=RaidEmbeds.info(
                    f"📨 PAG Raid Daveti • #{raid_id}",
                    f"**{short_text(raid['opponent_clan'], 80)}** Raid'ine davet edildin.\n\n**Invite ID:** `{invite_id}`\nButonları veya `!raidaccept {invite_id}` / `!raiddecline {invite_id}` komutlarını kullan.",
                ),
                view=InviteView(self, invite_id),
            )
        except discord.HTTPException:
            dm = None
        if dm is None:
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("⚠️ Davet Kaydedildi", f"{member.mention} için davet oluşturuldu ancak DM gönderilemedi. **Invite ID:** `{invite_id}`"))
        else:
            await self._prefix_send(ctx, embed=RaidEmbeds.success("📨 Davet Gönderildi", f"{member.mention} oyuncusuna **#{raid_id}** Raid daveti gönderildi."))

    async def _prefix_respond_invite(self, ctx: commands.Context, invite_id: int, accept: bool) -> None:
        invite = await self.store.get_invite(invite_id)
        if not invite:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Davet Bulunamadı", f"Invite **#{invite_id}** bulunamadı."))
            return
        if int(invite["invitee_id"]) != ctx.author.id:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("🛡️ Yetki", "Bu davet sana ait değil."))
            return
        if invite["status"] != "pending":
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("ℹ️ Davet Kullanılmış", f"Invite **#{invite_id}** zaten `{invite['status']}` durumda."))
            return
        guild = ctx.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(int(invite["raid_id"]), guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self.store.set_invite_status(invite_id, "expired")
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Kapalı", "Bu Raid artık aktif değil."))
                return
            if not accept:
                await self.store.set_invite_status(invite_id, "declined")
                await self.store.audit(guild.id, ctx.author.id, "invite_declined", int(invite["raid_id"]), details=str(invite_id))
                await self._prefix_send(ctx, embed=RaidEmbeds.warning("❌ Davet Reddedildi", f"Invite **#{invite_id}** reddedildi."))
                return
            if await self.store.is_player_in_raid(int(invite["raid_id"]), ctx.author.id):
                await self.store.set_invite_status(invite_id, "accepted")
                await self._prefix_send(ctx, embed=RaidEmbeds.warning("ℹ️ Zaten Kadroda", "Bu Raid'de zaten bulunuyorsun."))
                return
            for other in await self.store.get_active_raids(guild.id):
                if int(other["id"]) != int(invite["raid_id"]) and await self.store.is_player_in_raid(int(other["id"]), ctx.author.id):
                    await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Başka Raid'desin", f"Önce **#{other['id']}** Raid'inden ayrıl."))
                    return
            pag = await self.store.get_player_ids(int(invite["raid_id"]), "pag")
            if len(pag) >= TEAM_SIZE:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ PAG Dolu", "PAG tarafı 3/3 dolu."))
                return
            await self.store.add_player(int(invite["raid_id"]), guild.id, ctx.author.id, "pag")
            await self.store.set_invite_status(invite_id, "accepted")
            await self.store.audit(guild.id, ctx.author.id, "invite_accepted", int(invite["raid_id"]), details=str(invite_id))
            await self.maybe_activate_raid(int(invite["raid_id"]), guild)
            raid = await self.store.get_raid(int(invite["raid_id"]), guild.id)
            await self.refresh_raid_message(int(invite["raid_id"]), guild)
            await self.sync_raid_channel_permissions(raid)
        await self._prefix_send(ctx, embed=RaidEmbeds.success("✅ Davet Kabul Edildi", f"**#{invite['raid_id']}** Raid'ine katıldın."))

    @commands.command(name="raidaccept", aliases=["acceptraid", "raidacceptinvite"])
    @commands.guild_only()
    async def raidaccept_prefix(self, ctx: commands.Context, invite_id: int) -> None:
        await self._prefix_respond_invite(ctx, invite_id, True)

    @commands.command(name="raiddecline", aliases=["declineraid", "raiddeclineinvite"])
    @commands.guild_only()
    async def raiddecline_prefix(self, ctx: commands.Context, invite_id: int) -> None:
        await self._prefix_respond_invite(ctx, invite_id, False)

    @commands.command(name="raidaddopponents", aliases=["raidadv", "raidrival"])
    @commands.guild_only()
    async def raidaddopponents_prefix(self, ctx: commands.Context, raid_id: int, *members: discord.Member) -> None:
        if not await self._prefix_manager(ctx):
            return
        if not members or len(members) > TEAM_SIZE:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Geçersiz Kadro", "1–3 rakip oyuncu ekleyebilirsin."))
            return
        guild = ctx.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_RECRUITING, STATUS_ACTIVE}:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Kapalı", "Raid artık kadro düzenlemeye açık değil."))
                return
            current = await self.store.get_player_ids(raid_id, "opponent")
            added = 0
            skipped: list[str] = []
            for member in members:
                if member.bot or member.id in current or await self.store.is_player_in_raid(raid_id, member.id):
                    skipped.append(member.mention)
                    continue
                if len(current) + added >= TEAM_SIZE:
                    skipped.append(member.mention)
                    continue
                await self.store.add_player(raid_id, guild.id, member.id, "opponent")
                added += 1
            if not added:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Oyuncu Eklenemedi", "Eklenebilecek geçerli rakip oyuncu bulunamadı."))
                return
            await self.maybe_activate_raid(raid_id, guild)
            raid = await self.store.get_raid(raid_id, guild.id)
            await self.refresh_raid_message(raid_id, guild)
            await self.sync_raid_channel_permissions(raid)
            await self.store.audit(guild.id, ctx.author.id, "rival_players_added", raid_id, details=",".join(str(m.id) for m in members))
            desc = f"**{added}** rakip oyuncu eklendi."
            if skipped:
                desc += f"\nAtlanan: {', '.join(skipped)}"
            await self._prefix_send(ctx, embed=RaidEmbeds.success("⚔️ Rival Kadrosu Güncellendi", desc))

    @commands.command(name="raidfinish", aliases=["finishraid"])
    @commands.guild_only()
    async def raidfinish_prefix(self, ctx: commands.Context, raid_id: int, result_raw: str, *args: str) -> None:
        # Syntax: !raidfinish <id> <win|loss|draw> [@mvp] <proof-url>
        if not args:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Proof Zorunlu", "Kullanım: `!raidfinish <id> <win|loss|draw> [@mvp] <proof>`"))
            return
        proof_url = str(args[-1]).strip()
        mvp = None
        if len(args) > 1:
            mentioned = list(ctx.message.mentions)
            if mentioned:
                mvp = mentioned[0]
            else:
                maybe_ids = extract_user_ids(" ".join(args[:-1]))
                if maybe_ids:
                    mvp = guild_member = ctx.guild.get_member(maybe_ids[0])
        result = {
            "win": RESULT_PAG_WIN,
            "victory": RESULT_PAG_WIN,
            "pagwin": RESULT_PAG_WIN,
            "loss": RESULT_PAG_LOSS,
            "defeat": RESULT_PAG_LOSS,
            "pagloss": RESULT_PAG_LOSS,
            "draw": RESULT_DRAW,
        }.get(result_raw.casefold())
        if not result:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Sonuç Geçersiz", "`win`, `loss` veya `draw` kullan."))
            return
        if not re.match(r"^https?://\S+$", proof_url.strip()):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Proof Zorunlu", "Geçerli bir HTTP(S) proof linki vermelisin."))
            return
        guild = ctx.guild
        raid = await self.store.get_raid(raid_id, guild.id)
        if not raid:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Bulunamadı", "Raid bulunamadı."))
            return
        if ctx.author.id != int(raid["creator_id"]) and not await self.is_manager(ctx.author):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("🛡️ Yetki Gerekli", "Raid'i yalnızca host veya Raid Manager bitirebilir."))
            return
        if mvp and mvp.bot:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ MVP Geçersiz", "Bot MVP olamaz."))
            return
        # Directly perform the persistence flow to avoid fabricating a Discord Interaction.
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] not in {STATUS_ACTIVE, STATUS_RECRUITING}:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Bitirilemez", "Bu Raid kapanmış veya bulunamadı."))
                return
            pag = await self.store.get_player_ids(raid_id, "pag")
            opp = await self.store.get_player_ids(raid_id, "opponent")
            if not pag:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Oyuncu Yok", "Raid'de en az bir PAG oyuncusu olmalı."))
                return
            if mvp and mvp.id not in pag:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ MVP Geçersiz", "MVP PAG kadrosunda olmalı."))
                return
            if len(pag) < TEAM_SIZE or len(opp) < TEAM_SIZE:
                if not await self.is_manager(ctx.author):
                    await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ 3v3 Tamamlanmadı", "3v3 tamamlanmadan yalnızca Raid Manager/Staff Raid'i bitirebilir."))
                    return
            await self.store.finish_raid(raid_id, result, mvp.id if mvp else None, utc_now(), ctx.author.id, proof_url.strip())
            for user_id in pag:
                await self.store.apply_verified_stat(guild.id, user_id, result, user_id == (mvp.id if mvp else None))
            await self.store.audit(guild.id, ctx.author.id, "raid_verified_completed", raid_id, details=result)
            raid = await self.store.get_raid(raid_id, guild.id)
            await self.refresh_raid_message(raid_id, guild)
            await self.archive_or_delete_channel(raid)
        await self._prefix_send(ctx, embed=RaidEmbeds.success("🏁 Raid Tamamlandı", f"**#{raid_id}** → **{result_label(result)}**\nMVP: {mvp.mention if mvp else 'Seçilmedi'}\n🔗 Proof: {proof_url.strip()}"))

    @commands.command(name="raidcancel", aliases=["cancelraid"])
    @commands.guild_only()
    async def raidcancel_prefix(self, ctx: commands.Context, raid_id: int) -> None:
        if not await self._prefix_manager(ctx):
            return
        guild = ctx.guild
        async with self.guild_lock(guild.id):
            raid = await self.store.get_raid(raid_id, guild.id)
            if not raid or raid["status"] in {STATUS_COMPLETED, STATUS_CANCELLED}:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Kapalı", "Bu Raid zaten kapanmış."))
                return
            await self.store.cancel_raid(raid_id)
            await self.store.audit(guild.id, ctx.author.id, "raid_cancelled", raid_id)
            raid = await self.store.get_raid(raid_id, guild.id)
            await self.refresh_raid_message(raid_id, guild)
            await self.archive_or_delete_channel(raid)
        await self._prefix_send(ctx, embed=RaidEmbeds.success("🔴 Raid İptal Edildi", f"Raid **#{raid_id}** iptal edildi."))

    @commands.command(name="raidactive", aliases=["activeRaids"])
    @commands.guild_only()
    async def raidactive_prefix(self, ctx: commands.Context) -> None:
        rows = await self.store.get_active_raids(ctx.guild.id)
        if not rows:
            await self._prefix_send(ctx, embed=RaidEmbeds.info("⚔️ Active Raids", "Şu anda açık Raid yok."))
            return
        for row in rows[:10]:
            pag = await self.store.get_player_ids(int(row["id"]), "pag")
            opp = await self.store.get_player_ids(int(row["id"]), "opponent")
            await ctx.send(embed=RaidEmbeds.raid(row, pag, opp, ctx.guild), view=RaidActionView(self, int(row["id"])))

    @commands.command(name="raidmvp", aliases=["mvpranking", "raidmvprank"])
    @commands.guild_only()
    async def raidmvp_prefix(self, ctx: commands.Context) -> None:
        rows = await self.store.rankings(ctx.guild.id, "mvp")
        if not rows:
            await self._prefix_send(ctx, embed=RaidEmbeds.info("🏆 MVP RANKING", "Henüz doğrulanmış MVP istatistiği yok."))
            return
        lines = [f"**#{i}** {user_mention(int(row['user_id']))} — ★ `{int(row['mvp'])}` MVP" for i, row in enumerate(rows, 1)]
        await self._prefix_send(ctx, embed=RaidEmbeds.info("🏆 MVP RANKING", "\n".join(lines)))

    @commands.command(name="raidranking", aliases=["raidrank", "rankingraid"])
    @commands.guild_only()
    async def raidranking_prefix(self, ctx: commands.Context) -> None:
        rows = await self.store.rankings(ctx.guild.id, "wins")
        if not rows:
            await self._prefix_send(ctx, embed=RaidEmbeds.info("📊 RAID RANKING", "Henüz doğrulanmış Raid istatistiği yok."))
            return
        lines = [f"**#{i}** {user_mention(int(row['user_id']))} — `{int(row['wins'])} W • {int(row['losses'])} L` • `{int(row['raids'])} Raid`" for i, row in enumerate(rows, 1)]
        await self._prefix_send(ctx, embed=RaidEmbeds.info("📊 RAID RANKING", "\n".join(lines)))

    @commands.command(name="raidprofile", aliases=["raidstats", "mystatsraid"])
    @commands.guild_only()
    async def raidprofile_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        stats = await self.store.get_stats(ctx.guild.id, target.id)
        await self._prefix_send(ctx, embed=RaidEmbeds.profile(target.id, stats))

    @commands.command(name="raidhistory", aliases=["raidlog", "raidrecords"])
    @commands.guild_only()
    async def raidhistory_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        rows = await self.store.get_recent_raids(ctx.guild.id, target.id, 10)
        if not rows:
            await self._prefix_send(ctx, embed=RaidEmbeds.info("📜 RAID HISTORY", f"{target.mention} için Raid geçmişi yok."))
            return
        lines=[]
        for row in rows:
            date = parse_iso(row["ended_at"] or row["created_at"])
            stamp = f"<t:{int(date.timestamp())}:d>" if date else "—"
            lines.append(f"**#{row['id']}** • `{result_label(row['result']) if row['result'] else status_label(row['status'])}` • **{short_text(row['opponent_clan'], 40)}** • {stamp}")
        embed = RaidEmbeds.info("📜 RAID HISTORY", "\n".join(lines))
        embed.set_footer(text=f"Oyuncu: {target.display_name}")
        await self._prefix_send(ctx, embed=embed)

    @commands.command(name="raidreport", aliases=["reportraid"])
    @commands.guild_only()
    async def raidreport_prefix(self, ctx: commands.Context, *, raw: str = "") -> None:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) != 6:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("📝 RAID REPORT", "Kullanım:\n`!raidreport RIVAL | YYYY-MM-DD | @P1 @P2 @P3 | win | @MVP | https://proof`"))
            return
        opponent, raid_date, players_raw, result_raw, mvp_raw, proof_url = parts
        result = {
            "win": RESULT_PAG_WIN,
            "victory": RESULT_PAG_WIN,
            "pag win": RESULT_PAG_WIN,
            "loss": RESULT_PAG_LOSS,
            "defeat": RESULT_PAG_LOSS,
            "pag loss": RESULT_PAG_LOSS,
            "draw": RESULT_DRAW,
        }.get(result_raw.casefold())
        if not result:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Result", "Result `win`, `loss` veya `draw` olmalı."))
            return
        ids = extract_user_ids(players_raw)
        mvp_ids = extract_user_ids(mvp_raw)
        mvp_id = mvp_ids[0] if mvp_ids else None
        if not ids or len(ids) > TEAM_SIZE:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Players", "1–3 PAG oyuncusu girmelisin."))
            return
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", raid_date):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Tarih", "Tarih `YYYY-MM-DD` formatında olmalı."))
            return
        if not re.match(r"^https?://\S+$", proof_url):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("🔗 Proof Zorunlu", "Geçerli bir HTTP(S) Proof Linki vermelisin."))
            return
        if ctx.author.id not in ids:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Reporter", "Report gönderen kişi Players listesinde olmalı."))
            return
        if mvp_id and mvp_id not in ids:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ MVP", "MVP Players listesinde olmalı."))
            return
        for user_id in ids:
            member = ctx.guild.get_member(user_id)
            if not member or member.bot:
                await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Oyuncu", f"Oyuncu sunucuda bulunamadı: `{user_id}`"))
                return
        duplicate = await self.database.fetchone(
            "SELECT id FROM raid_reports WHERE guild_id = ? AND proof_url = ? AND status != 'rejected' LIMIT 1",
            (ctx.guild.id, proof_url),
        )
        live_duplicate = await self.database.fetchone(
            "SELECT id FROM raids WHERE guild_id = ? AND proof_url = ? AND status = 'completed' LIMIT 1",
            (ctx.guild.id, proof_url),
        )
        if duplicate or live_duplicate:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("♻️ Duplicate Proof", "Bu Proof Link daha önce kullanılmış."))
            return
        report_id = await self.store.create_report(ctx.guild.id, ctx.author.id, clean_text(opponent, 80), ids, result, mvp_id, raid_date, proof_url)
        await self.store.audit(ctx.guild.id, ctx.author.id, "report_created", report_id=report_id, details=proof_url)
        await self.notify_pending_report(ctx.guild, report_id)
        await self._prefix_send(ctx, embed=RaidEmbeds.success("📝 Report PENDING", f"Report **#{report_id}** alındı. Staff/Raid Manager doğrulamasını bekliyor.\n\n🔗 {proof_url}"))

    @commands.command(name="raidreview", aliases=["reviewraid"])
    @commands.guild_only()
    async def raidreview_prefix(self, ctx: commands.Context, report_id: int | None = None, action: str | None = None, *, note: str = "") -> None:
        if not await self._prefix_manager(ctx):
            return
        if report_id is None:
            rows = await self.store.get_pending_reports(ctx.guild.id, 10)
            if not rows:
                await self._prefix_send(ctx, embed=RaidEmbeds.info("🛡️ RAID REVIEW", "Bekleyen report yok."))
                return
            lines = [f"**#{row['id']}** • {user_mention(int(row['reporter_id']))} • **{short_text(row['opponent_clan'], 50)}** • `{result_label(row['result'])}`\n🔗 {row['proof_url']}" for row in rows]
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("🛡️ RAID REVIEW QUEUE", "\n\n".join(lines)))
            return
        if action not in {"verify", "verified", "approve", "reject", "rejected"}:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Review Action", "Kullanım: `!raidreview <report_id> <verify|reject> [not]`"))
            return
        report = await self.store.get_report(report_id, ctx.guild.id)
        if not report:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Report Bulunamadı", f"Report **#{report_id}** bulunamadı."))
            return
        if report["status"] != REPORT_PENDING:
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("ℹ️ Zaten İncelendi", f"Report şu anda `{report['status']}` durumunda."))
            return
        approve = action in {"verify", "verified", "approve"}
        if not approve:
            await self.store.review_report(report_id, REPORT_REJECTED, ctx.author.id, note or "Staff tarafından reddedildi.")
            await self.store.audit(ctx.guild.id, ctx.author.id, "report_rejected", report_id=report_id, details=note)
            await self._prefix_send(ctx, embed=RaidEmbeds.warning("❌ Report REJECTED", f"Report **#{report_id}** reddedildi."))
            return
        try:
            players = [int(value) for value in json.loads(report["players_json"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Bozuk Report", "Players verisi geçersiz olduğu için güvenlik amacıyla onaylanmadı."))
            return
        if not players or len(players) > TEAM_SIZE:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Players", "Report oyuncu listesi geçersiz."))
            return
        if report["mvp_id"] and int(report["mvp_id"]) not in players:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ MVP", "Report MVP verisi oyuncu listesinde değil."))
            return
        async with self.guild_lock(ctx.guild.id):
            # Re-read under lock to prevent two staff members from applying the same stats.
            fresh = await self.store.get_report(report_id, ctx.guild.id)
            if not fresh or fresh["status"] != REPORT_PENDING:
                await self._prefix_send(ctx, embed=RaidEmbeds.warning("⚠️ Yarış Durumu", "Bu report başka bir yetkili tarafından zaten işlendi."))
                return
            await self.store.review_report(report_id, REPORT_VERIFIED, ctx.author.id, note or "Verified")
            for user_id in players:
                await self.store.apply_verified_stat(ctx.guild.id, user_id, fresh["result"], int(fresh["mvp_id"] or 0) == user_id)
            await self.store.audit(ctx.guild.id, ctx.author.id, "report_verified", report_id=report_id, details=note)
        await self._prefix_send(ctx, embed=RaidEmbeds.success("✅ Report VERIFIED", f"Report **#{report_id}** doğrulandı ve **{len(players)}** oyuncunun istatistiğine işlendi."))

    @commands.command(name="raidinfo", aliases=["raidstatus", "raidshow"])
    @commands.guild_only()
    async def raidinfo_prefix(self, ctx: commands.Context, raid_id: int) -> None:
        raid = await self.store.get_raid(raid_id, ctx.guild.id)
        if not raid:
            await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ Raid Bulunamadı", f"`#{raid_id}` bulunamadı."))
            return
        pag = await self.store.get_player_ids(raid_id, "pag")
        opp = await self.store.get_player_ids(raid_id, "opponent")
        await self._prefix_send(ctx, embed=RaidEmbeds.raid(raid, pag, opp, ctx.guild), delete_after=None)

    # ========================================================
    # Prefix command error handling
    # ========================================================

    @raidhelp_prefix.error
    @raidpanel_prefix.error
    @raidsetup_prefix.error
    @raidcreate_prefix.error
    @raidjoin_prefix.error
    @raidleave_prefix.error
    @raidinvite_prefix.error
    @raidaccept_prefix.error
    @raiddecline_prefix.error
    @raidaddopponents_prefix.error
    @raidfinish_prefix.error
    @raidcancel_prefix.error
    @raidactive_prefix.error
    @raidmvp_prefix.error
    @raidranking_prefix.error
    @raidprofile_prefix.error
    @raidhistory_prefix.error
    @raidreport_prefix.error
    @raidreview_prefix.error
    @raidinfo_prefix.error
    async def raid_prefix_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, commands.MissingRequiredArgument):
            message = f"Eksik parametre: `{original.param.name}`. `!raidhelp` ile kullanım örneklerini görebilirsin."
        elif isinstance(original, commands.BadArgument):
            message = "Parametre geçersiz. Mention/ID/komut formatını kontrol et. `!raidhelp` yaz."
        elif isinstance(original, commands.MissingPermissions):
            message = "Bu komut için gerekli Discord yetkisine sahip değilsin."
        elif isinstance(original, commands.CheckFailure):
            message = "Bu komut bu kanalda veya bu kullanıcı için kullanılamıyor."
        else:
            self.logger.exception("Raid prefix command error", exc_info=original)
            message = "RAID sistemi beklenmeyen bir hata verdi. Hata loglandı."
        await self._prefix_send(ctx, embed=RaidEmbeds.error("❌ RAID COMMAND ERROR", message))
class RaidReportReviewButton(discord.ui.Button):
    def __init__(self, cog: Raid, report_id: int, approve: bool) -> None:
        self.cog = cog
        self.report_id = report_id
        self.approve = approve
        super().__init__(
            label="VERIFY" if approve else "REJECT",
            style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
            custom_id=f"pagraid:report:{report_id}:{'verify' if approve else 'reject'}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.require_manager(interaction):
            return
        await interaction.response.send_modal(
            RaidReviewNoteModal(self.cog, self.report_id, interaction.user.id, self.approve)
        )


class RaidReportReviewView(discord.ui.View):
    def __init__(self, cog: Raid, report_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(RaidReportReviewButton(cog, report_id, True))
        self.add_item(RaidReportReviewButton(cog, report_id, False))


class RaidReviewListView(discord.ui.View):
    def __init__(self, cog: Raid, report_ids: list[int]) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        for report_id in report_ids[:5]:
            self.add_item(RaidReportSelectButton(cog, report_id))


class RaidReportSelectButton(discord.ui.Button):
    def __init__(self, cog: Raid, report_id: int) -> None:
        super().__init__(
            label=f"REPORT #{report_id}",
            style=discord.ButtonStyle.primary,
            custom_id=f"pagraid:review:{report_id}",
        )
        self.cog = cog
        self.report_id = report_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.require_manager(interaction):
            return
        report = await self.cog.store.get_report(self.report_id, interaction.guild.id)
        if not report:
            await self.cog.safe_interaction_error(interaction, "Report bulunamadı.")
            return
        await interaction.response.send_message(
            embed=RaidEmbeds.warning(
                f"🛡️ REPORT #{self.report_id}",
                f"Reporter: {user_mention(int(report['reporter_id']))}\nOpponent: **{short_text(report['opponent_clan'], 80)}**\nResult: **{result_label(report['result'])}**\nPlayers: `{report['players_json']}`\n🔗 {report['proof_url']}",
            ),
            view=RaidReportReviewView(self.cog, self.report_id),
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Raid(bot))
