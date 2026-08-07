from __future__ import annotations

import asyncio
import logging
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import discord
import httpx
from discord.ext import commands

from utils.embeds import PAGEmbeds


STAGE_MIN = 0
STAGE_MAX = 4

STAGE_ROLE_NAMES = {i: f"Stage {i}" for i in range(STAGE_MIN, STAGE_MAX + 1)}
FAILED_ROLE_NAME = "Failed Tryout"
HOSTER_ROLE_NAME = "Tryout Hoster"
ANNOUNCE_CHANNEL_NAME = "tryout-announcements"
RESULT_CHANNEL_NAME = "tryout-results"

RATING_ORDER = {"low": 0, "mid": 1, "high": 2}
MODIFIER_ORDER = {"weak": 0, "stable": 1, "strong": 2}

ROLE_FIELD_KEYS = {
    "hoster": "hoster_role_id",
    **{f"stage_{i}": f"stage_{i}_role_id" for i in range(STAGE_MIN, STAGE_MAX + 1)},
    "failed": "failed_role_id",
}

CHANNEL_FIELD_KEYS = {
    "announce": "announce_channel_id",
    "results": "results_channel_id",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_text(value: str, limit: int = 1024) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def split_pipe(text: str, expected: int, defaults: tuple[str, ...]) -> list[str]:
    parts = [part.strip() for part in (text or "").split("|")]
    while len(parts) < expected:
        parts.append("")
    result: list[str] = []
    for idx in range(expected):
        value = parts[idx] if idx < len(parts) else ""
        if not value:
            value = defaults[idx] if idx < len(defaults) else ""
        result.append(value)
    return result


def parse_place_id(link: str) -> int | None:
    patterns = (
        r"placeId=(\d+)",
        r"roblox\.com/games/(\d+)",
        r"roblox\.com/games/\d+/[\w-]+",
        r"/games/(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, link, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def parse_hoster_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "Bilinmiyor"
    return clamp_text(raw, 128)


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def stage_color(stage: int) -> discord.Colour:
    palette = {
        0: discord.Colour.dark_grey(),
        1: discord.Colour.blue(),
        2: discord.Colour.teal(),
        3: discord.Colour.orange(),
        4: discord.Colour.green(),
    }
    return palette.get(stage, discord.Colour.blurple())


@dataclass(slots=True)
class ParsedTryoutResult:
    member: discord.Member
    stage: int
    rating: str
    modifier: str | None
    reason: str
    improvement: str
    failed: bool = False


class TryoutAttendanceView(discord.ui.View):
    def __init__(self, cog: "TryoutSystemCog", session_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.session_id = session_id

        attend = discord.ui.Button(
            label="Katıldım",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"pag_tryout_attend:{session_id}",
        )
        attend.callback = self._attend  # type: ignore[assignment]

        absent = discord.ui.Button(
            label="Katılmadım",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"pag_tryout_absent:{session_id}",
        )
        absent.callback = self._absent  # type: ignore[assignment]

        maybe = discord.ui.Button(
            label="Tespit Et",
            style=discord.ButtonStyle.secondary,
            emoji="🔎",
            custom_id=f"pag_tryout_detect:{session_id}",
        )
        maybe.callback = self._detect  # type: ignore[assignment]

        self.add_item(attend)
        self.add_item(absent)
        self.add_item(maybe)

    async def _attend(self, interaction: discord.Interaction) -> None:
        await self.cog.set_attendance(interaction, self.session_id, "attended", source="manual")

    async def _absent(self, interaction: discord.Interaction) -> None:
        await self.cog.set_attendance(interaction, self.session_id, "absent", source="manual")

    async def _detect(self, interaction: discord.Interaction) -> None:
        await self.cog.trigger_presence_scan(interaction, self.session_id)


class TryoutSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.roblox_service = bot.roblox_service
        self.discord_service = bot.discord_service
        self.logger = bot.logger
        self._schema_ready = False
        self._restoring_views = False

    async def cog_load(self) -> None:
        await self.ensure_schema()
        await self.restore_active_views()

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS tryout_settings (
                guild_id INTEGER PRIMARY KEY,
                hoster_role_id INTEGER,
                stage_0_role_id INTEGER,
                stage_1_role_id INTEGER,
                stage_2_role_id INTEGER,
                stage_3_role_id INTEGER,
                stage_4_role_id INTEGER,
                failed_role_id INTEGER,
                announce_channel_id INTEGER,
                results_channel_id INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS tryout_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                host_id INTEGER NOT NULL,
                link TEXT NOT NULL,
                place_id INTEGER,
                hoster_text TEXT,
                note_text TEXT,
                announcement_channel_id INTEGER,
                announcement_message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS tryout_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                roblox_id INTEGER,
                roblox_username TEXT,
                status TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, discord_id)
            )
            """
        )
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS tryout_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                session_id INTEGER,
                discord_id INTEGER NOT NULL,
                roblox_id INTEGER,
                roblox_username TEXT,
                stage INTEGER NOT NULL,
                rating TEXT NOT NULL,
                modifier TEXT,
                reason TEXT,
                improvement TEXT,
                host_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tryout_sessions_guild_status
            ON tryout_sessions(guild_id, status)
            """
        )
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tryout_results_guild_discord
            ON tryout_results(guild_id, discord_id)
            """
        )
        self._schema_ready = True

    async def restore_active_views(self) -> None:
        if self._restoring_views:
            return
        self._restoring_views = True
        try:
            rows = await self.database.fetchall(
                """
                SELECT id
                FROM tryout_sessions
                WHERE status = 'open' AND announcement_message_id IS NOT NULL
                """
            )
            for row in rows:
                try:
                    self.bot.add_view(TryoutAttendanceView(self, int(row["id"])), message_id=int(row["announcement_message_id"]))
                except Exception:
                    self.logger.exception("Failed to restore tryout view for session %s.", row["id"])
        finally:
            self._restoring_views = False

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        row = await self.database.fetchone(
            """
            SELECT *
            FROM tryout_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        if row is None:
            return {
                "guild_id": guild_id,
                "hoster_role_id": None,
                "stage_0_role_id": None,
                "stage_1_role_id": None,
                "stage_2_role_id": None,
                "stage_3_role_id": None,
                "stage_4_role_id": None,
                "failed_role_id": None,
                "announce_channel_id": None,
                "results_channel_id": None,
            }
        return dict(row)

    async def save_settings(self, guild_id: int, **values: Any) -> None:
        current = await self.get_settings(guild_id)
        current.update(values)
        await self.database.execute(
            """
            INSERT INTO tryout_settings (
                guild_id,
                hoster_role_id,
                stage_0_role_id,
                stage_1_role_id,
                stage_2_role_id,
                stage_3_role_id,
                stage_4_role_id,
                failed_role_id,
                announce_channel_id,
                results_channel_id,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                hoster_role_id = excluded.hoster_role_id,
                stage_0_role_id = excluded.stage_0_role_id,
                stage_1_role_id = excluded.stage_1_role_id,
                stage_2_role_id = excluded.stage_2_role_id,
                stage_3_role_id = excluded.stage_3_role_id,
                stage_4_role_id = excluded.stage_4_role_id,
                failed_role_id = excluded.failed_role_id,
                announce_channel_id = excluded.announce_channel_id,
                results_channel_id = excluded.results_channel_id,
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                current.get("hoster_role_id"),
                current.get("stage_0_role_id"),
                current.get("stage_1_role_id"),
                current.get("stage_2_role_id"),
                current.get("stage_3_role_id"),
                current.get("stage_4_role_id"),
                current.get("failed_role_id"),
                current.get("announce_channel_id"),
                current.get("results_channel_id"),
                utc_now(),
            ),
        )

    async def create_or_get_role(self, guild: discord.Guild, name: str, *, color: discord.Colour | None = None) -> discord.Role:
        found = discord.utils.get(guild.roles, name=name)
        if found is not None:
            return found
        return await guild.create_role(
            name=name,
            colour=color or discord.Colour.default(),
            hoist=False,
            mentionable=False,
            reason="PAG tryout system setup",
        )

    async def create_or_get_channel(self, guild: discord.Guild, name: str, *, topic: str) -> discord.TextChannel:
        existing = discord.utils.get(guild.text_channels, name=name)
        if existing is not None:
            return existing
        return await guild.create_text_channel(
            name=name,
            topic=topic,
            reason="PAG tryout system setup",
        )

    async def has_tryout_manage_access(self, guild: discord.Guild, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_roles:
            return True
        settings = await self.get_settings(guild.id)
        hoster_role_id = settings.get("hoster_role_id")
        if hoster_role_id:
            role = guild.get_role(int(hoster_role_id))
            if role and role in member.roles:
                return True
        role = discord.utils.get(guild.roles, name=HOSTER_ROLE_NAME)
        return bool(role and role in member.roles)

    def _status_color(self, rating: str, stage: int, modifier: str | None) -> discord.Colour:
        base = stage_color(stage)
        if rating.lower() == "high":
            return discord.Colour.green()
        if rating.lower() == "mid":
            return discord.Colour.orange()
        if rating.lower() == "low":
            return discord.Colour.red()
        if modifier == "stable":
            return discord.Colour.teal()
        return base

    def _role_for_stage(self, guild: discord.Guild, settings: dict[str, Any], stage: int) -> discord.Role | None:
        key = ROLE_FIELD_KEYS.get(f"stage_{stage}")
        role_id = settings.get(key) if key else None
        if role_id:
            role = guild.get_role(int(role_id))
            if role is not None:
                return role
        return discord.utils.get(guild.roles, name=STAGE_ROLE_NAMES.get(stage, f"Stage {stage}"))

    def _failed_role(self, guild: discord.Guild, settings: dict[str, Any]) -> discord.Role | None:
        role_id = settings.get("failed_role_id")
        if role_id:
            role = guild.get_role(int(role_id))
            if role is not None:
                return role
        return discord.utils.get(guild.roles, name=FAILED_ROLE_NAME)

    def _hoster_role(self, guild: discord.Guild, settings: dict[str, Any]) -> discord.Role | None:
        role_id = settings.get("hoster_role_id")
        if role_id:
            role = guild.get_role(int(role_id))
            if role is not None:
                return role
        return discord.utils.get(guild.roles, name=HOSTER_ROLE_NAME)

    async def _get_verified_profile(self, guild: discord.Guild, discord_id: int) -> dict[str, Any] | None:
        row = await self.database.fetchone(
            """
            SELECT discord_id, roblox_id, roblox_username, verified_at
            FROM verifications
            WHERE discord_id = ?
            LIMIT 1
            """,
            (discord_id,),
        )
        return dict(row) if row else None

    async def _resolve_roblox_user(self, guild: discord.Guild, member: discord.Member) -> dict[str, Any]:
        profile = await self._get_verified_profile(guild, member.id)
        result: dict[str, Any] = {
            "roblox_id": None,
            "roblox_username": None,
            "roblox_display_name": None,
            "avatar_url": None,
        }
        if not profile:
            return result

        roblox_id = profile.get("roblox_id")
        username = profile.get("roblox_username")
        result["roblox_id"] = int(roblox_id) if roblox_id is not None else None
        result["roblox_username"] = str(username) if username else None

        if roblox_id is None:
            return result

        try:
            roblox_user = await self.roblox_service.get_user(int(roblox_id))
            result["roblox_username"] = getattr(roblox_user, "name", result["roblox_username"])
            result["roblox_display_name"] = getattr(roblox_user, "display_name", result["roblox_username"])
        except Exception:
            self.logger.exception("Failed to resolve Roblox profile for %s.", member.id)

        try:
            avatar = await self.roblox_service.get_avatar(int(roblox_id))
            result["avatar_url"] = getattr(avatar, "image_url", None)
        except Exception:
            self.logger.exception("Failed to resolve Roblox avatar for %s.", member.id)

        return result

    def _detect_stage_and_rating(self, tokens: list[str]) -> tuple[int, str, str | None, list[str]]:
        stage: int | None = None
        rating: str | None = None
        modifier: str | None = None
        leftovers: list[str] = []

        for token in tokens:
            cleaned = token.strip().casefold()
            stage_match = re.fullmatch(r"(?:s|stage)?\s*(\d)", cleaned)
            if stage_match and stage is None:
                stage = int(stage_match.group(1))
                continue
            if cleaned in RATING_ORDER and rating is None:
                rating = cleaned
                continue
            if cleaned in MODIFIER_ORDER and modifier is None:
                modifier = cleaned
                continue
            leftovers.append(token)

        if stage is None:
            raise ValueError("Stage bulunamadı. Örnek: s3, stage2, 4")
        if stage < STAGE_MIN or stage > STAGE_MAX:
            raise ValueError(f"Stage yalnızca {STAGE_MIN}-{STAGE_MAX} arası olabilir.")
        if rating is None:
            rating = "mid"
        return stage, rating, modifier, leftovers

    async def parse_result_args(self, ctx: commands.Context, args: str) -> ParsedTryoutResult:
        segments = split_pipe(args, 3, ("", "", ""))
        head = segments[0].strip()
        if not head:
            raise ValueError("Kullanıcı ve stage gerekli.")

        tokens = shlex.split(head)
        if len(tokens) < 2:
            raise ValueError("Kullanıcı ve stage gerekli.")

        member_token = tokens[0]
        member = await commands.MemberConverter().convert(ctx, member_token)
        stage, rating, modifier, leftovers = self._detect_stage_and_rating(tokens[1:])

        inline_note = " ".join(leftovers).strip()
        reason = segments[1].strip() or inline_note
        improvement = segments[2].strip()

        if not reason:
            reason = "Değerlendirme notu verilmedi."
        if not improvement:
            if stage < STAGE_MAX:
                improvement = f"Bir sonraki hedef için Stage {stage + 1} tarafına hazırlanmalı."
            else:
                improvement = "Stage 4 seviyesini stabilize etmeli ve baskı altında tutarlılığı korumalı."

        return ParsedTryoutResult(
            member=member,
            stage=stage,
            rating=rating,
            modifier=modifier,
            reason=clamp_text(reason, 900),
            improvement=clamp_text(improvement, 900),
        )

    async def apply_roles(self, guild: discord.Guild, member: discord.Member, stage: int, *, failed: bool = False) -> list[str]:
        settings = await self.get_settings(guild.id)
        removed: list[str] = []
        for i in range(STAGE_MIN, STAGE_MAX + 1):
            role = self._role_for_stage(guild, settings, i)
            if role and role in member.roles:
                try:
                    await self.discord_service.remove_role(member, role, reason="PAG tryout result update")
                    removed.append(role.name)
                except Exception:
                    self.logger.exception("Failed to remove stage role %s from %s.", role.name, member.id)
        failed_role = self._failed_role(guild, settings)
        if failed_role and failed_role in member.roles:
            try:
                await self.discord_service.remove_role(member, failed_role, reason="PAG tryout result update")
                removed.append(failed_role.name)
            except Exception:
                self.logger.exception("Failed to remove failed role from %s.", member.id)

        if failed:
            if failed_role is not None:
                await self.discord_service.add_role(member, failed_role, reason="PAG tryout result")
            return removed

        role = self._role_for_stage(guild, settings, stage)
        if role is not None:
            await self.discord_service.add_role(member, role, reason="PAG tryout result")
        return removed

    async def set_attendance(self, interaction: discord.Interaction, session_id: int, status: str, *, source: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Bu işlem yalnızca sunucuda kullanılabilir.", ephemeral=True)

        session = await self.get_session(session_id)
        if not session or int(session["guild_id"]) != interaction.guild.id:
            return await interaction.response.send_message("Bu tryout oturumu bulunamadı.", ephemeral=True)
        if session["status"] != "open":
            return await interaction.response.send_message("Bu oturum kapalı.", ephemeral=True)

        profile = await self._get_verified_profile(interaction.guild, interaction.user.id)
        roblox_id = int(profile["roblox_id"]) if profile and profile.get("roblox_id") is not None else None
        roblox_username = profile.get("roblox_username") if profile else None

        await self.database.execute(
            """
            INSERT INTO tryout_attendance (
                session_id,
                guild_id,
                discord_id,
                roblox_id,
                roblox_username,
                status,
                source,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, discord_id) DO UPDATE SET
                roblox_id = excluded.roblox_id,
                roblox_username = excluded.roblox_username,
                status = excluded.status,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                interaction.guild.id,
                interaction.user.id,
                roblox_id,
                roblox_username,
                status,
                source,
                utc_now(),
            ),
        )

        await self.refresh_session_message(interaction.guild, session_id)
        label = "Katıldım" if status == "attended" else "Katılmadım"
        await interaction.response.send_message(f"{label} olarak kaydedildi.", ephemeral=True)

    async def trigger_presence_scan(self, interaction: discord.Interaction, session_id: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Bu işlem yalnızca sunucuda kullanılabilir.", ephemeral=True)

        session = await self.get_session(session_id)
        if not session or int(session["guild_id"]) != interaction.guild.id:
            return await interaction.response.send_message("Bu tryout oturumu bulunamadı.", ephemeral=True)
        if session["status"] != "open":
            return await interaction.response.send_message("Bu oturum kapalı.", ephemeral=True)

        if int(session["host_id"]) != interaction.user.id and not await self.has_tryout_manage_access(interaction.guild, interaction.user):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)

        detected = await self.best_effort_presence_scan(interaction.guild, session)
        await self.refresh_session_message(interaction.guild, session_id)

        if not detected:
            return await interaction.response.send_message("Katılım otomatik tespit edilemedi, yine de denendi.", ephemeral=True)

        await interaction.response.send_message(f"Otomatik tespit tamamlandı: {detected} kişi işaretlendi.", ephemeral=True)

    async def best_effort_presence_scan(self, guild: discord.Guild, session: dict[str, Any]) -> int:
        place_id = session.get("place_id")
        if not place_id:
            return 0

        verified = await self.database.fetchall(
            """
            SELECT discord_id, roblox_id, roblox_username
            FROM verifications
            WHERE roblox_id IS NOT NULL
            """
        )
        user_ids = [int(row["roblox_id"]) for row in verified if row["roblox_id"] is not None]
        if not user_ids:
            return 0

        guessed: set[int] = set()
        async with httpx.AsyncClient(timeout=20) as client:
            for start in range(0, len(user_ids), 100):
                chunk = user_ids[start : start + 100]
                try:
                    response = await client.post(
                        "https://presence.roblox.com/v1/presence/users",
                        json={"userIds": chunk},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    self.logger.exception("Roblox presence scan failed for session %s.", session["id"])
                    continue

                for entry in payload.get("userPresences", []):
                    if int(entry.get("placeId") or 0) != int(place_id):
                        continue
                    roblox_id = int(entry.get("userId") or 0)
                    if not roblox_id:
                        continue
                    guessed.add(roblox_id)

        if not guessed:
            return 0

        mapping = {int(row["roblox_id"]): int(row["discord_id"]) for row in verified if row["roblox_id"] is not None}
        for roblox_id in guessed:
            discord_id = mapping.get(roblox_id)
            if discord_id is None:
                continue
            row = next((r for r in verified if int(r["roblox_id"]) == roblox_id), None)
            if row is None:
                continue
            await self.database.execute(
                """
                INSERT INTO tryout_attendance (
                    session_id,
                    guild_id,
                    discord_id,
                    roblox_id,
                    roblox_username,
                    status,
                    source,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 'attended', 'api', ?)
                ON CONFLICT(session_id, discord_id) DO UPDATE SET
                    roblox_id = excluded.roblox_id,
                    roblox_username = excluded.roblox_username,
                    status = excluded.status,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    int(session["id"]),
                    guild.id,
                    discord_id,
                    roblox_id,
                    row["roblox_username"],
                    utc_now(),
                ),
            )

        return len(guessed)

    async def get_session(self, session_id: int) -> dict[str, Any] | None:
        row = await self.database.fetchone(
            """
            SELECT *
            FROM tryout_sessions
            WHERE id = ?
            LIMIT 1
            """,
            (session_id,),
        )
        return dict(row) if row else None

    async def list_open_sessions(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.database.fetchall(
            """
            SELECT *
            FROM tryout_sessions
            WHERE guild_id = ? AND status = 'open'
            ORDER BY id DESC
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def get_attendance_counts(self, session_id: int) -> tuple[int, int, int]:
        yes_row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM tryout_attendance
            WHERE session_id = ? AND status = 'attended'
            """,
            (session_id,),
        )
        no_row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM tryout_attendance
            WHERE session_id = ? AND status = 'absent'
            """,
            (session_id,),
        )
        api_row = await self.database.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM tryout_attendance
            WHERE session_id = ? AND source = 'api'
            """,
            (session_id,),
        )
        return int(yes_row["count"] or 0), int(no_row["count"] or 0), int(api_row["count"] or 0)

    async def refresh_session_message(self, guild: discord.Guild, session_id: int) -> None:
        session = await self.get_session(session_id)
        if not session:
            return
        channel_id = session.get("announcement_channel_id")
        message_id = session.get("announcement_message_id")
        if not channel_id or not message_id:
            return

        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        yes_count, no_count, api_count = await self.get_attendance_counts(session_id)
        embed = self.build_announcement_embed(session, yes_count, no_count, api_count)
        try:
            await message.edit(embed=embed, view=TryoutAttendanceView(self, session_id))
        except discord.HTTPException:
            self.logger.exception("Failed to refresh tryout announcement %s.", session_id)

    def build_announcement_embed(self, session: dict[str, Any], yes_count: int, no_count: int, api_count: int) -> discord.Embed:
        place_id = session.get("place_id")
        hoster_text = session.get("hoster_text") or "Bilinmiyor"
        note_text = session.get("note_text") or "Yok"
        link = session.get("link") or "Yok"
        stage_text = "Stage 0 → Stage 4"
        embed = PAGEmbeds.custom(
            title=f"🎯 Tryout Duyurusu #{session['id']}",
            description=(
                f"Tryout başladı. Katılımı butonlardan işaretleyebilirsin.\n\n"
                f"**Hoster:** {hoster_text}\n"
                f"**Link:** {link}\n"
                f"**Not:** {clamp_text(note_text, 800)}"
            ),
            color=discord.Colour.purple(),
        )
        embed.add_field(name="Stage Aralığı", value=stage_text, inline=True)
        embed.add_field(name="Katılım", value=f"✅ {yes_count} / ❌ {no_count}", inline=True)
        embed.add_field(name="API Tespiti", value=str(api_count), inline=True)
        if place_id:
            embed.add_field(name="Place ID", value=str(place_id), inline=True)
        embed.set_footer(text=f"Oturum #{session['id']} • {session['status']}")
        return embed

    def build_result_embed(self, result: ParsedTryoutResult, host: discord.Member, profile: dict[str, Any]) -> discord.Embed:
        roblox_username = profile.get("roblox_username") or result.member.display_name
        roblox_display = profile.get("roblox_display_name") or roblox_username
        avatar_url = profile.get("avatar_url")
        modifier_text = result.modifier.title() if result.modifier else "Yok"
        embed = PAGEmbeds.custom(
            title="🏁 Tryout Sonucu",
            description=(
                f"**{result.member.mention}** için sonuç kaydedildi.\n"
                f"Stage {result.stage} • {result.rating.title()}" + (f" • {modifier_text}" if result.modifier else "")
            ),
            color=self._status_color(result.rating, result.stage, result.modifier),
            thumbnail_url=avatar_url,
        )
        embed.add_field(name="Discord", value=result.member.mention, inline=True)
        embed.add_field(name="Roblox", value=clamp_text(str(roblox_username), 128), inline=True)
        embed.add_field(name="Display", value=clamp_text(str(roblox_display), 128), inline=True)
        embed.add_field(name="Stage", value=f"Stage {result.stage}", inline=True)
        embed.add_field(name="Rating", value=result.rating.title(), inline=True)
        embed.add_field(name="Modifier", value=modifier_text, inline=True)
        embed.add_field(name="Neden", value=clamp_text(result.reason, 1024), inline=False)
        embed.add_field(name="Bir Üst İçin", value=clamp_text(result.improvement, 1024), inline=False)
        embed.add_field(name="Host", value=host.mention, inline=True)
        embed.set_footer(text=f"{roblox_username} • {utc_now()}")
        return embed

    async def create_tryout_session(
        self,
        guild: discord.Guild,
        host: discord.Member,
        link: str,
        hoster_text: str,
        note_text: str,
        channel: discord.TextChannel,
        place_id: int | None,
    ) -> int:
        await self.database.execute(
            """
            INSERT INTO tryout_sessions (
                guild_id,
                host_id,
                link,
                place_id,
                hoster_text,
                note_text,
                announcement_channel_id,
                status,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                guild.id,
                host.id,
                link,
                place_id,
                hoster_text,
                note_text,
                channel.id,
                utc_now(),
            ),
        )
        row = await self.database.fetchone(
            "SELECT last_insert_rowid() AS id"
        )
        return int(row["id"])

    async def set_session_message(self, session_id: int, channel_id: int, message_id: int) -> None:
        await self.database.execute(
            """
            UPDATE tryout_sessions
            SET announcement_channel_id = ?, announcement_message_id = ?
            WHERE id = ?
            """,
            (channel_id, message_id, session_id),
        )

    async def close_session(self, session_id: int) -> None:
        await self.database.execute(
            """
            UPDATE tryout_sessions
            SET status = 'closed', closed_at = ?
            WHERE id = ?
            """,
            (utc_now(), session_id),
        )

    async def store_result(
        self,
        guild: discord.Guild,
        host: discord.Member,
        result: ParsedTryoutResult,
        session_id: int | None,
        profile: dict[str, Any],
    ) -> int:
        await self.database.execute(
            """
            INSERT INTO tryout_results (
                guild_id,
                session_id,
                discord_id,
                roblox_id,
                roblox_username,
                stage,
                rating,
                modifier,
                reason,
                improvement,
                host_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild.id,
                session_id,
                result.member.id,
                profile.get("roblox_id"),
                profile.get("roblox_username"),
                result.stage,
                result.rating,
                result.modifier,
                result.reason,
                result.improvement,
                host.id,
                utc_now(),
            ),
        )
        row = await self.database.fetchone("SELECT last_insert_rowid() AS id")
        return int(row["id"])

    async def setup_command(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self.has_tryout_manage_access(ctx.guild, ctx.author):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        await self.ensure_schema()
        settings = await self.get_settings(ctx.guild.id)

        created_roles: list[str] = []
        role_ids: dict[str, int | None] = {}

        try:
            hoster_role = await self.create_or_get_role(ctx.guild, HOSTER_ROLE_NAME, color=discord.Colour.blurple())
            role_ids["hoster_role_id"] = hoster_role.id
            created_roles.append(hoster_role.name)

            for stage in range(STAGE_MIN, STAGE_MAX + 1):
                role = await self.create_or_get_role(ctx.guild, STAGE_ROLE_NAMES[stage], color=stage_color(stage))
                role_ids[ROLE_FIELD_KEYS[f"stage_{stage}"]] = role.id
                created_roles.append(role.name)

            failed_role = await self.create_or_get_role(ctx.guild, FAILED_ROLE_NAME, color=discord.Colour.dark_red())
            role_ids["failed_role_id"] = failed_role.id
            created_roles.append(failed_role.name)

            announce_channel = await self.create_or_get_channel(
                ctx.guild,
                ANNOUNCE_CHANNEL_NAME,
                topic="Tryout duyuruları ve katılım butonları.",
            )
            results_channel = await self.create_or_get_channel(
                ctx.guild,
                RESULT_CHANNEL_NAME,
                topic="Tryout sonuçları ve kayıt geçmişi.",
            )
            role_ids["announce_channel_id"] = announce_channel.id
            role_ids["results_channel_id"] = results_channel.id
        except discord.Forbidden:
            return await ctx.reply("Gerekli Discord izinleri yok. Rol veya kanal oluşturamıyorum.", mention_author=False)
        except discord.HTTPException:
            return await ctx.reply("Discord tarafında hata oluştu. Setup tamamlanamadı.", mention_author=False)

        await self.save_settings(ctx.guild.id, **role_ids)

        embed = PAGEmbeds.success(
            "Tryout sistemi kuruldu.",
            (
                f"Oluşturulan / bulunan roller: {', '.join(created_roles)}\n"
                f"Duyuru kanalı: {announce_channel.mention}\n"
                f"Sonuç kanalı: {results_channel.mention}\n"
                f"Stage aralığı: Stage 0 → Stage 4"
            ),
        )
        await ctx.send(embed=embed)

    async def result_command(self, ctx: commands.Context, *, args: str = "") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self.has_tryout_manage_access(ctx.guild, ctx.author):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        try:
            parsed = await self.parse_result_args(ctx, args)
        except Exception as exc:
            return await ctx.reply(f"Sonuç çözümlenemedi: {exc}", mention_author=False)

        profile = await self._resolve_roblox_user(ctx.guild, parsed.member)
        session = await self._find_related_session(ctx.guild.id, parsed.member.id)
        if session and session.get("status") == "open":
            await self.database.execute(
                """
                INSERT INTO tryout_attendance (
                    session_id,
                    guild_id,
                    discord_id,
                    roblox_id,
                    roblox_username,
                    status,
                    source,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 'attended', 'result', ?)
                ON CONFLICT(session_id, discord_id) DO UPDATE SET
                    roblox_id = excluded.roblox_id,
                    roblox_username = excluded.roblox_username,
                    status = excluded.status,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    int(session["id"]),
                    ctx.guild.id,
                    parsed.member.id,
                    profile.get("roblox_id"),
                    profile.get("roblox_username"),
                    utc_now(),
                ),
            )

        try:
            await self.apply_roles(ctx.guild, parsed.member, parsed.stage, failed=parsed.failed)
        except discord.Forbidden:
            await ctx.reply("Rol veremiyorum veya rol kaldırma yetkim yok.", mention_author=False)
        except discord.HTTPException:
            await ctx.reply("Rol güncellenirken Discord hatası oluştu.", mention_author=False)

        result_id = await self.store_result(ctx.guild, ctx.author, parsed, int(session["id"]) if session else None, profile)
        embed = self.build_result_embed(parsed, ctx.author, profile)
        if session and session.get("announcement_channel_id"):
            await self.refresh_session_message(ctx.guild, int(session["id"]))

        await ctx.send(embed=embed)
        settings = await self.get_settings(ctx.guild.id)
        results_channel_id = settings.get("results_channel_id")
        if results_channel_id:
            channel = ctx.guild.get_channel(int(results_channel_id))
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    self.logger.exception("Failed to mirror tryout result to results channel.")

        self.logger.info("Tryout result saved: result_id=%s member=%s stage=%s", result_id, parsed.member.id, parsed.stage)

    async def history_command(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        if not ctx.guild:
            return
        target = member or ctx.author
        rows = await self.database.fetchall(
            """
            SELECT *
            FROM tryout_results
            WHERE guild_id = ? AND discord_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (ctx.guild.id, target.id),
        )
        if not rows:
            return await ctx.reply("Bu kullanıcı için kayıt bulunamadı.", mention_author=False)

        lines = []
        for row in rows:
            modifier = f" {row['modifier'].title()}" if row["modifier"] else ""
            lines.append(
                f"`#{row['id']}` • Stage {row['stage']} {row['rating'].title()}{modifier} • <@{row['host_id']}> • {row['created_at']}"
            )
        embed = PAGEmbeds.info(
            f"Tryout geçmişi: {target.display_name}",
            "\n".join(lines),
        )
        await ctx.send(embed=embed)

    async def session_command(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        sessions = await self.list_open_sessions(ctx.guild.id)
        if not sessions:
            return await ctx.reply("Açık tryout oturumu yok.", mention_author=False)

        current = sessions[0]
        yes_count, no_count, api_count = await self.get_attendance_counts(int(current["id"]))
        embed = self.build_announcement_embed(current, yes_count, no_count, api_count)
        await ctx.send(embed=embed, view=TryoutAttendanceView(self, int(current["id"])))

    async def close_command(self, ctx: commands.Context, session_id: int | None = None) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self.has_tryout_manage_access(ctx.guild, ctx.author):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        if session_id is None:
            sessions = await self.list_open_sessions(ctx.guild.id)
            if not sessions:
                return await ctx.reply("Kapalı oturum yok.", mention_author=False)
            session_id = int(sessions[0]["id"])

        session = await self.get_session(session_id)
        if not session or int(session["guild_id"]) != ctx.guild.id:
            return await ctx.reply("Bu oturum bulunamadı.", mention_author=False)

        await self.close_session(session_id)
        await self.refresh_session_message(ctx.guild, session_id)
        await ctx.reply(f"Tryout oturumu #{session_id} kapatıldı.", mention_author=False)

    async def annc_command(self, ctx: commands.Context, *, args: str = "") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self.has_tryout_manage_access(ctx.guild, ctx.author):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        link, hoster_text, note_text = split_pipe(args, 3, ("", "", ""))
        link = link.strip()
        if not link:
            return await ctx.reply("Link gerekli. Kullanım: `!tryout-annc link | hoster | not`", mention_author=False)

        place_id = parse_place_id(link)
        hoster_text = parse_hoster_text(hoster_text or ctx.author.display_name)
        note_text = note_text.strip()

        session_id = await self.create_tryout_session(
            ctx.guild,
            ctx.author,
            link,
            hoster_text,
            note_text,
            ctx.channel,
            place_id,
        )

        session = await self.get_session(session_id)
        if session is None:
            return await ctx.reply("Tryout oturumu oluşturulamadı.", mention_author=False)

        scan_count = 0
        try:
            scan_count = await self.best_effort_presence_scan(ctx.guild, session)
        except Exception:
            self.logger.exception("Presence scan crashed while creating tryout session %s.", session_id)

        yes_count, no_count, api_count = await self.get_attendance_counts(session_id)
        embed = self.build_announcement_embed(session, yes_count, no_count, api_count)
        message = await ctx.send(embed=embed, view=TryoutAttendanceView(self, session_id))
        await self.set_session_message(session_id, message.channel.id, message.id)
        self.bot.add_view(TryoutAttendanceView(self, session_id), message_id=message.id)
        if scan_count:
            await self.refresh_session_message(ctx.guild, session_id)
        await ctx.reply(f"Tryout duyurusu hazırlandı. Oturum #{session_id}", mention_author=False)

    async def _find_related_session(self, guild_id: int, discord_id: int) -> dict[str, Any] | None:
        row = await self.database.fetchone(
            """
            SELECT s.*
            FROM tryout_sessions s
            INNER JOIN tryout_attendance a ON a.session_id = s.id
            WHERE s.guild_id = ? AND a.discord_id = ?
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (guild_id, discord_id),
        )
        if row is not None:
            return dict(row)
        sessions = await self.list_open_sessions(guild_id)
        return sessions[0] if sessions else None

    async def on_ready(self) -> None:
        self.logger.info("TryoutSystemCog hazır.")

    @commands.command(name="tryout-setup")
    async def tryout_setup(self, ctx: commands.Context) -> None:
        await self.setup_command(ctx)

    @commands.command(name="tryout-annc")
    async def tryout_annc(self, ctx: commands.Context, *, args: str = "") -> None:
        await self.annc_command(ctx, args=args)

    @commands.command(name="tryout-result", aliases=["try-res"])
    async def tryout_result(self, ctx: commands.Context, *, args: str = "") -> None:
        await self.result_command(ctx, args=args)

    @commands.command(name="tryout-history")
    async def tryout_history(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self.history_command(ctx, member)

    @commands.command(name="tryout-session")
    async def tryout_session(self, ctx: commands.Context) -> None:
        await self.session_command(ctx)

    @commands.command(name="tryout-close")
    async def tryout_close(self, ctx: commands.Context, session_id: int | None = None) -> None:
        await self.close_command(ctx, session_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TryoutSystemCog(bot))
