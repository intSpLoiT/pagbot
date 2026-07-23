from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)


# ============================================================
# MODELS
# ============================================================


@dataclass(slots=True, frozen=True)
class Top10Entry:
    """
    Top 10 oyuncu kaydı.
    """

    position: int
    discord_id: Optional[int]
    roblox_id: int
    roblox_username: str
    display_name: str
    avatar_url: str


# ============================================================
# TOP 10 SERVICE
# ============================================================


class Top10Service:
    """
    PAG Top 10 database işlemleri.

    Liste maksimum 10 oyuncu içerir.

    Roblox API:
        Sadece oyuncu ekleme/güncelleme sırasında kullanılır.

    Top 10 görüntüleme:
        Sadece database kullanır.
        Bu nedenle hızlıdır.
    """

    TABLE_NAME = "top_10_players"

    def __init__(
        self,
        database,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:
        self.database = database
        self.roblox_service = roblox_service
        self.logger = logger

        self._lock = asyncio.Lock()

    # ========================================================
    # INITIALIZE
    # ========================================================

    async def initialize(self) -> None:
        """
        Top 10 tablosunu oluşturur.
        """

        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS top_10_players (
                position INTEGER PRIMARY KEY,

                discord_id INTEGER,

                roblox_id INTEGER NOT NULL UNIQUE,

                roblox_username TEXT NOT NULL,

                display_name TEXT NOT NULL,

                avatar_url TEXT NOT NULL,

                updated_at TEXT NOT NULL,

                CHECK (
                    position >= 1
                    AND position <= 10
                )
            )
            """
        )

        self.logger.info(
            "Top 10 database initialized.",
        )

    # ========================================================
    # SET PLAYER
    # ========================================================

    async def set_player(
        self,
        *,
        position: int,
        roblox_username: str,
        discord_id: int | None = None,
    ) -> Top10Entry:
        """
        Bir oyuncuyu Top 10 pozisyonuna ekler.

        Kullanıcı:
            - Roblox username
            - Discord member

        ile seçilebilir.

        Aynı Roblox oyuncusu başka pozisyondaysa
        eski pozisyonundan kaldırılır.
        """

        if not 1 <= position <= 10:
            raise ValueError(
                "Top 10 position must be between 1 and 10.",
            )

        async with self._lock:

            user = (
                await self.roblox_service
                .get_user_by_username(
                    roblox_username,
                )
            )

            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

            now = discord.utils.utcnow().isoformat()

            await self.database.transaction(
                [
                    (
                        """
                        DELETE FROM top_10_players
                        WHERE roblox_id = ?
                        """,
                        (
                            user.id,
                        ),
                    ),
                    (
                        """
                        DELETE FROM top_10_players
                        WHERE position = ?
                        """,
                        (
                            position,
                        ),
                    ),
                    (
                        """
                        INSERT INTO top_10_players (
                            position,
                            discord_id,
                            roblox_id,
                            roblox_username,
                            display_name,
                            avatar_url,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            position,
                            discord_id,
                            user.id,
                            user.name,
                            user.display_name,
                            avatar.image_url,
                            now,
                        ),
                    ),
                ],
            )

            return Top10Entry(
                position=position,
                discord_id=discord_id,
                roblox_id=user.id,
                roblox_username=user.name,
                display_name=user.display_name,
                avatar_url=avatar.image_url,
            )

    # ========================================================
    # GET ALL
    # ========================================================

    async def get_all(
        self,
    ) -> list[Top10Entry]:
        """
        Top 10 listesini tek database sorgusuyla alır.
        """

        rows = await self.database.fetchall(
            """
            SELECT
                position,
                discord_id,
                roblox_id,
                roblox_username,
                display_name,
                avatar_url
            FROM top_10_players
            ORDER BY position ASC
            """
        )

        return [
            Top10Entry(
                position=int(
                    row["position"]
                ),
                discord_id=(
                    int(row["discord_id"])
                    if row["discord_id"] is not None
                    else None
                ),
                roblox_id=int(
                    row["roblox_id"]
                ),
                roblox_username=str(
                    row["roblox_username"]
                ),
                display_name=str(
                    row["display_name"]
                ),
                avatar_url=str(
                    row["avatar_url"]
                ),
            )
            for row in rows
        ]

    # ========================================================
    # RESET
    # ========================================================

    async def reset(
        self,
    ) -> None:
        """
        Top 10 listesini temizler.
        """

        async with self._lock:

            await self.database.execute(
                """
                DELETE FROM top_10_players
                """
            )

        self.logger.info(
            "Top 10 list reset.",
        )

    # ========================================================
    # REMOVE POSITION
    # ========================================================

    async def remove_position(
        self,
        position: int,
    ) -> None:
        """
        Belirli bir pozisyonu siler.
        """

        if not 1 <= position <= 10:
            raise ValueError(
                "Position must be between 1 and 10.",
            )

        async with self._lock:

            await self.database.execute(
                """
                DELETE FROM top_10_players
                WHERE position = ?
                """,
                (
                    position,
                ),
            )

    # ========================================================
    # MOVE PLAYER
    # ========================================================

    async def move_player(
        self,
        old_position: int,
        new_position: int,
    ) -> None:
        """
        İki Top 10 pozisyonunu değiştirir.
        """

        if not 1 <= old_position <= 10:
            raise ValueError(
                "Invalid old position.",
            )

        if not 1 <= new_position <= 10:
            raise ValueError(
                "Invalid new position.",
            )

        if old_position == new_position:
            return

        async with self._lock:

            rows = await self.database.fetchall(
                """
                SELECT
                    position,
                    discord_id,
                    roblox_id,
                    roblox_username,
                    display_name,
                    avatar_url,
                    updated_at
                FROM top_10_players
                WHERE position IN (?, ?)
                """,
                (
                    old_position,
                    new_position,
                ),
            )

            old_entry = None
            new_entry = None

            for row in rows:

                if row["position"] == old_position:
                    old_entry = row

                elif row["position"] == new_position:
                    new_entry = row

            queries = [
                (
                    """
                    DELETE FROM top_10_players
                    WHERE position IN (?, ?)
                    """,
                    (
                        old_position,
                        new_position,
                    ),
                ),
            ]

            if old_entry is not None:

                queries.append(
                    (
                        """
                        INSERT INTO top_10_players (
                            position,
                            discord_id,
                            roblox_id,
                            roblox_username,
                            display_name,
                            avatar_url,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_position,
                            old_entry["discord_id"],
                            old_entry["roblox_id"],
                            old_entry["roblox_username"],
                            old_entry["display_name"],
                            old_entry["avatar_url"],
                            old_entry["updated_at"],
                        ),
                    )
                )

            if new_entry is not None:

                queries.append(
                    (
                        """
                        INSERT INTO top_10_players (
                            position,
                            discord_id,
                            roblox_id,
                            roblox_username,
                            display_name,
                            avatar_url,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            old_position,
                            new_entry["discord_id"],
                            new_entry["roblox_id"],
                            new_entry["roblox_username"],
                            new_entry["display_name"],
                            new_entry["avatar_url"],
                            new_entry["updated_at"],
                        ),
                    )
                )

            await self.database.transaction(
                queries,
            )


