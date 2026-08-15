from __future__ import annotations

import asyncio
import base64
import copy
import gzip
import hashlib
import io
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import discord
from discord import app_commands
from discord.ext import commands, tasks

try:
    import aiosqlite
except Exception:  # pragma: no cover - the project already requires it
    aiosqlite = None  # type: ignore


# ============================================================
# PAG SECURITY + DISASTER RECOVERY
# ============================================================
#
# Bu Cog iki ana sistemi birleştirir:
#
# 1) Velgrath Lock / Anti-Nuke
#    - owner kullanıcı adı: velgrath_
#    - kick/ban yetkilerini yönetilebilir rollerde kapatır
#    - audit log'u sürekli izler
#    - yetkisiz kick/ban/kanal/rol/emoji/sticker silmelerinde
#      son snapshot'tan geri yükleme dener
#    - ban işlemlerinde otomatik unban yapabilir
#    - kick sonrası hedef kullanıcıya geri dönüş daveti üretir
#    - owner'a onay paneli gönderir
#
# 2) Full Snapshot / Disaster Recovery
#    - sunucu ayarları
#    - roller + izinler + overwrite'lar
#    - kategoriler + kanallar + thread bilgileri
#    - emoji + sticker meta bilgileri
#    - webhook yapılandırmaları
#    - önemli kanal mesajlarının embed/button görünümleri
#    - SQLite içindeki guild ayarlı veriler
#    - retention + sha256 checksum
#
# NOT:
# Discord API bir kick işlemini diğer botlar/adminler tarafından
# yapılmadan önce bir botun yakalayıp durdurmasına izin vermez.
# Bu nedenle gerçek "önleme" katmanı, yönetilebilir rollerden
# KICK/BAN izinlerini otomatik kaldırmaktır. Administrator ve
# sunucu sahibi yetkileri Discord tarafından özel tutulur.
# ============================================================


OWNER_USERNAME = "velgrath_"
OWNER_MATCH_CASE_SENSITIVE = False

BACKUP_ROOT = Path(
    os.getenv("PAG_BACKUP_PATH", "data/backups")
)

BACKUP_RETENTION = max(
    2,
    int(os.getenv("PAG_BACKUP_RETENTION", "20")),
)

AUTO_BACKUP_MINUTES = max(
    1,
    int(os.getenv("PAG_AUTO_BACKUP_MINUTES", "5")),
)

AUDIT_POLL_SECONDS = max(
    1,
    int(os.getenv("PAG_SECURITY_POLL_SECONDS", "3")),
)

MESSAGE_BACKUP_LIMIT = max(
    0,
    int(os.getenv("PAG_MESSAGE_BACKUP_LIMIT", "100")),
)

MAX_RESTORE_MESSAGES_PER_CHANNEL = max(
    0,
    int(
        os.getenv(
            "PAG_MAX_RESTORE_MESSAGES_PER_CHANNEL",
            str(MESSAGE_BACKUP_LIMIT),
        )
    ),
)

BACKUP_IMPORTANT_CHANNEL_KEYWORDS = (
    "raid",
    "announcement",
    "duyuru",
    "oryantasyon",
    "onboarding",
    "başvuru",
    "basvuru",
    "application",
    "apply",
    "tryout",
    "training",
    "line",
)

