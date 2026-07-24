from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
)
from services.top10_service import (
    Top10Entry,
    Top10Service,
)


class Top10ConfirmView(discord.ui.View):
    """
    Top 10 reset işlemi için onay paneli.
    """

    def __init__(
        self,
        *,
        cog: "Top10",
        author_id: int,
    ) -> None:
        super().__init__(
            timeout=30,
        )

        self.cog = cog
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                (
                    "❌ Bu paneli sadece "
                    "komutu kullanan kişi kullanabilir."
                ),
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Reset",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "⏳ PAG Top 10 sıfırlanıyor..."
            ),
            view=self,
        )

        try:
            await self.cog.service.reset()

        except Exception:
            self.cog.logger.exception(
                "Top 10 reset failed.",
            )

            await interaction.edit_original_response(
                content=(
                    "❌ Top 10 sıfırlanırken "
                    "bir hata oluştu."
                ),
                view=None,
            )

            return

        await interaction.edit_original_response(
            content=(
                "✅ **PAG Top 10 başarıyla sıfırlandı.**"
            ),
            view=None,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "❎ Top 10 reset işlemi iptal edildi."
            ),
            view=self,
        )

        self.stop()

    async def on_timeout(
        self,
    ) -> None:
        for child in self.children:
            child.disabled = True