# ============================================================
# TOP 10 EMBED
# ============================================================


def build_top_10_embed(
    entries: list[Top10Entry],
) -> discord.Embed:
    """
    Profesyonel Top 10 embed'i oluşturur.
    """

    embed = discord.Embed(
        title="🏆 PAG TOP 10",
        description=(
            "The strongest players of PAG.\n\n"
            "Every position is earned."
        ),
        timestamp=discord.utils.utcnow(),
    )

    if not entries:

        embed.description = (
            "The PAG Top 10 is currently empty."
        )

        return embed

    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }

    lines: list[str] = []

    for entry in entries:

        prefix = medals.get(
            entry.position,
            f"`#{entry.position}`",
        )

        if entry.discord_id:

            member_text = (
                f"<@{entry.discord_id}>"
            )

        else:

            member_text = (
                f"**{entry.display_name}**"
            )

        lines.append(
            (
                f"{prefix} "
                f"{member_text}\n"
                f"└ `{entry.roblox_username}`"
            )
        )

    embed.description = "\n\n".join(
        lines,
    )

    embed.set_footer(
        text=(
            "PAG • Top 10 Rankings"
        ),
    )

    return embed


# ============================================================
# TOP 10 PANEL
# ============================================================


class Top10PanelView(
    discord.ui.View,
):
    """
    Top 10 paneli.

    Panel mesajı kalıcı tutulabilir.
    """

    def __init__(
        self,
        cog: "Top10",
    ) -> None:
        super().__init__(
            timeout=None,
        )

        self.cog = cog

    @discord.ui.button(
        label="View Top 10",
        emoji="🏆",
        style=discord.ButtonStyle.primary,
        custom_id="pag_top10_view",
    )
    async def view_top_10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        entries = (
            await self.cog.service
            .get_all()
        )

        await interaction.followup.send(
            embed=build_top_10_embed(
                entries,
            ),
            ephemeral=True,
        )


