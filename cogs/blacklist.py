from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)


class Blacklist(commands.Cog):
    """
    PAG Blacklist sistemi.

    Komutlar:

        /blacklist
        /unblacklist

    Kullanım:

        /blacklist user:@User reason:Reason

        /blacklist username:RobloxUsername reason:Reason

        /unblacklist user:@User

        /unblacklist username:RobloxUsername
    """

    TABLE_NAME = "blacklist"

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.logger: logging.Logger = (
            bot.logger
        )

        self.database = bot.database

        self.roblox_service: RobloxService = (
            bot.roblox_service
        )

        self._lock = asyncio.Lock()

    # ========================================================
    # DATABASE
    # ========================================================

    async def cog_load(
        self,
    ) -> None:
        """
        Blacklist tablosunu oluşturur.
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

                active INTEGER NOT NULL
                    DEFAULT 1
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

        self.logger.info(
            "Blacklist system initialized.",
        )

    # ========================================================
    # BLACKLIST
    # ========================================================

    @app_commands.command(
        name="blacklist",
        description="Bir kullanıcıyı PAG blacklistine ekler.",
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

        # ====================================================
        # VALIDATION
        # ====================================================

        if user is None and not username:

            await interaction.response.send_message(
                (
                    "❌ En az bir hedef belirtmelisin.\n\n"
                    "Discord üyesi veya Roblox kullanıcı adı "
                    "girebilirsin."
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:

            discord_id = (
                user.id
                if user is not None
                else None
            )

            roblox_id = None
            roblox_name = None
            avatar_url = None

            # =================================================
            # ROBLOX USERNAME
            # =================================================

            if username:

                roblox_user = (
                    await self.roblox_service
                    .get_user_by_username(
                        username,
                    )
                )

                roblox_id = (
                    roblox_user.id
                )

                roblox_name = (
                    roblox_user.name
                )

                # Avatar zorunlu değil.
                # Blacklist işlemini avatar yüzünden
                # başarısız bırakmıyoruz.

                try:

                    avatar = (
                        await self.roblox_service
                        .get_avatar(
                            roblox_id,
                        )
                    )

                    avatar_url = (
                        avatar.image_url
                    )

                except Exception:

                    self.logger.warning(
                        (
                            "Failed to fetch blacklist "
                            "avatar for Roblox ID %s."
                        ),
                        roblox_id,
                    )

            # =================================================
            # EXISTING RECORD CHECK
            # =================================================

            existing = None

            if discord_id is not None:

                existing = (
                    await self.database.fetchone(
                        """
                        SELECT *
                        FROM blacklist
                        WHERE discord_id = ?
                        """,
                        (
                            discord_id,
                        ),
                    )
                )

            if existing is None and roblox_id is not None:

                existing = (
                    await self.database.fetchone(
                        """
                        SELECT *
                        FROM blacklist
                        WHERE roblox_id = ?
                        """,
                        (
                            roblox_id,
                        ),
                    )
                )

            now = datetime.now(
                timezone.utc,
            ).isoformat()

            # =================================================
            # UPDATE EXISTING
            # =================================================

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
                        discord_id,
                        roblox_id,
                        roblox_name,
                        reason[:1000],
                        interaction.user.id,
                        now,
                        existing["id"],
                    ),
                )

            # =================================================
            # INSERT NEW
            # =================================================

            else:

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
                        discord_id,
                        roblox_id,
                        roblox_name,
                        reason[:1000],
                        interaction.user.id,
                        now,
                    ),
                )

            # =================================================
            # EMBED
            # =================================================

            embed = discord.Embed(
                title="🚫 PAG BLACKLIST",
                description=(
                    "Bu kullanıcı PAG blacklistine "
                    "eklendi."
                ),
                timestamp=discord.utils.utcnow(),
            )

            if user is not None:

                embed.add_field(
                    name="Discord User",
                    value=(
                        f"{user.mention}\n"
                        f"`{user.id}`"
                    ),
                    inline=True,
                )

            if roblox_name is not None:

                embed.add_field(
                    name="Roblox User",
                    value=(
                        f"**{roblox_name}**\n"
                        f"`{roblox_id}`"
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
                value=interaction.user.mention,
                inline=True,
            )

            embed.add_field(
                name="Status",
                value="🔴 **BLACKLISTED**",
                inline=True,
            )

            if avatar_url:

                embed.set_thumbnail(
                    url=avatar_url,
                )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

        except RobloxNotFoundError:

            await interaction.followup.send(
                (
                    "❌ Roblox kullanıcısı bulunamadı."
                ),
                ephemeral=True,
            )

        except RobloxAPIError:

            await interaction.followup.send(
                (
                    "❌ Roblox API şu anda kullanılamıyor."
                ),
                ephemeral=True,
            )

        except Exception:

            self.logger.exception(
                "Blacklist command failed.",
            )

            await interaction.followup.send(
                (
                    "❌ Blacklist işlemi sırasında "
                    "beklenmeyen bir hata oluştu."
                ),
                ephemeral=True,
            )

    # ========================================================
    # UNBLACKLIST
    # ========================================================

    @app_commands.command(
        name="unblacklist",
        description="Bir kullanıcıyı PAG blacklistinden çıkarır.",
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

        if user is None and not username:

            await interaction.response.send_message(
                (
                    "❌ Discord üyesi veya Roblox "
                    "kullanıcı adı belirtmelisin."
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:

            discord_id = (
                user.id
                if user is not None
                else None
            )

            roblox_id = None

            if username:

                roblox_user = (
                    await self.roblox_service
                    .get_user_by_username(
                        username,
                    )
                )

                roblox_id = (
                    roblox_user.id
                )

            # =================================================
            # SEARCH
            # =================================================

            row = None

            if discord_id is not None:

                row = (
                    await self.database.fetchone(
                        """
                        SELECT *
                        FROM blacklist
                        WHERE discord_id = ?
                        AND active = 1
                        """,
                        (
                            discord_id,
                        ),
                    )
                )

            if row is None and roblox_id is not None:

                row = (
                    await self.database.fetchone(
                        """
                        SELECT *
                        FROM blacklist
                        WHERE roblox_id = ?
                        AND active = 1
                        """,
                        (
                            roblox_id,
                        ),
                    )
                )

            if row is None:

                await interaction.followup.send(
                    (
                        "ℹ️ Bu kullanıcı aktif blacklistte "
                        "bulunamadı."
                    ),
                    ephemeral=True,
                )

                return

            # =================================================
            # DISABLE RECORD
            # =================================================

            await self.database.execute(
                """
                UPDATE blacklist
                SET active = 0
                WHERE id = ?
                """,
                (
                    row["id"],
                ),
            )

            # =================================================
            # EMBED
            # =================================================

            embed = discord.Embed(
                title="✅ PAG UNBLACKLIST",
                description=(
                    "Kullanıcı blacklistten çıkarıldı."
                ),
                timestamp=discord.utils.utcnow(),
            )

            if row["discord_id"]:

                embed.add_field(
                    name="Discord User",
                    value=(
                        f"<@{row['discord_id']}>"
                    ),
                    inline=True,
                )

            if row["roblox_username"]:

                embed.add_field(
                    name="Roblox User",
                    value=(
                        f"**{row['roblox_username']}**"
                    ),
                    inline=True,
                )

            embed.add_field(
                name="Previous Reason",
                value=(
                    str(
                        row["reason"]
                    )[:1024]
                ),
                inline=False,
            )

            embed.add_field(
                name="Removed By",
                value=interaction.user.mention,
                inline=True,
            )

            embed.add_field(
                name="Status",
                value="🟢 **UNBLACKLISTED**",
                inline=True,
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

        except RobloxNotFoundError:

            await interaction.followup.send(
                (
                    "❌ Roblox kullanıcısı bulunamadı."
                ),
                ephemeral=True,
            )

        except RobloxAPIError:

            await interaction.followup.send(
                (
                    "❌ Roblox API şu anda kullanılamıyor."
                ),
                ephemeral=True,
            )

        except Exception:

            self.logger.exception(
                "Unblacklist command failed.",
            )

            await interaction.followup.send(
                (
                    "❌ Unblacklist işlemi sırasında "
                    "beklenmeyen bir hata oluştu."
                ),
                ephemeral=True,
            )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:

        self.logger.exception(
            "Blacklist command error: %s",
            error,
        )

        message = (
            "❌ Bu işlem sırasında bir hata oluştu."
        )

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True,
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True,
            )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Blacklist(
            bot,
        ),
    )