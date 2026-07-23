from __future__ import annotations

import logging
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
# SAY MODAL
# ============================================================


class SayModal(discord.ui.Modal):
    """
    PAG yayın mesajı oluşturma paneli.

    Aynı panel üzerinden:
    - Başlık
    - 3 farklı yazı alanı
    - Roblox avatarı

    alınabilir.
    """

    def __init__(
        self,
        cog: "Say",
    ) -> None:
        super().__init__(
            title="PAG Say Panel",
        )

        self.cog = cog

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        self.title_input = discord.ui.TextInput(
            label="Başlık",
            placeholder="Örn: 🏆 Haftanın Oyuncusu",
            required=True,
            min_length=1,
            max_length=256,
        )

        # ----------------------------------------------------
        # MAIN TEXT
        # ----------------------------------------------------

        self.main_text = discord.ui.TextInput(
            label="Ana Yazı",
            placeholder="Ana duyuru metnini yaz...",
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=1,
            max_length=4000,
        )

        # ----------------------------------------------------
        # SECOND TEXT
        # ----------------------------------------------------

        self.second_text = discord.ui.TextInput(
            label="Ek Yazı 1",
            placeholder="İsteğe bağlı ek yazı...",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )

        # ----------------------------------------------------
        # THIRD TEXT
        # ----------------------------------------------------

        self.third_text = discord.ui.TextInput(
            label="Ek Yazı 2",
            placeholder="İsteğe bağlı ek yazı...",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )

        # ----------------------------------------------------
        # ROBLOX USERNAME
        # ----------------------------------------------------

        self.roblox_username = discord.ui.TextInput(
            label="Roblox Kullanıcı Adı",
            placeholder="Avatar eklemek için isteğe bağlı...",
            required=False,
            max_length=20,
        )

        self.add_item(
            self.title_input
        )

        self.add_item(
            self.main_text
        )

        self.add_item(
            self.second_text
        )

        self.add_item(
            self.third_text
        )

        self.add_item(
            self.roblox_username
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Panel gönderildiğinde çalışır.
        """

        # ----------------------------------------------------
        # IMMEDIATE ACK
        # ----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            await self.cog.send_message(
                interaction=interaction,
                title=self.title_input.value.strip(),
                main_text=self.main_text.value.strip(),
                second_text=self.second_text.value.strip(),
                third_text=self.third_text.value.strip(),
                roblox_username=(
                    self.roblox_username.value.strip()
                    or None
                ),
            )

        except Exception:
            self.cog.logger.exception(
                "Unexpected error while executing /say.",
            )

            await interaction.edit_original_response(
                content=(
                    "❌ Mesaj gönderilirken beklenmeyen "
                    "bir hata oluştu."
                ),
            )


# ============================================================
# SAY COG
# ============================================================


class Say(commands.Cog):
    """
    PAG say/yayın sistemi.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot

        self.roblox_service = (
            roblox_service
        )

        self.logger = logger

    # ========================================================
    # SAY COMMAND
    # ========================================================

    @app_commands.command(
        name="say",
        description="PAG adına özel bir mesaj gönderir.",
    )
    @app_commands.default_permissions(
        administrator=True,
    )
    @app_commands.guild_only()
    async def say(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Say panelini açar.
        """

        if interaction.guild is None:
            await interaction.response.send_message(
                "Bu komut sadece sunucuda kullanılabilir.",
                ephemeral=True,
            )

            return

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Üye bilgisi alınamadı.",
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # REAL PERMISSION CHECK
        # ----------------------------------------------------

        if not member.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Bu komutu yalnızca sunucu yöneticileri "
                "kullanabilir.",
                ephemeral=True,
            )

            return

        await interaction.response.send_modal(
            SayModal(
                self,
            )
        )

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    async def send_message(
        self,
        *,
        interaction: discord.Interaction,
        title: str,
        main_text: str,
        second_text: str,
        third_text: str,
        roblox_username: Optional[str],
    ) -> None:
        """
        Say mesajını oluşturur ve gönderir.
        """

        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = discord.Embed(
            title=title,
            description=main_text,
            timestamp=discord.utils.utcnow(),
        )

        # ----------------------------------------------------
        # EXTRA TEXTS
        # ----------------------------------------------------

        if second_text:
            embed.add_field(
                name="",
                value=second_text,
                inline=False,
            )

        if third_text:
            embed.add_field(
                name="",
                value=third_text,
                inline=False,
            )

        # ----------------------------------------------------
        # ROBLOX AVATAR
        # ----------------------------------------------------

        if roblox_username:

            try:
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

                embed.set_thumbnail(
                    url=avatar.image_url,
                )

                embed.set_footer(
                    text=(
                        f"Roblox: {user.display_name}"
                    ),
                )

            except RobloxNotFoundError:

                self.logger.warning(
                    "Roblox user not found for /say: %s",
                    roblox_username,
                )

            except RobloxAPIError:

                self.logger.warning(
                    "Roblox API failed for /say.",
                    exc_info=True,
                )

        # ----------------------------------------------------
        # SEND PUBLIC MESSAGE
        # ----------------------------------------------------

        await interaction.channel.send(
            content="@everyone",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
            ),
        )

        # ----------------------------------------------------
        # PRIVATE RESULT
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                "✅ Mesaj başarıyla gönderildi."
            ),
        )

        self.logger.info(
            "Say message sent by user=%s guild=%s",
            interaction.user.id,
            interaction.guild.id
            if interaction.guild
            else None,
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
        Say(
            bot,
            roblox_service=bot.roblox_service,
            logger=bot.logger,
        )
    )