# ============================================================
# TOP 10 EDIT MODAL
# ============================================================


class Top10EditModal(
    discord.ui.Modal,
):
    """
    Top 10 hızlı düzenleme paneli.
    """

    def __init__(
        self,
        cog: "Top10",
    ) -> None:
        super().__init__(
            title="Edit PAG Top 10",
        )

        self.cog = cog

        self.position = discord.ui.TextInput(
            label="Position",
            placeholder="1 - 10",
            required=True,
            max_length=2,
        )

        self.roblox_username = discord.ui.TextInput(
            label="Roblox Username",
            placeholder="Roblox kullanıcı adı",
            required=True,
            max_length=20,
        )

        self.discord_member = discord.ui.TextInput(
            label="Discord User ID",
            placeholder="İsteğe bağlı Discord ID",
            required=False,
            max_length=20,
        )

        self.add_item(
            self.position,
        )

        self.add_item(
            self.roblox_username,
        )

        self.add_item(
            self.discord_member,
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        try:

            position = int(
                self.position.value.strip()
            )

            discord_id = None

            if self.discord_member.value.strip():

                discord_id = int(
                    self.discord_member.value.strip()
                )

            entry = await self.cog.service.set_player(
                position=position,
                roblox_username=(
                    self.roblox_username.value.strip()
                ),
                discord_id=discord_id,
            )

            await interaction.followup.send(
                content=(
                    f"✅ `#{entry.position}` "
                    f"güncellendi: "
                    f"`{entry.roblox_username}`"
                ),
                ephemeral=True,
            )

        except ValueError:

            await interaction.followup.send(
                content=(
                    "❌ Position ve Discord ID "
                    "geçerli bir sayı olmalı."
                ),
                ephemeral=True,
            )

        except RobloxNotFoundError:

            await interaction.followup.send(
                content=(
                    "❌ Roblox kullanıcısı bulunamadı."
                ),
                ephemeral=True,
            )

        except RobloxAPIError:

            await interaction.followup.send(
                content=(
                    "❌ Roblox API şu anda kullanılamıyor."
                ),
                ephemeral=True,
            )

        except Exception:

            self.cog.logger.exception(
                "Top 10 edit failed.",
            )

            await interaction.followup.send(
                content=(
                    "❌ Top 10 güncellenirken "
                    "beklenmeyen bir hata oluştu."
                ),
                ephemeral=True,
            )


# ============================================================
# TOP 10 COG
# ============================================================


class Top10(
    commands.GroupCog,
    group_name="top_10",
):
    """
    PAG Top 10 komutları.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        database,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:

        self.bot = bot
        self.logger = logger

        self.service = Top10Service(
            database=database,
            roblox_service=roblox_service,
            logger=logger,
        )

    async def cog_load(
        self,
    ) -> None:

        await self.service.initialize()

    # ========================================================
    # /top_10
    # ========================================================

    @app_commands.command(
        name="show",
        description="PAG Top 10 listesini gösterir.",
    )
    async def show(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer()

        entries = (
            await self.service
            .get_all()
        )

        await interaction.followup.send(
            embed=build_top_10_embed(
                entries,
            ),
        )

    # ========================================================
    # /top_10-set
    # ========================================================

    @app_commands.command(
        name="set",
        description="Top 10'a oyuncu ekler veya günceller.",
    )
    @app_commands.describe(
        position="Top 10 pozisyonu.",
        member="İsteğe bağlı Discord üyesi.",
        roblox_username="İsteğe bağlı Roblox kullanıcı adı.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def set(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        member: discord.Member | None = None,
        roblox_username: str | None = None,
    ) -> None:

        if member is None and not roblox_username:

            await interaction.response.send_message(
                (
                    "❌ Discord üyesi veya Roblox "
                    "kullanıcı adı vermelisin."
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:

            if roblox_username:

                username = (
                    roblox_username.strip()
                )

                discord_id = (
                    member.id
                    if member
                    else None
                )

            else:

                # Bu aşamada Discord üyesinin
                # Roblox username'i bilinmiyorsa
                # username alınamaz.
                await interaction.followup.send(
                    (
                        "⚠️ Discord üyesi seçildi ancak "
                        "Roblox kullanıcı adı verilmedi. "
                        "Verify database bağlantısı "
                        "eklendiğinde bu otomatik olacak."
                    ),
                    ephemeral=True,
                )

                return

            entry = await self.service.set_player(
                position=position,
                roblox_username=username,
                discord_id=discord_id,
            )

            await interaction.followup.send(
                content=(
                    f"✅ **#{entry.position}** "
                    f"Top 10'a eklendi.\n"
                    f"Roblox: `{entry.roblox_username}`"
                ),
                ephemeral=True,
            )

        except RobloxNotFoundError:

            await interaction.followup.send(
                "❌ Roblox kullanıcısı bulunamadı.",
                ephemeral=True,
            )

        except RobloxAPIError:

            await interaction.followup.send(
                "❌ Roblox API isteği başarısız oldu.",
                ephemeral=True,
            )

        except Exception:

            self.logger.exception(
                "Top 10 set command failed.",
            )

            await interaction.followup.send(
                "❌ Top 10 güncellenemedi.",
                ephemeral=True,
            )
    # ========================================================
    # /top_10-edit
    # ========================================================

    @app_commands.command(
        name="edit",
        description="Top 10 düzenleme panelini açar.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def edit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.send_modal(
            Top10EditModal(
                self,
            )
        )

    # ========================================================
    # /top_10-reset
    # ========================================================

    @app_commands.command(
        name="reset",
        description="Top 10 listesini sıfırlar.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def reset(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        await self.service.reset()

        await interaction.followup.send(
            "✅ PAG Top 10 sıfırlandı.",
            ephemeral=True,
        )

    # ========================================================
    # /top_10-panel
    # ========================================================

    @app_commands.command(
        name="panel",
        description="Top 10 paneli gönderir.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def panel(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        entries = (
            await self.service
            .get_all()
        )

        await interaction.channel.send(
            embed=build_top_10_embed(
                entries,
            ),
            view=Top10PanelView(
                self,
            ),
        )

        await interaction.followup.send(
            "✅ Top 10 paneli gönderildi.",
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
            "Top 10 command error: %s",
            error,
        )

        message = (
            "❌ Top 10 işlemi sırasında "
            "bir hata oluştu."
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
        Top10(
            bot,
            database=bot.database,
            roblox_service=bot.roblox_service,
            logger=bot.logger,
        )
    )