SECURITY_ACTIONS = {
    discord.AuditLogAction.kick: "kick",
    discord.AuditLogAction.ban: "ban",
    discord.AuditLogAction.channel_delete: "channel_delete",
    discord.AuditLogAction.role_delete: "role_delete",
    discord.AuditLogAction.emoji_delete: "emoji_delete",
    discord.AuditLogAction.sticker_delete: "sticker_delete",
    discord.AuditLogAction.webhook_delete: "webhook_delete",
    discord.AuditLogAction.role_update: "role_update",
    discord.AuditLogAction.channel_update: "channel_update",
    discord.AuditLogAction.guild_update: "guild_update",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def json_safe(value: Any) -> Any:
    """Genel DB/Discord objelerini JSON uyumlu hale getirir."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def restore_json_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type__") == "bytes":
        try:
            return base64.b64decode(value["data"])
        except Exception:
            return b""
    if isinstance(value, list):
        return [restore_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: restore_json_value(v) for k, v in value.items()}
    return value


def component_to_dict(component: discord.Component) -> dict[str, Any]:
    """Message component'larını restore edilebilir görsel metadata'ya çevirir."""
    data: dict[str, Any] = {}

    for attr in (
        "type",
        "custom_id",
        "label",
        "style",
        "url",
        "disabled",
        "placeholder",
        "min_values",
        "max_values",
        "row",
    ):
        if hasattr(component, attr):
            value = getattr(component, attr)
            if isinstance(value, discord.ComponentType):
                value = value.value
            data[attr] = json_safe(value)

    emoji = getattr(component, "emoji", None)
    if emoji is not None:
        data["emoji"] = {
            "name": getattr(emoji, "name", None),
            "id": getattr(emoji, "id", None),
            "animated": getattr(emoji, "animated", False),
        }

    options = getattr(component, "options", None)
    if options:
        data["options"] = [
            {
                "label": getattr(option, "label", ""),
                "value": getattr(option, "value", ""),
                "description": getattr(option, "description", None),
                "emoji": json_safe(getattr(option, "emoji", None)),
                "default": getattr(option, "default", False),
            }
            for option in options
        ]

    children = getattr(component, "children", None)
    if children:
        data["children"] = [
            component_to_dict(child)
            for child in children
        ]

    return data
# ========================================================
# Discord.py compatibility helpers
# ========================================================

def _safe_channel_id(guild: discord.Guild, attr: str) -> int | None:
    """
    Discord.py sürüm farklarına karşı güvenli kanal ID erişimi.
    Önce *_id alanını dener, yoksa kanal nesnesinden ID alır.
    Hiçbiri yoksa None döndürür.
    """

    # Eski / farklı sürümler
    direct = getattr(guild, f"{attr}_id", None)
    if isinstance(direct, int):
        return direct

    # Discord.py 2.x
    channel = getattr(guild, attr, None)
    if channel is not None:
        return getattr(channel, "id", None)

    return None

def embed_to_dict(embed: discord.Embed) -> dict[str, Any]:
    try:
        return json_safe(embed.to_dict())
    except Exception:
        return {}


def overwrite_to_dict(
    target_id: int,
    overwrite: discord.PermissionOverwrite,
) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "allow": overwrite.pair()[0].value,
        "deny": overwrite.pair()[1].value,
    }


def permissions_to_int(permissions: discord.Permissions) -> int:
    return int(permissions.value)


@dataclass(slots=True)
class PendingAction:
    guild_id: int
    action: str
    actor_id: int
    target_id: int | None
    created_at: float
    reason: str
    destructive: bool = True


class ApprovalView(discord.ui.View):
    """Owner için persistent olmayan onay görünümü."""

    def __init__(
        self,
        cog: "SecurityBackup",
        pending: PendingAction,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.pending = pending

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if not await self.cog.is_owner_user(interaction.user):
            await interaction.response.send_message(
                "Bu güvenlik panelini yalnızca Velgrath kullanabilir.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Onayla",
        style=discord.ButtonStyle.danger,
        custom_id="pag_security_approve",
    )
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        result = await self.cog._handle_approval_dispatch(
            self.pending,
            approved=True,
        )

        await interaction.followup.send(
            result,
            ephemeral=True,
        )

        for child in self.children:
            child.disabled = True

        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="Reddet / Kilitle",
        style=discord.ButtonStyle.success,
        custom_id="pag_security_deny",
    )
    async def deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        result = await self.cog._handle_approval_dispatch(
            self.pending,
            approved=False,
        )

        await interaction.followup.send(
            result,
            ephemeral=True,
        )

        for child in self.children:
            child.disabled = True

        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass


class SecurityBackup(commands.Cog):
    """
    PAG tam güvenlik + disaster recovery sistemi.

    Komutlar:
        !backup create
        !backup list
        !backup restore [id]
        !backup verify [id]
        !backup messages [limit]
        !security status
        !security lockdown
        !security unlock
        !security protect
        !security safe-kick @uye <sebep>
        !security approve ...   (panel üzerinden tercih edilir)

    Slash karşılıkları da hybrid command olarak oluşturulur.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("PAG.SecurityBackup")
        self.root = BACKUP_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

        self._guild_locks: dict[int, asyncio.Lock] = {}
        self._last_audit_ids: dict[int, int] = {}
        self._seen_audit_keys: set[tuple[int, int]] = set()
        self._pending: dict[str, PendingAction] = {}
        self._last_snapshot: dict[int, Path] = {}
        self._startup_complete = False

        self.audit_guard_loop.start()
        self.auto_backup_loop.start()

    # ========================================================
    # LIFECYCLE
    # ========================================================

    def cog_unload(self) -> None:
        self.audit_guard_loop.cancel()
        self.auto_backup_loop.cancel()

    async def cog_load(self) -> None:
        await asyncio.sleep(0)
        await self.install_command_guards()

        # Cog loader dosyaları alfabetik sırayla yüklediği için bu cog,
        # moderation'ın ardından gelir. Mevcut kick/ban komutlarını
        # tamamen değiştirmeden bir güvenlik katmanı uygular.
        self.logger.info(
            "SecurityBackup loaded. Owner lock: %s",
            OWNER_USERNAME,
        )

    # ========================================================
    # COMMAND ENFORCEMENT
    # ========================================================

    async def install_command_guards(self) -> None:
        """
        Mevcut moderation cog'undaki kick/ban komutlarını
        approval-only akışına kilitler.

        Böylece yalnızca yeni `security safe-kick` komutu
        ile kick uygulanabilir.
        """
        dangerous_names = {"kick", "ban"}

        for name in dangerous_names:
            command = self.bot.get_command(name)
            if command is None:
                continue

            # Aynı check'in tekrar tekrar eklenmesini önle.
            if not any(
                getattr(check, "__pag_security_guard__", False)
                for check in getattr(command, "checks", [])
            ):
                async def _prefix_guard(
                    ctx: commands.Context,
                    _name: str = name,
                ) -> bool:
                    if _name in dangerous_names:
                        await ctx.reply(
                            "🛡️ PAG Security: Bu komut kilitlendi. "
                            "Kick için `security safe-kick` kullan ve Velgrath onayından geçir.",
                            mention_author=False,
                        )
                        return False
                    return True

                _prefix_guard.__pag_security_guard__ = True  # type: ignore[attr-defined]
                command.add_check(_prefix_guard)

            app_command = getattr(command, "app_command", None)
            if app_command is not None:
                if not any(
                    getattr(check, "__pag_security_guard__", False)
                    for check in getattr(app_command, "checks", [])
                ):
                    async def _slash_guard(
                        interaction: discord.Interaction,
                        _name: str = name,
                    ) -> bool:
                        if await self.is_owner_user(interaction.user):
                            # Owner da bypass etmez; güvenlik için aynı
                            # approval akışını kullanması gerekir.
                            pass
                        if not interaction.response.is_done():
                            await interaction.response.send_message(
                                "🛡️ PAG Security: Bu slash komutu kilitlendi. "
                                "Kick için `security safe-kick` kullan.",
                                ephemeral=True,
                            )
                        return False

                    _slash_guard.__pag_security_guard__ = True  # type: ignore[attr-defined]
                    app_command.add_check(_slash_guard)

    # ========================================================
    # OWNER
    # ========================================================

    async def is_owner_user(self, user: discord.abc.User) -> bool:
        name = getattr(user, "name", "") or ""
        if OWNER_MATCH_CASE_SENSITIVE:
            return name == OWNER_USERNAME
        return name.lower() == OWNER_USERNAME.lower()

    async def get_owner_member(
        self,
        guild: discord.Guild,
    ) -> discord.Member | None:
        for member in guild.members:
            if await self.is_owner_user(member):
                return member

        try:
            owner = await guild.fetch_member(guild.owner_id)
            if await self.is_owner_user(owner):
                return owner
        except discord.HTTPException:
            pass

        return None

    async def require_owner(self, ctx: commands.Context) -> bool:
        if await self.is_owner_user(ctx.author):
            return True

        await ctx.reply(
            "⛔ Bu komut yalnızca `velgrath_` owner hesabı tarafından kullanılabilir.",
            mention_author=False,
        )
        return False

    async def application_owner_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if await self.is_owner_user(interaction.user):
            return True
        raise app_commands.CheckFailure(
            "Bu komut yalnızca velgrath_ tarafından kullanılabilir."
        )

    # ========================================================
    # PATH / ID
    # ========================================================

    def guild_dir(self, guild_id: int) -> Path:
        path = self.root / str(guild_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def make_backup_id(self, guild: discord.Guild) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{guild.id}_{stamp}"

    def backup_path(self, guild: discord.Guild, backup_id: str) -> Path:
        return self.guild_dir(guild.id) / f"{backup_id}.json.gz"

    # ========================================================
    # DISCORD SERIALIZATION
    # ========================================================

    async def serialize_guild(
        self,
        guild: discord.Guild,
        include_all_messages: bool = False,
    ) -> dict[str, Any]:
        roles = [
            self.serialize_role(role)
            for role in sorted(guild.roles, key=lambda r: r.position)
            if not role.is_default()
        ]

        channels = []
        for channel in sorted(guild.channels, key=lambda c: (c.position, c.id)):
            channels.append(
                await self.serialize_channel(
                    channel,
                    guild,
                    include_messages=(
                        include_all_messages
                        or self.is_important_channel(channel)
                    ),
                )
            )

        emojis = []
        for emoji in guild.emojis:
            emojis.append(
                {
                    "id": emoji.id,
                    "name": emoji.name,
                    "animated": emoji.animated,
                    "available": emoji.available,
                    "managed": emoji.managed,
                    "url": str(emoji.url),
                }
            )

        stickers = []
        for sticker in guild.stickers:
            stickers.append(
                {
                    "id": sticker.id,
                    "name": sticker.name,
                    "description": sticker.description,
                    "emoji": sticker.emoji,
                    "format_type": getattr(sticker.format, "value", None),
                    "url": str(sticker.url),
                }
            )

        webhooks = await self.serialize_webhooks(guild)
        threads = await self.serialize_threads(guild)

        return {
            "schema_version": 3,
            "created_at": utc_now(),
            "guild": self.serialize_guild_settings(guild),
            "roles": roles,
            "channels": channels,
            "emojis": emojis,
            "stickers": stickers,
            "webhooks": webhooks,
            "threads": threads,
            "database": await self.serialize_database(guild),
            "security": {
                "owner_username": OWNER_USERNAME,
                "message_backup_limit": MESSAGE_BACKUP_LIMIT,
                "important_channel_keywords": list(
                    BACKUP_IMPORTANT_CHANNEL_KEYWORDS
                ),
            },
        }

    def serialize_guild_settings(
        self,
        guild: discord.Guild,
    ) -> dict[str, Any]:
        return {
            "id": guild.id,
            "name": guild.name,
            "description": guild.description,
            "verification_level": getattr(
                guild.verification_level,
                "value",
                None,
            ),
            "default_notifications": getattr(
                guild.default_notifications,
                "value",
                None,
            ),
            "explicit_content_filter": getattr(
                guild.explicit_content_filter,
                "value",
                None,
            ),
            "afk_timeout": guild.afk_timeout,
            "system_channel_id": _safe_channel_id(guild, "system_channel"),
            "rules_channel_id": _safe_channel_id(guild, "rules_channel"),
            "public_updates_channel_id": _safe_channel_id(guild, "public_updates_channel"),
            "afk_channel_id": _safe_channel_id(guild, "afk_channel"),
            "preferred_locale": str(getattr(guild, "preferred_locale", "en-US")),
            "features": list(getattr(guild, "features", [])),
        }

    def serialize_role(
        self,
        role: discord.Role,
    ) -> dict[str, Any]:
        return {
            "id": role.id,
            "name": role.name,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "permissions": permissions_to_int(role.permissions),
            "position": role.position,
            "managed": role.managed,
        }

    def serialize_overwrites(
        self,
        channel: discord.abc.GuildChannel,
    ) -> list[dict[str, Any]]:
        result = []
        for target, overwrite in channel.overwrites.items():
            result.append(
                overwrite_to_dict(
                    target.id,
                    overwrite,
                )
            )
        return result

    async def serialize_channel(
        self,
        channel: discord.abc.GuildChannel,
        guild: discord.Guild,
        include_messages: bool = False,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": channel.id,
            "name": channel.name,
            "type": channel.type.value,
            "position": channel.position,
            "category_id": channel.category_id,
            "overwrites": self.serialize_overwrites(channel),
        }

        if isinstance(channel, discord.TextChannel):
            item.update(
                {
                    "topic": channel.topic,
                    "slowmode_delay": channel.slowmode_delay,
                    "nsfw": channel.nsfw,
                    "default_auto_archive_duration": getattr(
                        channel,
                        "default_auto_archive_duration",
                        None,
                    ),
                }
            )

        elif isinstance(channel, discord.VoiceChannel):
            item.update(
                {
                    "bitrate": channel.bitrate,
                    "user_limit": channel.user_limit,
                    "rtc_region": (
                        str(channel.rtc_region)
                        if channel.rtc_region is not None
                        else None
                    ),
                    "video_quality_mode": getattr(
                        getattr(channel, "video_quality_mode", None),
                        "value",
                        None,
                    ),
                }
            )

        elif isinstance(channel, discord.StageChannel):
            item.update(
                {
                    "bitrate": channel.bitrate,
                    "user_limit": channel.user_limit,
                    "rtc_region": (
                        str(channel.rtc_region)
                        if channel.rtc_region is not None
                        else None
                    ),
                }
            )

        elif isinstance(channel, discord.CategoryChannel):
            item.update({"category": True})

        if include_messages and isinstance(channel, discord.TextChannel):
            item["messages"] = await self.serialize_messages(
                channel,
                MESSAGE_BACKUP_LIMIT,
            )
        else:
            item["messages"] = []

        return item

    async def serialize_messages(
        self,
        channel: discord.TextChannel,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        result: list[dict[str, Any]] = []
        try:
            async for message in channel.history(
                limit=min(limit, 500),
                oldest_first=False,
            ):
                result.append(
                    {
                        "id": message.id,
                        "author_id": message.author.id,
                        "author_name": str(message.author),
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                        "edited_at": (
                            message.edited_at.isoformat()
                            if message.edited_at
                            else None
                        ),
                        "embeds": [
                            embed_to_dict(embed)
                            for embed in message.embeds
                        ],
                        "components": [
                            component_to_dict(component)
                            for component in message.components
                        ],
                        "attachments": [
                            {
                                "id": attachment.id,
                                "filename": attachment.filename,
                                "url": attachment.url,
                                "content_type": attachment.content_type,
                                "size": attachment.size,
                            }
                            for attachment in message.attachments
                        ],
                        "reference_message_id": (
                            message.reference.message_id
                            if message.reference
                            else None
                        ),
                    }
                )
        except (discord.Forbidden, discord.HTTPException):
            self.logger.warning(
                "Message backup failed for #%s (%s)",
                channel.name,
                channel.id,
            )

        result.reverse()
        return result

    async def serialize_webhooks(
        self,
        guild: discord.Guild,
    ) -> list[dict[str, Any]]:
        result = []
        for channel in guild.text_channels:
            try:
                hooks = await channel.webhooks()
            except (discord.Forbidden, discord.HTTPException):
                continue

            for webhook in hooks:
                result.append(
                    {
                        "id": webhook.id,
                        "name": webhook.name,
                        "channel_id": webhook.channel_id,
                        "type": webhook.type.value,
                        "user_id": (
                            webhook.user.id
                            if webhook.user
                            else None
                        ),
                        "avatar": (
                            str(webhook.avatar.url)
                            if webhook.avatar
                            else None
                        ),
                        "warning": (
                            "Webhook token is intentionally not stored; "
                            "Discord does not expose existing webhook tokens "
                            "to a normal bot fetch."
                        ),
                    }
                )
        return result

    async def serialize_threads(
        self,
        guild: discord.Guild,
    ) -> list[dict[str, Any]]:
        result = []
        for thread in guild.threads:
            result.append(
                {
                    "id": thread.id,
                    "name": thread.name,
                    "parent_id": thread.parent_id,
                    "archived": thread.archived,
                    "locked": thread.locked,
                    "auto_archive_duration": thread.auto_archive_duration,
                    "slowmode_delay": thread.slowmode_delay,
                    "type": thread.type.value,
                }
            )
        return result

    def is_important_channel(
        self,
        channel: discord.abc.GuildChannel,
    ) -> bool:
        name = channel.name.lower()
        return any(
            keyword in name
            for keyword in BACKUP_IMPORTANT_CHANNEL_KEYWORDS
        )

    # ========================================================
    # DATABASE SNAPSHOT
    # ========================================================

    async def serialize_database(
        self,
        guild: discord.Guild,
    ) -> dict[str, Any]:
        """
        Bot veritabanındaki tabloları dinamik olarak snapshot'lar.

        - guild_id/server_id bulunan tablolar: yalnızca ilgili guild
        - user/member/discord_id bulunan tablolar: guild üyeleriyle
          ilişkilendirilebilir satırlar
        - diğer tablolar: snapshot'a alınır ama restore sırasında
          güvenli merge yapılır
        """
        db = getattr(self.bot, "database", None)
        connection = getattr(db, "_connection", None)
        if connection is None:
            connection = getattr(db, "connection", None)

        if connection is None:
            return {
                "available": False,
                "reason": "Database connection not available.",
                "tables": [],
            }

        try:
            async with connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ) as cursor:
                table_rows = await cursor.fetchall()

            tables: list[dict[str, Any]] = []
            member_ids = {member.id for member in guild.members}
            member_ids.add(guild.owner_id)

            for table_row in table_rows:
                table_name = table_row[0]

                async with connection.execute(
                    f'PRAGMA table_info("{table_name.replace(chr(34), chr(34) * 2)}")'
                ) as cursor:
                    columns = await cursor.fetchall()

                column_names = [row[1] for row in columns]
                lower_columns = {name.lower() for name in column_names}

                filter_column = None
                for candidate in (
                    "guild_id",
                    "server_id",
                    "guildid",
                    "serverid",
                ):
                    if candidate in lower_columns:
                        filter_column = next(
                            name
                            for name in column_names
                            if name.lower() == candidate
                        )
                        break

                member_filter_column = None
                for candidate in (
                    "discord_id",
                    "user_id",
                    "member_id",
                ):
                    if candidate in lower_columns:
                        member_filter_column = next(
                            name
                            for name in column_names
                            if name.lower() == candidate
                        )
                        break

                query = (
                    f'SELECT * FROM "{table_name.replace(chr(34), chr(34) * 2)}"'
                )
                params: tuple[Any, ...] = ()

                if filter_column is not None:
                    query += (
                        f' WHERE "{filter_column.replace(chr(34), chr(34) * 2)}" = ?'
                    )
                    params = (guild.id,)
                elif member_filter_column is not None:
                    placeholders = ",".join("?" for _ in member_ids)
                    if placeholders:
                        query += (
                            f' WHERE "{member_filter_column.replace(chr(34), chr(34) * 2)}" '
                            f"IN ({placeholders})"
                        )
                        params = tuple(member_ids)

                async with connection.execute(query, params) as cursor:
                    rows = await cursor.fetchall()

                serial_rows = []
                for row in rows:
                    if hasattr(row, "keys"):
                        record = {
                            key: json_safe(row[key])
                            for key in row.keys()
                        }
                    else:
                        record = {
                            column_names[index]: json_safe(value)
                            for index, value in enumerate(row)
                        }
                    serial_rows.append(record)

                tables.append(
                    {
                        "name": table_name,
                        "columns": column_names,
                        "primary_keys": [
                            row[1]
                            for row in columns
                            if row[5]
                        ],
                        "guild_filter_column": filter_column,
                        "member_filter_column": member_filter_column,
                        "rows": serial_rows,
                    }
                )

            return {
                "available": True,
                "created_at": utc_now(),
                "tables": tables,
            }

        except Exception as exc:
            self.logger.exception("Database snapshot failed.")
            return {
                "available": False,
                "reason": repr(exc),
                "tables": [],
            }

    async def restore_database(
        self,
        guild: discord.Guild,
        db_snapshot: dict[str, Any],
    ) -> list[str]:
        restored: list[str] = []
        if not db_snapshot.get("available"):
            return restored

        db = getattr(self.bot, "database", None)
        connection = getattr(db, "_connection", None)
        if connection is None:
            connection = getattr(db, "connection", None)
        if connection is None:
            return restored

        for table in db_snapshot.get("tables", []):
            table_name = str(table.get("name", ""))
            columns = [str(c) for c in table.get("columns", [])]
            rows = table.get("rows", [])
            guild_column = table.get("guild_filter_column")

            if not table_name or not columns or not rows:
                continue

            qtable = '"' + table_name.replace('"', '""') + '"'
            qcols = ",".join(
                '"' + col.replace('"', '""') + '"'
                for col in columns
            )
            placeholders = ",".join("?" for _ in columns)

            try:
                if guild_column:
                    qguild = '"' + str(guild_column).replace('"', '""') + '"'
                    await connection.execute(
                        f"DELETE FROM {qtable} WHERE {qguild} = ?",
                        (guild.id,),
                    )

                for record in rows:
                    values = tuple(
                        restore_json_value(record.get(column))
                        for column in columns
                    )
                    await connection.execute(
                        f"INSERT OR REPLACE INTO {qtable} ({qcols}) "
                        f"VALUES ({placeholders})",
                        values,
                    )

                restored.append(table_name)
            except Exception:
                self.logger.exception(
                    "Database table restore failed: %s",
                    table_name,
                )

        try:
            await connection.commit()
        except Exception:
            self.logger.exception("Database restore commit failed.")

        return restored

    # ========================================================
    # FILE I/O / CHECKSUM
    # ========================================================

    async def write_backup_file(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        backup_id: str,
    ) -> Path:
        path = self.backup_path(guild, backup_id)
        temp = path.with_suffix(".tmp")

        payload = json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        checksum = hashlib.sha256(payload).hexdigest()
        snapshot["integrity"] = {
            "algorithm": "sha256",
            "payload_sha256": checksum,
        }

        # integrity alanı payload'un parçası olduğu için ikinci hash gerekir;
        # final dosyanın hash'i ayrıca manifestte tutulur.
        final_payload = json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        def _write() -> None:
            with gzip.open(temp, "wb", compresslevel=6) as file:
                file.write(final_payload)
            temp.replace(path)

            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = path.with_suffix(path.suffix + ".sha256")
            manifest.write_text(
                sha256,
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)
        return path

    async def read_backup_file(
        self,
        path: Path,
    ) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)

        def _read() -> dict[str, Any]:
            with gzip.open(path, "rb") as file:
                return json.loads(file.read().decode("utf-8"))

        return await asyncio.to_thread(_read)

    async def verify_backup_file(
        self,
        path: Path,
    ) -> tuple[bool, str]:
        manifest = path.with_suffix(path.suffix + ".sha256")
        if not path.exists() or not manifest.exists():
            return False, "Backup veya checksum manifesti bulunamadı."

        def _verify() -> tuple[bool, str]:
            expected = manifest.read_text(encoding="utf-8").strip()
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected != actual:
                return False, "SHA-256 uyuşmuyor; dosya değişmiş olabilir."
            return True, "SHA-256 doğrulandı."

        return await asyncio.to_thread(_verify)

    # ========================================================
    # BACKUP MANAGER
    # ========================================================

    async def create_backup(
        self,
        guild: discord.Guild,
        *,
        include_all_messages: bool = False,
    ) -> tuple[str, Path, dict[str, Any]]:
        lock = self._guild_locks.setdefault(
            guild.id,
            asyncio.Lock(),
        )

        async with lock:
            backup_id = self.make_backup_id(guild)
            snapshot = await self.serialize_guild(
                guild,
                include_all_messages=include_all_messages,
            )
            path = await self.write_backup_file(
                guild,
                snapshot,
                backup_id,
            )
            self._last_snapshot[guild.id] = path
            await self.prune_backups(guild)
            return backup_id, path, snapshot

    async def list_backups(
        self,
        guild: discord.Guild,
    ) -> list[Path]:
        directory = self.guild_dir(guild.id)
        files = sorted(
            directory.glob("*.json.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files

    async def prune_backups(self, guild: discord.Guild) -> None:
        files = await self.list_backups(guild)
        for path in files[BACKUP_RETENTION:]:
            try:
                path.unlink(missing_ok=True)
                path.with_suffix(path.suffix + ".sha256").unlink(
                    missing_ok=True
                )
            except OSError:
                self.logger.exception(
                    "Backup cleanup failed: %s",
                    path,
                )

    async def resolve_backup(
        self,
        guild: discord.Guild,
        identifier: str | None,
    ) -> Path:
        files = await self.list_backups(guild)
        if not files:
            raise FileNotFoundError("Bu sunucu için backup bulunamadı.")

        if not identifier or identifier.lower() in {"latest", "last", "son"}:
            return files[0]

        for path in files:
            if path.stem == identifier or identifier in path.name:
                return path

        raise FileNotFoundError(
            f"Backup bulunamadı: {identifier}"
        )

    # ========================================================
    # RESTORE ENGINE
    # ========================================================

    async def restore_backup(
        self,
        guild: discord.Guild,
        snapshot: dict[str, Any],
        *,
        restore_messages: bool = True,
        restore_database: bool = True,
    ) -> dict[str, Any]:
        lock = self._guild_locks.setdefault(
            guild.id,
            asyncio.Lock(),
        )

        async with lock:
            report: dict[str, Any] = {
                "roles_created": 0,
                "roles_updated": 0,
                "channels_created": 0,
                "channels_updated": 0,
                "channels_deleted": 0,
                "messages_restored": 0,
                "emojis_created": 0,
                "stickers_skipped": 0,
                "webhooks_created": 0,
                "database_tables": [],
                "errors": [],
            }

            role_map: dict[int, discord.Role] = {
                role.id: role
                for role in guild.roles
            }

            # ------------------------------------------------
            # ROLES
            # ------------------------------------------------
            for role_data in snapshot.get("roles", []):
                if role_data.get("managed"):
                    continue

                old_id = safe_int(role_data.get("id"))
                role = role_map.get(old_id)

                try:
                    if role is None:
                        role = await guild.create_role(
                            name=str(role_data.get("name", "Restored Role"))[:100],
                            permissions=discord.Permissions(
                                permissions=safe_int(
                                    role_data.get("permissions")
                                )
                            ),
                            colour=discord.Colour(
                                safe_int(role_data.get("color"), 0)
                            ),
                            hoist=bool(role_data.get("hoist")),
                            mentionable=bool(role_data.get("mentionable")),
                            reason="PAG disaster recovery",
                        )
                        role_map[old_id] = role
                        report["roles_created"] += 1
                    else:
                        await role.edit(
                            name=str(role_data.get("name", role.name))[:100],
                            permissions=discord.Permissions(
                                permissions=safe_int(
                                    role_data.get("permissions"),
                                    role.permissions.value,
                                )
                            ),
                            colour=discord.Colour(
                                safe_int(
                                    role_data.get("color"),
                                    role.color.value,
                                )
                            ),
                            hoist=bool(role_data.get("hoist")),
                            mentionable=bool(role_data.get("mentionable")),
                            reason="PAG disaster recovery",
                        )
                        report["roles_updated"] += 1
                except discord.Forbidden:
                    report["errors"].append(
                        f"Role permission denied: {role_data.get('name')}"
                    )
                except discord.HTTPException as exc:
                    report["errors"].append(
                        f"Role restore failed: {role_data.get('name')}: {exc}"
                    )

            # Role hierarchy must be restored after creation.
            position_payload = []
            for role_data in snapshot.get("roles", []):
                role = role_map.get(safe_int(role_data.get("id")))
                if role is not None and not role.is_default():
                    position_payload.append(
                        {
                            "id": role.id,
                            "position": safe_int(role_data.get("position")),
                        }
                    )

            try:
                for item in sorted(
                    position_payload,
                    key=lambda x: x["position"],
                ):
                    role = guild.get_role(item["id"])
                    if role is None:
                        continue
                    await role.edit(
                        position=max(0, item["position"]),
                        reason="PAG disaster recovery role hierarchy",
                    )
            except (discord.Forbidden, discord.HTTPException):
                self.logger.warning(
                    "Role hierarchy restore partially failed."
                )

            # ------------------------------------------------
            # CHANNELS
            # ------------------------------------------------
            channel_map: dict[int, discord.abc.GuildChannel] = {
                channel.id: channel
                for channel in guild.channels
            }

            # Create parents/categories first.
            channel_data_sorted = sorted(
                snapshot.get("channels", []),
                key=lambda item: (
                    0 if item.get("type") == discord.ChannelType.category.value else 1,
                    safe_int(item.get("position")),
                ),
            )

            for item in channel_data_sorted:
                old_id = safe_int(item.get("id"))
                existing = channel_map.get(old_id)
                channel_type = safe_int(
                    item.get("type"),
                    discord.ChannelType.text.value,
                )

                if existing is not None:
                    try:
                        await self.edit_existing_channel(
                            guild,
                            existing,
                            item,
                            role_map,
                        )
                        report["channels_updated"] += 1
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        report["errors"].append(
                            f"Channel edit failed: {item.get('name')}: {exc}"
                        )
                    continue

                try:
                    created = await self.create_channel_from_snapshot(
                        guild,
                        item,
                        role_map,
                        channel_map,
                    )
                    if created is not None:
                        channel_map[old_id] = created
                        report["channels_created"] += 1
                except (discord.Forbidden, discord.HTTPException) as exc:
                    report["errors"].append(
                        f"Channel create failed: {item.get('name')}: {exc}"
                    )

            # Overwrites are best restored after all channels/roles exist.
            for item in snapshot.get("channels", []):
                channel = channel_map.get(safe_int(item.get("id")))
                if channel is None:
                    continue

                try:
                    await self.restore_overwrites(
                        channel,
                        item.get("overwrites", []),
                        role_map,
                        guild,
                    )
                except (discord.Forbidden, discord.HTTPException) as exc:
                    report["errors"].append(
                        f"Overwrite restore failed: {item.get('name')}: {exc}"
                    )

            # ------------------------------------------------
            # MESSAGES
            # ------------------------------------------------
            if restore_messages:
                for item in snapshot.get("channels", []):
                    messages = item.get("messages", []) or []
                    if not messages:
                        continue
                    channel = channel_map.get(safe_int(item.get("id")))
                    if not isinstance(channel, discord.TextChannel):
                        continue

                    restored = await self.restore_messages(
                        channel,
                        messages,
                        max_messages=MAX_RESTORE_MESSAGES_PER_CHANNEL,
                    )
                    report["messages_restored"] += restored

            # ------------------------------------------------
            # EMOJIS
            # ------------------------------------------------
            existing_emoji_names = {emoji.name for emoji in guild.emojis}
            for item in snapshot.get("emojis", []):
                name = str(item.get("name", ""))[:32]
                if not name or name in existing_emoji_names:
                    continue

                try:
                    image = await self.download_asset(str(item.get("url", "")))
                    if not image:
                        continue
                    await guild.create_custom_emoji(
                        name=name,
                        image=image,
                        reason="PAG disaster recovery",
                    )
                    existing_emoji_names.add(name)
                    report["emojis_created"] += 1
                except (discord.Forbidden, discord.HTTPException, ValueError):
                    report["errors"].append(
                        f"Emoji restore failed: {name}"
                    )

            # ------------------------------------------------
            # WEBHOOKS
            # ------------------------------------------------
            report["webhooks_created"] += await self.restore_webhooks(
                guild,
                snapshot.get("webhooks", []),
            )

            # ------------------------------------------------
            # GUILD SETTINGS
            # ------------------------------------------------
            try:
                await self.restore_guild_settings(
                    guild,
                    snapshot.get("guild", {}),
                    channel_map,
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                report["errors"].append(
                    f"Guild settings restore failed: {exc}"
                )

            # ------------------------------------------------
            # DATABASE / BOT SETTINGS
            # ------------------------------------------------
            if restore_database:
                report["database_tables"] = await self.restore_database(
                    guild,
                    snapshot.get("database", {}),
                )

            return report

    async def create_channel_from_snapshot(
        self,
        guild: discord.Guild,
        item: dict[str, Any],
        role_map: dict[int, discord.Role],
        channel_map: dict[int, discord.abc.GuildChannel],
    ) -> discord.abc.GuildChannel | None:
        name = str(item.get("name", "restored"))[:100]
        channel_type = safe_int(
            item.get("type"),
            discord.ChannelType.text.value,
        )

        category = channel_map.get(
            safe_int(item.get("category_id"))
        )
        if not isinstance(category, discord.CategoryChannel):
            category = None

        overwrites = self.build_overwrites(
            item.get("overwrites", []),
            role_map,
            guild,
        )

        if channel_type == discord.ChannelType.category.value:
            return await guild.create_category(
                name=name,
                overwrites=overwrites,
                reason="PAG disaster recovery",
            )

        if channel_type == discord.ChannelType.text.value:
            return await guild.create_text_channel(
                name=name,
                category=category,
                topic=item.get("topic"),
                slowmode_delay=safe_int(item.get("slowmode_delay")),
                nsfw=bool(item.get("nsfw")),
                overwrites=overwrites,
                reason="PAG disaster recovery",
            )

        if channel_type == discord.ChannelType.voice.value:
            return await guild.create_voice_channel(
                name=name,
                category=category,
                bitrate=safe_int(item.get("bitrate")) or None,
                user_limit=safe_int(item.get("user_limit")),
                overwrites=overwrites,
                reason="PAG disaster recovery",
            )

        if channel_type == discord.ChannelType.stage_voice.value:
            return await guild.create_stage_channel(
                name=name,
                category=category,
                bitrate=safe_int(item.get("bitrate")) or None,
                user_limit=safe_int(item.get("user_limit")),
                overwrites=overwrites,
                reason="PAG disaster recovery",
            )

        return None

    async def edit_existing_channel(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        item: dict[str, Any],
        role_map: dict[int, discord.Role],
    ) -> None:
        kwargs: dict[str, Any] = {
            "name": str(item.get("name", channel.name))[:100],
        }

        if isinstance(channel, discord.TextChannel):
            kwargs.update(
                {
                    "topic": item.get("topic"),
                    "slowmode_delay": safe_int(item.get("slowmode_delay")),
                    "nsfw": bool(item.get("nsfw")),
                }
            )

        if isinstance(channel, discord.VoiceChannel):
            kwargs.update(
                {
                    "bitrate": safe_int(item.get("bitrate"), channel.bitrate),
                    "user_limit": safe_int(item.get("user_limit"), channel.user_limit),
                }
            )

        try:
            await channel.edit(
                **kwargs,
                reason="PAG disaster recovery",
            )
        except TypeError:
            # Bazı channel türlerinde kwargs fazladan olabilir.
            await channel.edit(
                name=kwargs["name"],
                reason="PAG disaster recovery",
            )

    def build_overwrites(
        self,
        items: Iterable[dict[str, Any]],
        role_map: dict[int, discord.Role],
        guild: discord.Guild,
    ) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        result: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}

        for item in items:
            target_id = safe_int(item.get("target_id"))
            allow = discord.Permissions(safe_int(item.get("allow")))
            deny = discord.Permissions(safe_int(item.get("deny")))
            role = role_map.get(target_id) or guild.get_role(target_id)

            if role is None:
                continue

            overwrite = discord.PermissionOverwrite.from_pair(
                allow,
                deny,
            )
            result[role] = overwrite

        return result

    async def restore_overwrites(
        self,
        channel: discord.abc.GuildChannel,
        items: Iterable[dict[str, Any]],
        role_map: dict[int, discord.Role],
        guild: discord.Guild,
    ) -> None:
        for item in items:
            target_id = safe_int(item.get("target_id"))
            role = role_map.get(target_id) or guild.get_role(target_id)
            if role is None:
                continue

            allow = discord.Permissions(safe_int(item.get("allow")))
            deny = discord.Permissions(safe_int(item.get("deny")))
            overwrite = discord.PermissionOverwrite.from_pair(allow, deny)

            await channel.set_permissions(
                role,
                overwrite=overwrite,
                reason="PAG disaster recovery",
            )

    async def restore_messages(
        self,
        channel: discord.TextChannel,
        messages: list[dict[str, Any]],
        *,
        max_messages: int,
    ) -> int:
        if max_messages <= 0:
            return 0

        count = 0
        ordered = messages[-max_messages:]

        for message_data in ordered:
            content = str(message_data.get("content", ""))
            embeds = []
            for data in message_data.get("embeds", []):
                try:
                    embeds.append(discord.Embed.from_dict(data))
                except Exception:
                    continue

            # Link buttonlarını ve disabled state'lerini mümkün olduğunca
            # görsel olarak geri kur. Custom ID'li interaction davranışı
            # botun koduna bağlı olduğundan burada yalnızca görünüm restore edilir.
            view = self.build_view_from_components(
                message_data.get("components", [])
            )

            if not content and not embeds and view is None:
                continue

            try:
                await channel.send(
                    content=content[:2000] if content else None,
                    embeds=embeds[:10],
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                count += 1
            except (discord.Forbidden, discord.HTTPException):
                self.logger.warning(
                    "Message restore failed in #%s",
                    channel.name,
                )

        return count

    def build_view_from_components(
        self,
        components: list[dict[str, Any]],
    ) -> discord.ui.View | None:
        if not components:
            return None

        view = discord.ui.View(timeout=0)

        def add_component(data: dict[str, Any]) -> None:
            children = data.get("children") or []
            if children:
                for child in children:
                    add_component(child)
                return

            component_type = safe_int(data.get("type"))

            if component_type != discord.ComponentType.button.value:
                return

            style_value = safe_int(
                data.get("style"),
                discord.ButtonStyle.secondary.value,
            )
            try:
                style = discord.ButtonStyle(style_value)
            except ValueError:
                style = discord.ButtonStyle.secondary

            emoji_data = data.get("emoji")
            emoji = None
            if isinstance(emoji_data, dict):
                emoji = emoji_data.get("name")

            button = discord.ui.Button(
                label=(str(data.get("label"))[:80] if data.get("label") else None),
                style=style,
                custom_id=(
                    str(data.get("custom_id"))[:100]
                    if data.get("custom_id")
                    else None
                ),
                url=(
                    str(data.get("url"))[:512]
                    if data.get("url")
                    else None
                ),
                disabled=bool(data.get("disabled")),
                emoji=emoji,
            )
            view.add_item(button)

        for component in components:
            add_component(component)

        return view if view.children else None

    async def restore_webhooks(
        self,
        guild: discord.Guild,
        webhooks: list[dict[str, Any]],
    ) -> int:
        created = 0
        existing_by_channel: dict[int, set[str]] = {}

        for channel in guild.text_channels:
            try:
                hooks = await channel.webhooks()
            except (discord.Forbidden, discord.HTTPException):
                continue
            existing_by_channel[channel.id] = {
                hook.name
                for hook in hooks
                if hook.name
            }

        for item in webhooks:
            channel = guild.get_channel(
                safe_int(item.get("channel_id"))
            )
            if not isinstance(channel, discord.TextChannel):
                continue

            name = str(item.get("name", "restored-webhook"))[:80]
            if name in existing_by_channel.setdefault(channel.id, set()):
                continue

            try:
                avatar = None
                if item.get("avatar"):
                    avatar = await self.download_asset(
                        str(item.get("avatar"))
                    )
                await channel.create_webhook(
                    name=name,
                    avatar=avatar,
                    reason="PAG disaster recovery",
                )
                existing_by_channel[channel.id].add(name)
                created += 1
            except (discord.Forbidden, discord.HTTPException, ValueError):
                self.logger.warning(
                    "Webhook restore failed in #%s: %s",
                    channel.name,
                    name,
                )

        return created

    async def restore_guild_settings(
        self,
        guild: discord.Guild,
        data: dict[str, Any],
        channel_map: dict[int, discord.abc.GuildChannel],
    ) -> None:
        kwargs: dict[str, Any] = {}

        if data.get("name"):
            kwargs["name"] = str(data["name"])[:100]
        if data.get("description") is not None:
            kwargs["description"] = str(data["description"])[:120]

        for key, enum_type in (
            ("verification_level", discord.VerificationLevel),
            ("default_notifications", discord.NotificationLevel),
            ("explicit_content_filter", discord.ContentFilter),
        ):
            value = data.get(key)
            if value is None:
                continue
            try:
                kwargs[key] = enum_type(value)
            except ValueError:
                pass

        if data.get("afk_timeout") is not None:
            kwargs["afk_timeout"] = safe_int(data["afk_timeout"])

        for source_key, dest_key in (
            ("system_channel_id", "system_channel"),
            ("rules_channel_id", "rules_channel"),
            ("public_updates_channel_id", "public_updates_channel"),
            ("afk_channel_id", "afk_channel"),
        ):
            source_id = safe_int(data.get(source_key))
            channel = channel_map.get(source_id) if source_id else None
            if channel is not None:
                kwargs[dest_key] = channel

        if kwargs:
            await guild.edit(
                **kwargs,
                reason="PAG disaster recovery",
            )

    async def download_asset(self, url: str) -> bytes | None:
        if not url.startswith(("https://", "http://")):
            return None

        def _download() -> bytes | None:
            import urllib.request

            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "PAGBot-DisasterRecovery/1.0"
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read()
                return data if data else None
            except Exception:
                return None

        return await asyncio.to_thread(_download)

    # ========================================================
    # SECURITY / HARDENING
    # ========================================================

    async def protect_roles(self, guild: discord.Guild) -> int:
        """
        Yönetilebilir rollerden KICK/BAN yetkisini kaldırır.

        Administrator Discord tarafından ayrıcalıklı olduğu için
        admin rolü varsa bunu bu katmanda tamamen etkisizleştiremez.
        """
        me = guild.me
        if me is None:
            return 0

        changed = 0
        forbidden = (
            discord.Permissions.kick_members,
            discord.Permissions.ban_members,
        )

        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            if role >= me.top_role:
                continue

            permissions = role.permissions
            before = permissions.value

            permissions.kick_members = False
            permissions.ban_members = False

            if permissions.value == before:
                continue

            try:
                await role.edit(
                    permissions=permissions,
                    reason="PAG Velgrath Lock: kick/ban disabled",
                )
                changed += 1
            except (discord.Forbidden, discord.HTTPException):
                self.logger.warning(
                    "Unable to harden role: %s (%s)",
                    role.name,
                    role.id,
                )

        # The variable exists to make the intended protected permission
        # set explicit and avoid accidental future narrowing.
        _ = forbidden
        return changed

    async def protect_owner(self, guild: discord.Guild) -> None:
        owner = await self.get_owner_member(guild)
        if owner is None:
            return

        # Owner's managed-role placement is controlled by Discord. We do not
        # attempt to mutate the server owner or their identity.
        self.logger.info(
            "Owner lock verified for %s (%s) in %s.",
            owner,
            owner.id,
            guild.name,
        )

    async def run_lockdown(self, guild: discord.Guild) -> int:
        changed = await self.protect_roles(guild)
        await self.create_backup(guild, include_all_messages=False)
        return changed

    # ========================================================
    # AUDIT LOG GUARD
    # ========================================================

    async def find_recent_actions(
        self,
        guild: discord.Guild,
    ) -> list[discord.AuditLogEntry]:
        actions = list(SECURITY_ACTIONS.keys())
        entries: list[discord.AuditLogEntry] = []

        for action in actions:
            try:
                async for entry in guild.audit_logs(
                    limit=10,
                    action=action,
                ):
                    if entry.id in self._seen_audit_keys:
                        continue
                    entries.append(entry)
                    self._seen_audit_keys.add((guild.id, entry.id))
            except (discord.Forbidden, discord.HTTPException):
                continue

        entries.sort(key=lambda entry: entry.created_at)
        if len(self._seen_audit_keys) > 5000:
            self._seen_audit_keys = set(
                list(self._seen_audit_keys)[-2500:]
            )
        return entries

    async def process_audit_entry(
        self,
        guild: discord.Guild,
        entry: discord.AuditLogEntry,
    ) -> None:
        action_name = SECURITY_ACTIONS.get(entry.action)
        if action_name is None:
            return

        actor = entry.user
        if actor is None:
            return

        if actor.bot:
            return

        if await self.is_owner_user(actor):
            return

        if entry.target is not None and await self.is_owner_user(entry.target):
            # Owner üzerinde yıkıcı işlem yapıldıysa en yüksek öncelik.
            action_name = f"owner_{action_name}"

        pending = PendingAction(
            guild_id=guild.id,
            action=action_name,
            actor_id=actor.id,
            target_id=(
                entry.target.id
                if entry.target is not None
                else None
            ),
            created_at=time.time(),
            reason="Discord Audit Log unauthorized/destructive action",
            destructive=True,
        )

        self._pending[str(entry.id)] = pending

        await self.send_owner_alert(
            guild,
            pending,
            entry,
        )

        # Kritik geri dönüşler audit işleminden sonra otomatik yapılır.
        try:
            if action_name in {"ban", "owner_ban"}:
                await self.handle_unauthorized_ban(
                    guild,
                    pending,
                )
            elif action_name in {"channel_delete", "owner_channel_delete"}:
                await self.restore_from_latest(guild)
            elif action_name in {"role_delete", "owner_role_delete"}:
                await self.restore_from_latest(guild)
            elif action_name in {"emoji_delete", "owner_emoji_delete"}:
                await self.restore_from_latest(guild)
            elif action_name in {"sticker_delete", "owner_sticker_delete"}:
                await self.restore_from_latest(guild)
            elif action_name in {"webhook_delete", "owner_webhook_delete"}:
                await self.restore_from_latest(guild)
            elif action_name in {"kick", "owner_kick"}:
                await self.handle_unauthorized_kick(
                    guild,
                    pending,
                )
            elif action_name in {
                "role_update",
                "channel_update",
                "guild_update",
            }:
                # Son snapshot ile güvenli geri alma.
                await self.restore_from_latest(guild)
        except Exception:
            self.logger.exception(
                "Security recovery failed for audit entry %s",
                entry.id,
            )

        # Yetkisiz aktörün yönetilebilir rollerinden KICK/BAN kaldırılır.
        member = guild.get_member(actor.id)
        if member is not None:
            await self.revoke_dangerous_permissions(member)

    async def revoke_dangerous_permissions(
        self,
        member: discord.Member,
    ) -> int:
        guild = member.guild
        bot_member = guild.me
        if bot_member is None:
            return 0

        changed = 0
        for role in member.roles:
            if role.is_default() or role.managed:
                continue
            if role >= bot_member.top_role:
                continue

            permissions = role.permissions
            before = permissions.value
            permissions.kick_members = False
            permissions.ban_members = False

            if permissions.value == before:
                continue

            try:
                await role.edit(
                    permissions=permissions,
                    reason="PAG Security: unauthorized destructive action",
                )
                changed += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

        return changed

    async def handle_unauthorized_ban(
        self,
        guild: discord.Guild,
        pending: PendingAction,
    ) -> None:
        target_id = pending.target_id
        if target_id is None:
            return

        try:
            await guild.unban(
                discord.Object(id=target_id),
                reason="PAG Security: unauthorized ban rollback",
            )
        except discord.NotFound:
            return
        except (discord.Forbidden, discord.HTTPException):
            self.logger.exception(
                "Unable to unban unauthorized target %s",
                target_id,
            )
            return

    async def handle_unauthorized_kick(
        self,
        guild: discord.Guild,
        pending: PendingAction,
    ) -> None:
        target_id = pending.target_id
        if target_id is None:
            return

        # Kicked user bot tarafından tek taraflı olarak sunucuya eklenemez.
        # Bunun yerine anında geri dönüş daveti oluşturulur ve hedefe DM denenir.
        invite = None
        try:
            channel = (
                guild.system_channel
                or next(
                    iter(guild.text_channels),
                    None,
                )
            )
            if channel is not None:
                invite = await channel.create_invite(
                    max_age=3600,
                    max_uses=1,
                    unique=True,
                    reason="PAG unauthorized kick recovery",
                )
        except (discord.Forbidden, discord.HTTPException):
            pass

        if invite is None:
            return

        try:
            user = guild.get_member(target_id)
            if user is None:
                user = await self.bot.fetch_user(target_id)
            await user.send(
                "PAG güvenlik sistemi hesabınız için bir kick işlemi algıladı. "
                f"Geri dönüş daveti: {invite.url}"
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def send_owner_alert(
        self,
        guild: discord.Guild,
        pending: PendingAction,
        entry: discord.AuditLogEntry,
    ) -> None:
        owner = await self.get_owner_member(guild)
        if owner is None:
            # Owner kullanıcı adı ile sunucu üyesi bulunamazsa Discord'un gerçek
            # owner hesabına DM denemesi yapılır; isim filtresi yine aşağıdaki
            # interaction güvenliğini belirler.
            try:
                owner_user = await self.bot.fetch_user(guild.owner_id)
            except discord.HTTPException:
                return
        else:
            owner_user = owner

        target = (
            f"<@{pending.target_id}>"
            if pending.target_id
            else "Bilinmiyor"
        )
        actor = f"<@{pending.actor_id}>"

        embed = discord.Embed(
            title="🛡️ PAG SECURITY — Yıkıcı İşlem Algılandı",
            description=(
                "Aşağıdaki işlem Discord Audit Log üzerinden tespit edildi.\n\n"
                "**Önemli:** Kick işlemi Discord tarafından zaten uygulanmış olabilir. "
                "Botun gerçek önleme katmanı, KICK/BAN yetkilerini rollerde kilitlemektir."
            ),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="İşlem", value=pending.action, inline=True)
        embed.add_field(name="Aktör", value=actor, inline=True)
        embed.add_field(name="Hedef", value=target, inline=True)
        embed.add_field(
            name="Audit Reason",
            value=entry.reason or "Belirtilmemiş",
            inline=False,
        )
        embed.add_field(
            name="Geri Dönüş",
            value=(
                "Ban ise otomatik unban denenir.\n"
                "Kick ise geri dönüş daveti denenir.\n"
                "Kanal/rol silinmesi ise son backup'tan restore denenir."
            ),
            inline=False,
        )

        try:
            await owner_user.send(
                embed=embed,
                view=ApprovalView(self, pending),
            )
        except (discord.Forbidden, discord.HTTPException):
            self.logger.warning(
                "Could not DM owner for security alert in %s",
                guild.name,
            )

    async def handle_approval(
        self,
        pending: PendingAction,
        *,
        approved: bool,
    ) -> str:
        if not approved:
            return (
                "✅ İşlem reddedildi. Güvenlik politikası korunuyor; "
                "ilgili aktörün yönetilebilir KICK/BAN yetkileri kilitlendi."
            )

        # Approval, gelecekte manuel secure-kick gibi akışlarda kullanılabilir.
        # Audit log tabanlı olay için işlem Discord tarafında zaten gerçekleşmiştir.
        return (
            "⚠️ İşlem onaylandı. Bu panel audit-log olayından sonra açıldığı için "
            "geri alma otomatik sistemi tekrar çalıştırılmadı."
        )

    async def restore_from_latest(
        self,
        guild: discord.Guild,
    ) -> dict[str, Any] | None:
        path = self._last_snapshot.get(guild.id)
        if path is None or not path.exists():
            try:
                path = await self.resolve_backup(guild, "latest")
            except FileNotFoundError:
                return None

        try:
            valid, reason = await self.verify_backup_file(path)
            if not valid:
                self.logger.error(
                    "Latest backup invalid for %s: %s",
                    guild.name,
                    reason,
                )
                return None

            snapshot = await self.read_backup_file(path)
            return await self.restore_backup(
                guild,
                snapshot,
                restore_messages=True,
                restore_database=True,
            )
        except Exception:
            self.logger.exception(
                "Restore from latest failed for %s",
                guild.name,
            )
            return None

    # ========================================================
    # BACKUP COMMANDS
    # ========================================================

    @commands.hybrid_group(
        name="backup",
        description="PAG disaster recovery / backup yönetimi.",
        invoke_without_command=True,
    )
    async def backup(self, ctx: commands.Context) -> None:
        if not await self.require_owner(ctx):
            return
        await ctx.reply(
            "`backup create`, `backup list`, `backup restore`, `backup verify`, `backup messages` kullan.",
            mention_author=False,
        )

    @backup.command(
        name="create",
        description="Tam PAG sunucu snapshot'ı oluşturur.",
    )
    @app_commands.describe(
        all_messages="Tüm text kanallarından mesaj geçmişi snapshotlansın mı?",
    )
    async def backup_create(
        self,
        ctx: commands.Context,
        all_messages: bool = False,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        await ctx.defer()
        try:
            backup_id, path, snapshot = await self.create_backup(
                ctx.guild,
                include_all_messages=all_messages,
            )

            embed = discord.Embed(
                title="💾 PAG Full Snapshot Oluşturuldu",
                description=(
                    f"Backup ID: `{backup_id}`\n"
                    f"Boyut: `{path.stat().st_size:,} bytes`\n"
                    f"Mesaj limiti: `{MESSAGE_BACKUP_LIMIT}`\n"
                    f"Tam mesaj snapshot: `{'Evet' if all_messages else 'Hayır'}`"
                ),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="Kapsam",
                value=(
                    "Sunucu ayarları • Roller • Kanallar • Overwrite'lar • "
                    "Emoji/Sticker meta • Webhook konfigürasyonu • "
                    "Önemli kanal mesajları • SQLite guild verileri"
                ),
                inline=False,
            )
            embed.set_footer(text="PAG Disaster Recovery")
            await ctx.send(embed=embed)
        except Exception as exc:
            self.logger.exception("Manual backup failed.")
            await ctx.send(
                f"❌ Backup oluşturulamadı: `{exc}`",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @backup.command(
        name="list",
        description="Sunucunun mevcut backup'larını listeler.",
    )
    async def backup_list(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        files = await self.list_backups(ctx.guild)
        if not files:
            await ctx.reply("Bu sunucu için backup bulunamadı.", mention_author=False)
            return

        lines = []
        for index, path in enumerate(files[:15], start=1):
            valid, reason = await self.verify_backup_file(path)
            size = path.stat().st_size
            lines.append(
                f"`{index:02}` • `{path.stem}` • `{size:,} B` • "
                f"{'✅' if valid else '❌'} {reason}"
            )

        embed = discord.Embed(
            title="💾 PAG Backup Arşivi",
            description="\n".join(lines),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(
            text=f"Retention: {BACKUP_RETENTION}"
        )
        await ctx.send(embed=embed)

    @backup.command(
        name="restore",
        description="Bir snapshot'ı geri yükler.",
    )
    @app_commands.describe(
        identifier="Backup ID veya latest",
        messages="Mesaj snapshotlarını da geri yükle.",
        database="PAG SQLite ayarlarını geri yükle.",
    )
    async def backup_restore(
        self,
        ctx: commands.Context,
        identifier: str = "latest",
        messages: bool = True,
        database: bool = True,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        await ctx.defer()
        try:
            path = await self.resolve_backup(
                ctx.guild,
                identifier,
            )
            valid, reason = await self.verify_backup_file(path)
            if not valid:
                await ctx.send(
                    f"❌ Restore durduruldu: `{reason}`"
                )
                return

            snapshot = await self.read_backup_file(path)
            report = await self.restore_backup(
                ctx.guild,
                snapshot,
                restore_messages=messages,
                restore_database=database,
            )

            embed = discord.Embed(
                title="♻️ PAG Disaster Recovery Tamamlandı",
                description=(
                    f"Kaynak: `{path.stem}`\n"
                    f"Mesaj restore: `{'Evet' if messages else 'Hayır'}`\n"
                    f"DB restore: `{'Evet' if database else 'Hayır'}`"
                ),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="Sonuç",
                value=(
                    f"Roller: `{report['roles_created']} yeni / {report['roles_updated']} güncellendi`\n"
                    f"Kanallar: `{report['channels_created']} yeni / {report['channels_updated']} güncellendi`\n"
                    f"Mesajlar: `{report['messages_restored']}`\n"
                    f"Emoji: `{report['emojis_created']}`\n"
                    f"Webhook: `{report['webhooks_created']}`\n"
                    f"DB tabloları: `{len(report['database_tables'])}`\n"
                    f"Hatalar: `{len(report['errors'])}`"
                ),
                inline=False,
            )
            if report["errors"]:
                embed.add_field(
                    name="İlk Hatalar",
                    value="\n".join(
                        str(error)[:250]
                        for error in report["errors"][:5]
                    ),
                    inline=False,
                )
            await ctx.send(embed=embed)
        except Exception as exc:
            self.logger.exception("Backup restore failed.")
            await ctx.send(
                f"❌ Restore başarısız: `{exc}`",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @backup.command(
        name="verify",
        description="Backup SHA-256 bütünlüğünü doğrular.",
    )
    async def backup_verify(
        self,
        ctx: commands.Context,
        identifier: str = "latest",
    ) -> None:
        if not await self.require_owner(ctx):
            return

        try:
            path = await self.resolve_backup(
                ctx.guild,
                identifier,
            )
            valid, reason = await self.verify_backup_file(path)
            await ctx.reply(
                f"{'✅' if valid else '❌'} `{path.stem}` — {reason}",
                mention_author=False,
            )
        except Exception as exc:
            await ctx.reply(
                f"❌ `{exc}`",
                mention_author=False,
            )

    @backup.command(
        name="messages",
        description="Tüm önemli kanalları mesaj geçmişiyle snapshotlar.",
    )
    @app_commands.describe(
        limit="Kanal başına mesaj sayısı, maksimum 500.",
    )
    async def backup_messages(
        self,
        ctx: commands.Context,
        limit: int = MESSAGE_BACKUP_LIMIT,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        limit = max(0, min(500, limit))
        await ctx.defer()

        old_limit = MESSAGE_BACKUP_LIMIT
        # Global sabiti değiştirmeden özel snapshot üretmek için doğrudan
        # serialize_guild sonrası message bölümlerini yeniden dolduruyoruz.
        snapshot = await self.serialize_guild(
            ctx.guild,
            include_all_messages=False,
        )

        count = 0
        for channel_data in snapshot.get("channels", []):
            channel = ctx.guild.get_channel(
                safe_int(channel_data.get("id"))
            )
            if not isinstance(channel, discord.TextChannel):
                continue
            if not self.is_important_channel(channel):
                continue
            channel_data["messages"] = await self.serialize_messages(
                channel,
                limit,
            )
            count += len(channel_data["messages"])

        backup_id = self.make_backup_id(ctx.guild) + "_messages"
        path = await self.write_backup_file(
            ctx.guild,
            snapshot,
            backup_id,
        )

        await ctx.send(
            f"✅ Message snapshot oluşturuldu: `{backup_id}` • `{count}` mesaj • `{path.name}`"
        )
        _ = old_limit

    # ========================================================
    # SECURITY COMMANDS
    # ========================================================

    @commands.hybrid_group(
        name="security",
        description="PAG security / anti-nuke kontrolü.",
        invoke_without_command=True,
    )
    async def security(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return
        await ctx.reply(
            "`security status`, `security protect`, `security lockdown`, `security unlock`, `security safe-kick` kullan.",
            mention_author=False,
        )

    @security.command(
        name="status",
        description="PAG Security durumunu gösterir.",
    )
    async def security_status(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        last = self._last_snapshot.get(ctx.guild.id)
        files = await self.list_backups(ctx.guild)
        protected_roles = 0
        owner = await self.get_owner_member(ctx.guild)

        if ctx.guild.me is not None:
            protected_roles = sum(
                1
                for role in ctx.guild.roles
                if not role.is_default()
                and not role.managed
                and not role.permissions.kick_members
                and not role.permissions.ban_members
            )

        embed = discord.Embed(
            title="🛡️ PAG Security Status",
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Owner Lock",
            value=(
                f"✅ `{OWNER_USERNAME}` bulundu"
                if owner is not None
                else f"⚠️ `{OWNER_USERNAME}` sunucuda bulunamadı"
            ),
            inline=False,
        )
        embed.add_field(
            name="Rol Hardening",
            value=f"`{protected_roles}` yönetilebilir rol KICK/BAN kilidine uygun",
            inline=True,
        )
        embed.add_field(
            name="Backup",
            value=f"`{len(files)}` snapshot\nSon: `{last.name if last else 'yok'}`",
            inline=True,
        )
        embed.add_field(
            name="Audit Guard",
            value="✅ Aktif",
            inline=True,
        )
        embed.add_field(
            name="Sınır",
            value=(
                "Sunucu sahibi ve Administrator yetkisi Discord seviyesinde bot tarafından "
                "tam anlamıyla önlenemez. KICK/BAN rol izinleri ise otomatik kilitlenir."
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @security.command(
        name="protect",
        description="Yönetilebilir tüm rollerde KICK/BAN izinlerini kilitler.",
    )
    async def security_protect(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        await ctx.defer()
        changed = await self.protect_roles(ctx.guild)
        await self.protect_owner(ctx.guild)
        await ctx.send(
            f"🛡️ Velgrath Lock uygulandı. `{changed}` rol güncellendi."
        )

    @security.command(
        name="lockdown",
        description="Güvenlik kilidi + anlık backup çalıştırır.",
    )
    async def security_lockdown(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        await ctx.defer()
        changed = await self.run_lockdown(ctx.guild)
        await ctx.send(
            f"🔒 PANIC/LOCKDOWN tamamlandı. `{changed}` rol KICK/BAN izinlerinden arındırıldı ve güncel backup alındı."
        )

    @security.command(
        name="unlock",
        description="Otomatik hardening'i kaldırmaz; bilgi amaçlı güvenlik durumunu gösterir.",
    )
    async def security_unlock(
        self,
        ctx: commands.Context,
    ) -> None:
        if not await self.require_owner(ctx):
            return

        await ctx.reply(
            "ℹ️ Güvenlik kilidi geriye izin eklemek üzere tasarlanmadı. "
            "KICK/BAN izinleri backup'tan ancak açıkça restore edilirse geri gelir.",
            mention_author=False,
        )

    @security.command(
        name="safe-kick",
        description="Velgrath onayı sonrası bot üzerinden kick işlemi başlatır.",
    )
    @app_commands.describe(
        member="Atılacak üye",
        reason="Kick sebebi",
    )
    async def security_safe_kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        reason: str = "PAG security approved kick",
    ) -> None:
        if not await self.require_owner(ctx):
            return

        if await self.is_owner_user(member):
            await ctx.reply(
                "⛔ Velgrath hesabı güvenlik sistemi tarafından kicklenemez.",
                mention_author=False,
            )
            return

        me = ctx.guild.me
        if me is None or not me.guild_permissions.kick_members:
            await ctx.reply(
                "❌ Botta Kick Members yetkisi yok.",
                mention_author=False,
            )
            return

        if member.top_role >= me.top_role:
            await ctx.reply(
                "❌ Bot bu üyeyi kickleyemiyor; üyenin en yüksek rolü botun rolüne eşit/yukarıda.",
                mention_author=False,
            )
            return

        pending = PendingAction(
            guild_id=ctx.guild.id,
            action="approved_kick",
            actor_id=ctx.author.id,
            target_id=member.id,
            created_at=time.time(),
            reason=reason,
            destructive=False,
        )

        embed = discord.Embed(
            title="⚠️ Kick Onayı",
            description=(
                f"Hedef: {member.mention}\n"
                f"Sebep: `{reason[:500]}`\n\n"
                "Onaylarsan bot kick işlemini uygular."
            ),
        )

        await ctx.send(
            embed=embed,
            view=ApprovalView(self, pending),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ========================================================
    # OWNER APPROVAL EXECUTION
    # ========================================================

    async def perform_approved_action(
        self,
        pending: PendingAction,
    ) -> str:
        guild = self.bot.get_guild(pending.guild_id)
        if guild is None:
            return "❌ Sunucu artık erişilebilir değil."

        if pending.action == "approved_kick":
            member = guild.get_member(safe_int(pending.target_id))
            if member is None:
                return "❌ Üye artık sunucuda değil."
            if await self.is_owner_user(member):
                return "⛔ Velgrath hesabı korunuyor."

            me = guild.me
            if me is None or not me.guild_permissions.kick_members:
                return "❌ Botta Kick Members yok."
            if member.top_role >= me.top_role:
                return "❌ Üyenin rolü botun rolünden yüksek/eşit."

            try:
                await member.kick(
                    reason=pending.reason,
                )
                return f"✅ {member} onaylı olarak kicklendi."
            except discord.HTTPException as exc:
                return f"❌ Kick başarısız: {exc}"

        return "ℹ️ Bu audit-log işlemi zaten gerçekleşti; panel yalnızca kayıt/onay amacıyla gösterildi."

    # Override handle_approval to execute secure-kick.
    # Python method replacement is intentionally explicit here to keep the
    # interaction code centralized.
    async def _handle_approval_dispatch(
        self,
        pending: PendingAction,
        approved: bool,
    ) -> str:
        if pending.action == "approved_kick":
            if not approved:
                return "✅ Kick reddedildi; işlem yapılmadı."
            return await self.perform_approved_action(pending)
        return await self.handle_approval(
            pending,
            approved=approved,
        )

    # ========================================================
    # LOOPS
    # ========================================================

    @tasks.loop(seconds=AUDIT_POLL_SECONDS)
    async def audit_guard_loop(self) -> None:
        if not self.bot.is_ready():
            return

        for guild in list(self.bot.guilds):
            try:
                entries = await self.find_recent_actions(guild)
                for entry in entries:
                    await self.process_audit_entry(
                        guild,
                        entry,
                    )
            except (discord.Forbidden, discord.HTTPException):
                continue
            except Exception:
                self.logger.exception(
                    "Audit guard failure in guild %s",
                    guild.id,
                )

    @audit_guard_loop.before_loop
    async def before_audit_guard_loop(self) -> None:
        await self.bot.wait_until_ready()
        self._startup_complete = True

        # İlk anda role hardening ve baseline backup.
        for guild in list(self.bot.guilds):
            try:
                await self.protect_roles(guild)
                await self.protect_owner(guild)
            except Exception:
                self.logger.exception(
                    "Initial security hardening failed for %s",
                    guild.name,
                )

    @tasks.loop(minutes=AUTO_BACKUP_MINUTES)
    async def auto_backup_loop(self) -> None:
        if not self.bot.is_ready():
            return

        for guild in list(self.bot.guilds):
            try:
                await self.create_backup(
                    guild,
                    include_all_messages=False,
                )
            except Exception:
                self.logger.exception(
                    "Automatic backup failed for %s",
                    guild.name,
                )

    @auto_backup_loop.before_loop
    async def before_auto_backup_loop(self) -> None:
        await self.bot.wait_until_ready()
        # Bağlantı tamamlandığında security baseline alınır.
        await asyncio.sleep(3)
        for guild in list(self.bot.guilds):
            try:
                if guild.id not in self._last_snapshot:
                    _, path, _ = await self.create_backup(
                        guild,
                        include_all_messages=False,
                    )
                    self._last_snapshot[guild.id] = path
            except Exception:
                self.logger.exception(
                    "Initial backup failed for %s",
                    guild.name,
                )

    # ========================================================
    # EVENT LISTENERS
    # ========================================================

    @commands.Cog.listener("on_guild_join")
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await self.protect_roles(guild)
            await self.protect_owner(guild)
            await self.create_backup(guild)
        except Exception:
            self.logger.exception(
                "Security setup failed after guild join: %s",
                guild.name,
            )

    @commands.Cog.listener("on_guild_remove")
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self.logger.warning(
            "Bot removed from guild %s (%s). Local backups remain on disk.",
            guild.name,
            guild.id,
        )

    @commands.Cog.listener("on_member_remove")
    async def on_member_remove(self, member: discord.Member) -> None:
        if await self.is_owner_user(member):
            self.logger.critical(
                "Owner %s left/was removed from guild %s. "
                "Discord cannot be force-rejoined by a bot.",
                member,
                member.guild.name,
            )

    @commands.Cog.listener("on_role_delete")
    async def on_role_delete(self, role: discord.Role) -> None:
        if not self.bot.is_ready():
            return
        try:
            await self.restore_from_latest(role.guild)
        except Exception:
            self.logger.exception(
                "Immediate role restore failed: %s",
                role.name,
            )

    @commands.Cog.listener("on_guild_channel_delete")
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        if not self.bot.is_ready():
            return
        try:
            await self.restore_from_latest(channel.guild)
        except Exception:
            self.logger.exception(
                "Immediate channel restore failed: %s",
                channel.name,
            )

    # ========================================================
    # HELP / ERROR
    # ========================================================

    @commands.Cog.listener("on_command_error")
    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if not isinstance(error, commands.CommandNotFound):
            return

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    cog = SecurityBackup(bot)
    await bot.add_cog(cog)

    # Mevcut moderation kick/ban sistemlerinin üzerine tam yetki kilidi
    # koymak için botun global prefix check'ine güvenmiyoruz. Bu Cog'un
    # protect_roles katmanı asıl enforcement'tır.

    logging.getLogger("PAG.SecurityBackup").info(
        "SecurityBackup cog registered."
    )