class Top10(commands.Cog):
    """
    PAG Core
    Top 10 Cog

    This Cog provides the complete Discord interface
    for the PAG Top 10 ranking system.

    Public:

        /top10

    Administrator:

        /top10-set
        /top10-edit
        /top10-remove
        /top10-reset

    Ranking:

        Position 1 = Best player
        Position 2 = Second best player
        ...
        Position 10 = Tenth best player

    Data is managed by:

        services.top10_service.Top10Service
    """

    MIN_POSITION = 1
    MAX_POSITION = 10

    def __init__(
        self,
        bot: commands.Bot,
        *,
        top10_service: Top10Service,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.service = top10_service
        self.logger = logger

    # ========================================================
    # EMBEDS
    # ========================================================

    @staticmethod
    def _build_top10_embed(
        entries: list[Top10Entry],
    ) -> discord.Embed:
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

            embed.set_footer(
                text="PAG • Top 10 Rankings",
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

        embed.description = (
            "\n\n".join(
                lines,
            )
        )

        embed.set_footer(
            text="PAG • Top 10 Rankings",
        )

        return embed

    @staticmethod
    def _build_success_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def _build_error_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    # ========================================================
    # HELPERS
    # ========================================================

    async def _get_entry_at_position(
        self,
        position: int,
    ) -> Top10Entry | None:
        entries = await self.service.get_all()

        for entry in entries:
            if entry.position == position:
                return entry

        return None

    @staticmethod
    def _clean_username(
        username: str,
    ) -> str:
        return username.strip()

    # ========================================================
    # /TOP10
    # ========================================================

    @app_commands.command(
        name="top10",
        description="PAG Top 10 sıralamasını gösterir.",
    )
    async def top10(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer()

        try:
            entries = (
                await self.service.get_all()
            )

        except Exception:
            self.logger.exception(
                "Failed to load Top 10.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "Top 10 listesi yüklenirken "
                        "bir hata oluştu."
                    ),
                ),
            )

            return

        await interaction.followup.send(
            embed=self._build_top10_embed(
                entries,
            ),
        )

    # ========================================================
    # /TOP10-SET
    # ========================================================

    @app_commands.command(
        name="top10-set",
        description="Top 10'a oyuncu ekler veya değiştirir.",
    )
    @app_commands.describe(
        position="Oyuncunun pozisyonu. 1-10.",
        roblox_username="Roblox kullanıcı adı.",
        member="İsteğe bağlı Discord üyesi.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_set(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        roblox_username: str,
        member: discord.Member | None = None,
    ) -> None:
        username = self._clean_username(
            roblox_username,
        )

        if not username:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Geçersiz Kullanıcı Adı",
                    (
                        "Roblox kullanıcı adı "
                        "boş bırakılamaz."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = (
                await self.service.set_player(
                    position=position,
                    roblox_username=username,
                    discord_id=(
                        member.id
                        if member
                        else None
                    ),
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox Kullanıcısı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox API error during Top 10 set.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'sine erişilirken "
                        "bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Top 10 set failed.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ İşlem Başarısız",
                    (
                        "Oyuncu Top 10'a eklenirken "
                        "bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=self._build_success_embed(
                "✅ Top 10 Güncellendi",
                (
                    f"**#{entry.position}** pozisyonuna "
                    f"**{entry.display_name}** eklendi.\n\n"
                    f"Roblox: `{entry.roblox_username}`"
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # /TOP10-EDIT
    # ========================================================

    @app_commands.command(
        name="top10-edit",
        description="Top 10'daki oyuncuyu düzenler.",
    )
    @app_commands.describe(
        position="Düzenlenecek pozisyon.",
        roblox_username="Yeni Roblox kullanıcı adı.",
        member="Yeni Discord üyesi.",
        new_position="Yeni pozisyon.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_edit(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        roblox_username: str | None = None,
        member: discord.Member | None = None,
        new_position: app_commands.Range[
            int,
            1,
            10,
        ] | None = None,
    ) -> None:
        try:
            current_entry = (
                await self._get_entry_at_position(
                    position,
                )
            )

        except Exception:
            self.logger.exception(
                "Failed to load entry for edit.",
            )

            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "Düzenlenecek oyuncu "
                        "kontrol edilemedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        if current_entry is None:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Pozisyon Boş",
                    (
                        f"**#{position}** pozisyonunda "
                        "oyuncu bulunmuyor."
                    ),
                ),
                ephemeral=True,
            )

            return

        username = (
            self._clean_username(
                roblox_username,
            )
            if roblox_username
            else current_entry.roblox_username
        )

        target_position = (
            new_position
            if new_position is not None
            else position
        )

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            if target_position != position:
                await self.service.move_player(
                    old_position=position,
                    new_position=target_position,
                )

            entry = (
                await self.service.set_player(
                    position=target_position,
                    roblox_username=username,
                    discord_id=(
                        member.id
                        if member
                        else current_entry.discord_id
                    ),
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox Kullanıcısı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox API error during Top 10 edit.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'sine erişilemedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Top 10 edit failed.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Düzenleme Başarısız",
                    (
                        "Oyuncu düzenlenirken "
                        "bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=self._build_success_embed(
                "✅ Top 10 Düzenlendi",
                (
                    f"**#{entry.position}** pozisyonu "
                    "başarıyla güncellendi.\n\n"
                    f"Roblox: `{entry.roblox_username}`"
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # /TOP10-REMOVE
    # ========================================================

    @app_commands.command(
        name="top10-remove",
        description="Top 10'daki oyuncuyu kaldırır.",
    )
    @app_commands.describe(
        position="Kaldırılacak pozisyon.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_remove(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
    ) -> None:
        try:
            entry = (
                await self._get_entry_at_position(
                    position,
                )
            )

        except Exception:
            self.logger.exception(
                "Failed to load entry for removal.",
            )

            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "Oyuncu kontrol edilirken "
                        "bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        if entry is None:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Pozisyon Boş",
                    (
                        f"**#{position}** pozisyonunda "
                        "oyuncu bulunmuyor."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            await self.service.remove_position(
                position,
            )

        except Exception:
            self.logger.exception(
                "Top 10 remove failed.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Oyuncu Kaldırılamadı",
                    (
                        "Oyuncu Top 10'dan "
                        "kaldırılırken bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=self._build_success_embed(
                "✅ Oyuncu Kaldırıldı",
                (
                    f"**#{entry.position}** pozisyonundaki "
                    f"**{entry.display_name}** "
                    "Top 10'dan kaldırıldı."
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # /TOP10-RESET
    # ========================================================

    @app_commands.command(
        name="top10-reset",
        description="PAG Top 10 listesini tamamen sıfırlar.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_reset(
        self,
        interaction: discord.Interaction,
    ) -> None:
        embed = discord.Embed(
            title="⚠️ PAG Top 10 Reset",
            description=(
                "Bu işlem **tüm Top 10 oyuncularını "
                "kaldıracaktır.**\n\n"
                "Devam etmek istiyorsanız "
                "**Reset** butonuna basın."
            ),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=Top10ConfirmView(
                cog=self,
                author_id=interaction.user.id,
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
        if isinstance(
            error,
            app_commands.MissingPermissions,
        ):
            message = (
                "❌ Bu komutu kullanmak için "
                "**Administrator** yetkisine "
                "sahip olmalısın."
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

            return

        self.logger.error(
            "Top 10 command error: %s",
            error,
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                (
                    "❌ Top 10 komutu çalıştırılırken "
                    "beklenmeyen bir hata oluştu."
                ),
                ephemeral=True,
            )

        else:
            await interaction.response.send_message(
                (
                    "❌ Top 10 komutu çalıştırılırken "
                    "beklenmeyen bir hata oluştu."
                ),
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
            top10_service=bot.top10_service,
            logger=bot.logger,
        )
    )