from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)


# ============================================================
# ENUMS
# ============================================================


class BlacklistAction(str, Enum):
    """
    Blacklist işlem türleri.
    """

    ADD = "add"
    REMOVE = "remove"


class BlacklistResult(str, Enum):
    """
    İşlem sonucunu standartlaştırır.
    """

    SUCCESS = "success"
    ALREADY_ACTIVE = "already_active"
    NOT_FOUND = "not_found"
    INVALID_TARGET = "invalid_target"
    API_ERROR = "api_error"
    DATABASE_ERROR = "database_error"
    DISCORD_ERROR = "discord_error"
    UNKNOWN_ERROR = "unknown_error"


# ============================================================
# DATA MODELS
# ============================================================


@dataclass(slots=True)
class BlacklistTarget:
    """
    Blacklist hedefinin çözülmüş hâli.

    Aynı anda Discord ve Roblox bilgilerini
    taşıyabilir.
    """

    discord_member: discord.Member | None = None

    discord_id: int | None = None

    roblox_id: int | None = None

    roblox_username: str | None = None

    roblox_display_name: str | None = None

    avatar_url: str | None = None


@dataclass(slots=True)
class BlacklistOperation:
    """
    Blacklist işlem sonucu.
    """

    result: BlacklistResult

    target: BlacklistTarget | None = None

    record: Any | None = None

    message: str | None = None


# ============================================================
# BLACKLIST COG
# ============================================================


class Blacklist(commands.Cog):
    """
    PAG Blacklist sistemi.

    Komutlar:

        /blacklist
        /unblacklist

    Hedefler:

        Discord Member
        Roblox Username

    Sistem:

        Target Resolution
            ↓
        Roblox Resolution
            ↓
        Existing Record Check
            ↓
        Database Operation
            ↓
        Result Handling
            ↓
        Embed Response
    """

    TABLE_NAME = "blacklist"

    MAX_REASON_LENGTH = 1000

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.logger: logging.Logger = (
            bot.logger
        )

        self.database = (
            bot.database
        )

        self.roblox_service: RobloxService = (
            bot.roblox_service
        )

        self._lock = asyncio.Lock()

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(
        self,
    ) -> None:
        """
        Blacklist database altyapısını hazırlar.
        """

        await self._initialize_database()

        self.logger.info(
            "Blacklist system initialized.",
        )

    # ========================================================
    # DATABASE INITIALIZATION
    # ========================================================

    async def _initialize_database(
        self,
    ) -> None:
        """
        Blacklist tablolarını ve indexleri oluşturur.
        """

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                discord_id INTEGER UNIQUE,

                roblox_id INTEGER UNIQUE,

                roblox_username TEXT,

                reason TEXT NOT NULL,

                added_by INTEGER NOT NULL,

                created_at TEXT NOT NULL,

                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_blacklist_active
            ON blacklist(active)
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_blacklist_discord
            ON blacklist(discord_id)
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_blacklist_roblox
            ON blacklist(roblox_id)
            """
        )

    # ========================================================
    # INPUT VALIDATION
    # ========================================================

    def _validate_target_input(
        self,
        *,
        user: discord.Member | None,
        username: str | None,
    ) -> tuple[bool, str | None]:
        """
        Kullanıcı hedef girişini doğrular.

        Gelecekte başka hedef türleri
        buraya eklenebilir.
        """

        if user is None and not username:

            return (
                False,
                (
                    "❌ En az bir hedef belirtmelisin.\n\n"
                    "Discord kullanıcısı veya Roblox "
                    "kullanıcı adı girebilirsin."
                ),
            )

        if username:

            username = username.strip()

            if len(username) < 3:

                return (
                    False,
                    (
                        "❌ Roblox kullanıcı adı "
                        "çok kısa."
                    ),
                )

            if len(username) > 20:

                return (
                    False,
                    (
                        "❌ Roblox kullanıcı adı "
                        "çok uzun."
                    ),
                )

        return (
            True,
            None,
        )

    # ========================================================
    # TARGET RESOLUTION
    # ========================================================

    async def resolve_target(
        self,
        *,
        user: discord.Member | None,
        username: str | None,
    ) -> BlacklistTarget:
        """
        Discord ve Roblox hedefini çözer.

        Senaryolar:

        1. Sadece Discord
        2. Sadece Roblox
        3. İkisi birlikte
        4. Roblox API hatası
        5. Roblox kullanıcı bulunamaması
        """

        target = BlacklistTarget()

        # ----------------------------------------------------
        # DISCORD
        # ----------------------------------------------------

        if user is not None:

            target.discord_member = user

            target.discord_id = user.id

        # ----------------------------------------------------
        # ROBLOX
        # ----------------------------------------------------

        if username:

            normalized_username = (
                username.strip()
            )

            roblox_user = (
                await self.resolve_roblox_user(
                    normalized_username,
                )
            )

            target.roblox_id = (
                roblox_user.id
            )

            target.roblox_username = (
                roblox_user.name
            )

            target.roblox_display_name = (
                roblox_user.display_name
            )

            await self.try_resolve_avatar(
                target,
            )

        return target

    # ========================================================
    # ROBLOX RESOLUTION
    # ========================================================

    async def resolve_roblox_user(
        self,
        username: str,
    ) -> Any:
        """
        Roblox kullanıcı adını çözer.

        Hatalar üst katmana kontrollü şekilde
        aktarılır.
        """

        try:

            return (
                await self.roblox_service
                .get_user_by_username(
                    username,
                )
            )

        except RobloxNotFoundError:

            self.logger.info(
                "Roblox user not found: %s",
                username,
            )

            raise

        except RobloxAPIError:

            self.logger.exception(
                "Roblox API error while resolving: %s",
                username,
            )

            raise

        except Exception:

            self.logger.exception(
                "Unexpected Roblox resolution error.",
            )

            raise

    # ========================================================
    # AVATAR
    # ========================================================

    async def try_resolve_avatar(
        self,
        target: BlacklistTarget,
    ) -> None:
        """
        Avatarı almaya çalışır.

        Avatar alınamazsa blacklist işlemi
        başarısız olmaz.
        """

        if target.roblox_id is None:

            return

        try:

            avatar = (
                await self.roblox_service
                .get_avatar(
                    target.roblox_id,
                )
            )

            target.avatar_url = (
                avatar.image_url
            )

        except Exception:

            self.logger.warning(
                (
                    "Could not resolve avatar "
                    "for Roblox ID %s."
                ),
                target.roblox_id,
                exc_info=True,
            )

    # ========================================================
    # DATABASE SEARCH
    # ========================================================

    async def find_record(
        self,
        target: BlacklistTarget,
        *,
        active_only: bool = False,
    ) -> Any | None:
        """
        Hedefe ait blacklist kaydını bulur.

        Arama sırası:

            Discord ID
                ↓
            Roblox ID
        """

        conditions: list[str] = []

        parameters: list[Any] = []

        if target.discord_id is not None:

            conditions.append(
                "discord_id = ?"
            )

            parameters.append(
                target.discord_id
            )

        if target.roblox_id is not None:

            conditions.append(
                "roblox_id = ?"
            )

            parameters.append(
                target.roblox_id
            )

        if not conditions:

            return None

        query = (
            "SELECT * FROM blacklist "
            "WHERE ("
            + " OR ".join(
                conditions
            )
            + ")"
        )

        if active_only:

            query += (
                " AND active = 1"
            )

        query += (
            " ORDER BY id DESC "
            "LIMIT 1"
        )

        return (
            await self.database.fetchone(
                query,
                tuple(parameters),
            )
        )

    # ========================================================
    # CONFLICT CHECK
    # ========================================================

    async def detect_target_conflict(
        self,
        target: BlacklistTarget,
    ) -> tuple[Any | None, Any | None]:
        """
        Discord ve Roblox hedeflerinin
        farklı blacklist kayıtlarına bağlı olup
        olmadığını kontrol eder.

        Örnek:

        Discord A → Record 1
        Roblox B  → Record 2

        Bu durumda sistem sessizce yanlış
        birleştirme yapmaz.
        """

        discord_record = None

        roblox_record = None

        if target.discord_id is not None:

            discord_record = (
                await self.database.fetchone(
                    """
                    SELECT *
                    FROM blacklist
                    WHERE discord_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        target.discord_id,
                    ),
                )
            )

        if target.roblox_id is not None:

            roblox_record = (
                await self.database.fetchone(
                    """
                    SELECT *
                    FROM blacklist
                    WHERE roblox_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        target.roblox_id,
                    ),
                )
            )

        return (
            discord_record,
            roblox_record,
        )

    # ========================================================
    # CONFLICT VALIDATION
    # ========================================================

    def validate_records(
        self,
        discord_record: Any | None,
        roblox_record: Any | None,
    ) -> None:
        """
        İki farklı aktif kaydın çakışmasını
        kontrol eder.
        """

        if (
            discord_record is None
            or roblox_record is None
        ):

            return

        discord_id = (
            discord_record["id"]
        )

        roblox_id = (
            roblox_record["id"]
        )

        if discord_id != roblox_id:

            raise ValueError(
                (
                    "Discord and Roblox targets "
                    "belong to different blacklist "
                    "records."
                )
            )

    # ========================================================
    # NORMALIZE REASON
    # ========================================================

    def normalize_reason(
        self,
        reason: str | None,
    ) -> str:
        """
        Sebebi normalize eder.
        """

        if not reason:

            return (
                "Sebep belirtilmedi."
            )

        normalized = (
            reason.strip()
        )

        if not normalized:

            return (
                "Sebep belirtilmedi."
            )

        return (
            normalized[
                :self.MAX_REASON_LENGTH
            ]
        )

    # ========================================================
    # CREATE / UPDATE RECORD
    # ========================================================

    async def save_blacklist_record(
        self,
        *,
        target: BlacklistTarget,
        reason: str,
        added_by: int,
        existing: Any | None,
    ) -> None:
        """
        Yeni blacklist kaydı oluşturur veya
        eski kaydı aktif hâle getirir.
        """

        now = (
            datetime.now(
                timezone.utc,
            ).isoformat()
        )

        if existing is not None:

            await self.database.execute(
                """
                UPDATE blacklist
                SET
                    discord_id = ?,
                    roblox_id = ?,
                    roblox_username = ?,
                    reason = ?,
                    added_by = ?,
                    created_at = ?,
                    active = 1
                WHERE id = ?
                """,
                (
                    target.discord_id,
                    target.roblox_id,
                    target.roblox_username,
                    reason,
                    added_by,
                    now,
                    existing["id"],
                ),
            )

            return

        await self.database.execute(
            """
            INSERT INTO blacklist (
                discord_id,
                roblox_id,
                roblox_username,
                reason,
                added_by,
                created_at,
                active
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                target.discord_id,
                target.roblox_id,
                target.roblox_username,
                reason,
                added_by,
                now,
            ),
        )

    # ========================================================
    # DEACTIVATE RECORD
    # ========================================================

    async def deactivate_record(
        self,
        record: Any,
    ) -> None:
        """
        Blacklist kaydını pasifleştirir.

        Kayıt silinmez.

        Böylece geçmiş kayıtları korunur.
        """

        await self.database.execute(
            """
            UPDATE blacklist
            SET active = 0
            WHERE id = ?
            """,
            (
                record["id"],
            ),
        )

    # ========================================================
    # BLACKLIST EMBED
    # ========================================================

    def build_blacklist_embed(
        self,
        *,
        target: BlacklistTarget,
        reason: str,
        moderator: discord.Member,
        updated: bool,
    ) -> discord.Embed:
        """
        Blacklist başarı embed'i oluşturur.
        """

        title = (
            "⚠️ PAG BLACKLIST UPDATED"
            if updated
            else
            "⚠️ PAG BLACKLIST"
        )

        description = (
            "Kullanıcı blacklist kaydına "
            "eklendi."
            if not updated
            else
            "Mevcut blacklist kaydı güncellendi."
        )

        embed = discord.Embed(
            title=title,
            description=description,
            timestamp=discord.utils.utcnow(),
        )

        if target.discord_member is not None:

            embed.add_field(
                name="Discord User",
                value=(
                    f"{target.discord_member.mention}\n"
                    f"`{target.discord_id}`"
                ),
                inline=True,
            )

        elif target.discord_id is not None:

            embed.add_field(
                name="Discord User",
                value=(
                    f"<@{target.discord_id}>\n"
                    f"`{target.discord_id}`"
                ),
                inline=True,
            )

        if target.roblox_username is not None:

            embed.add_field(
                name="Roblox User",
                value=(
                    f"**{target.roblox_username}**\n"
                    f"`{target.roblox_id}`"
                ),
                inline=True,
            )

        embed.add_field(
            name="Reason",
            value=reason[:1024],
            inline=False,
        )

        embed.add_field(
            name="Added By",
            value=moderator.mention,
            inline=True,
        )

        embed.add_field(
            name="Status",
            value="🔴 **BLACKLISTED**",
            inline=True,
        )

        if target.avatar_url:

            embed.set_thumbnail(
                url=target.avatar_url,
            )

        return embed

    # ========================================================
    # UNBLACKLIST EMBED
    # ========================================================

    def build_unblacklist_embed(
        self,
        *,
        record: Any,
        moderator: discord.Member,
    ) -> discord.Embed:
        """
        Unblacklist başarı embed'i oluşturur.
        """

        embed = discord.Embed(
            title="✅ PAG UNBLACKLIST",
            description=(
                "Kullanıcının aktif blacklist "
                "kaydı kaldırıldı."
            ),
            timestamp=discord.utils.utcnow(),
        )

        if record["discord_id"]:

            embed.add_field(
                name="Discord User",
                value=(
                    f"<@{record['discord_id']}>"
                ),
                inline=True,
            )

        if record["roblox_username"]:

            embed.add_field(
                name="Roblox User",
                value=(
                    f"**{record['roblox_username']}**"
                ),
                inline=True,
            )

        embed.add_field(
            name="Previous Reason",
            value=(
                str(
                    record["reason"]
                )[:1024]
            ),
            inline=False,
        )

        embed.add_field(
            name="Removed By",
            value=moderator.mention,
            inline=True,
        )

        embed.add_field(
            name="Status",
            value="🟢 **UNBLACKLISTED**",
            inline=True,
        )

        return embed

    # ========================================================
    # SAFE RESPONSE
    # ========================================================

    async def safe_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> None:
        """
        Interaction'ın cevaplanıp cevaplanmadığını
        kontrol ederek güvenli cevap verir.
        """

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    content=content,
                    embed=embed,
                    ephemeral=True,
                )

            else:

                await interaction.response.send_message(
                    content=content,
                    embed=embed,
                    ephemeral=True,
                )

        except discord.NotFound:

            self.logger.warning(
                "Interaction expired.",
            )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to send interaction response.",
            )

    # ========================================================
    # BLACKLIST COMMAND
    # ========================================================

    @app_commands.command(
        name="blacklist",
        description=(
            "Bir kullanıcıyı PAG blacklistine ekler."
        ),
    )
    @app_commands.describe(
        user="Discord kullanıcısı.",
        username="Roblox kullanıcı adı.",
        reason="Blacklist sebebi.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def blacklist(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        username: str | None = None,
        reason: str = "Sebep belirtilmedi.",
    ) -> None:

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        valid, error_message = (
            self._validate_target_input(
                user=user,
                username=username,
            )
        )

        if not valid:

            await self.safe_response(
                interaction,
                content=error_message,
            )

            return

        # ----------------------------------------------------
        # DEFER
        # ----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True,
        )

        async with self._lock:

            try:

                normalized_reason = (
                    self.normalize_reason(
                        reason,
                    )
                )

                # --------------------------------------------
                # TARGET
                # --------------------------------------------

                target = (
                    await self.resolve_target(
                        user=user,
                        username=username,
                    )
                )

                # --------------------------------------------
                # CONFLICT CHECK
                # --------------------------------------------

                (
                    discord_record,
                    roblox_record,
                ) = (
                    await self.detect_target_conflict(
                        target,
                    )
                )

                self.validate_records(
                    discord_record,
                    roblox_record,
                )

                existing = (
                    discord_record
                    or roblox_record
                )

                was_active = (
                    existing is not None
                    and existing["active"] == 1
                )

                # --------------------------------------------
                # DATABASE
                # --------------------------------------------

                await self.save_blacklist_record(
                    target=target,
                    reason=normalized_reason,
                    added_by=interaction.user.id,
                    existing=existing,
                )

                # --------------------------------------------
                # EMBED
                # --------------------------------------------

                embed = (
                    self.build_blacklist_embed(
                        target=target,
                        reason=normalized_reason,
                        moderator=interaction.user,
                        updated=was_active,
                    )
                )

                await interaction.edit_original_response(
                    embed=embed,
                )

                self.logger.info(
                    (
                        "Blacklist operation completed. "
                        "discord_id=%s roblox_id=%s "
                        "moderator=%s updated=%s"
                    ),
                    target.discord_id,
                    target.roblox_id,
                    interaction.user.id,
                    was_active,
                )

            except RobloxNotFoundError:

                await interaction.edit_original_response(
                    content=(
                        "❌ Roblox kullanıcısı bulunamadı."
                    ),
                )

            except RobloxAPIError:

                await interaction.edit_original_response(
                    content=(
                        "❌ Roblox API şu anda "
                        "kullanılamıyor. Lütfen daha "
                        "sonra tekrar deneyin."
                    ),
                )

            except ValueError as error:

                self.logger.warning(
                    "Blacklist target conflict: %s",
                    error,
                )

                await interaction.edit_original_response(
                    content=(
                        "⚠️ Discord kullanıcısı ve "
                        "Roblox hesabı farklı blacklist "
                        "kayıtlarına bağlı görünüyor."
                    ),
                )

            except discord.HTTPException:

                self.logger.exception(
                    "Discord error during blacklist.",
                )

                await interaction.edit_original_response(
                    content=(
                        "❌ Discord işlemi başarısız oldu."
                    ),
                )

            except Exception:

                self.logger.exception(
                    "Unexpected blacklist error.",
                )

                await interaction.edit_original_response(
                    content=(
                        "❌ Blacklist işlemi sırasında "
                        "beklenmeyen bir hata oluştu."
                    ),
                )

    # ========================================================
    # UNBLACKLIST COMMAND
    # ========================================================

    @app_commands.command(
        name="unblacklist",
        description=(
            "Bir kullanıcıyı PAG blacklistinden çıkarır."
        ),
    )
    @app_commands.describe(
        user="Discord kullanıcısı.",
        username="Roblox kullanıcı adı.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def unblacklist(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        username: str | None = None,
    ) -> None:

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        valid, error_message = (
            self._validate_target_input(
                user=user,
                username=username,
            )
        )

        if not valid:

            await self.safe_response(
                interaction,
                content=error_message,
            )

            return

        # ----------------------------------------------------
        # DEFER
        # ----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True,
        )

        async with self._lock:

            try:

                # --------------------------------------------
                # RESOLVE
                # --------------------------------------------

                target = (
                    await self.resolve_target(
                        user=user,
                        username=username,
                    )
                )

                # --------------------------------------------
                # ACTIVE RECORD
                # --------------------------------------------

                record = (
                    await self.find_record(
                        target,
                        active_only=True,
                    )
                )

                if record is None:

                    await interaction.edit_original_response(
                        content=(
                            "ℹ️ Bu kullanıcı aktif "
                            "blacklistte bulunamadı."
                        ),
                    )

                    return

                # --------------------------------------------
                # DEACTIVATE
                # --------------------------------------------

                await self.deactivate_record(
                    record,
                )

                # --------------------------------------------
                # RESPONSE
                # --------------------------------------------

                embed = (
                    self.build_unblacklist_embed(
                        record=record,
                        moderator=interaction.user,
                    )
                )

                await interaction.edit_original_response(
                    embed=embed,
                )

                self.logger.info(
                    (
                        "Unblacklist completed. "
                        "record_id=%s moderator=%s"
                    ),
                    record["id"],
                    interaction.user.id,
                )

            except RobloxNotFoundError:

                await interaction.edit_original_response(
                    content=(
                        "❌ Roblox kullanıcısı bulunamadı."
                    ),
                )

            except RobloxAPIError:

                await interaction.edit_original_response(
                    content=(
                        "❌ Roblox API şu anda "
                        "kullanılamıyor."
                    ),
                )

            except discord.HTTPException:

                self.logger.exception(
                    "Discord error during unblacklist.",
                )

                await interaction.edit_original_response(
                    content=(
                        "❌ Discord işlemi başarısız oldu."
                    ),
                )

            except Exception:

                self.logger.exception(
                    "Unexpected unblacklist error.",
                )

                await interaction.edit_original_response(
                    content=(
                        "❌ Unblacklist işlemi sırasında "
                        "beklenmeyen bir hata oluştu."
                    ),
                )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Slash command hatalarını merkezi olarak yönetir.
        """

        self.logger.exception(
            "Blacklist command error: %s",
            error,
        )

        if isinstance(
            error,
            app_commands.errors.MissingPermissions,
        ):

            await self.safe_response(
                interaction,
                content=(
                    "❌ Bu komutu kullanmak için "
                    "Administrator yetkisine sahip "
                    "olmalısın."
                ),
            )

            return

        if isinstance(
            error,
            app_commands.errors.CommandOnCooldown,
        ):

            await self.safe_response(
                interaction,
                content=(
                    "⏳ Bu komut şu anda cooldown'da."
                ),
            )

            return

        await self.safe_response(
            interaction,
            content=(
                "❌ Blacklist komutunda beklenmeyen "
                "bir hata oluştu."
            ),
        )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Cog setup.
    """

    await bot.add_cog(
        Blacklist(
            bot,
        ),
    )