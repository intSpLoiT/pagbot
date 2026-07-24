from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)
from utils.embeds import PAGEmbeds


class VerifyModal(discord.ui.Modal):
    """
    Roblox kullanıcı adı alma modalı.
    """

    def __init__(
        self,
        cog: "Verify",
    ) -> None:
        super().__init__(
            title="PAG Verification",
        )

        self.cog = cog

        self.username = discord.ui.TextInput(
            label="Roblox Username",
            placeholder="Roblox kullanıcı adını gir...",
            required=True,
            min_length=3,
            max_length=20,
        )

        self.add_item(
            self.username
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Modal gönderildiğinde çalışır.
        """

        await interaction.response.defer(
            ephemeral=True
        )

        username = self.username.value.strip()

        try:
            await self.cog.process_verification(
                interaction,
                username,
            )

        except RobloxNotFoundError:
            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Roblox hesabı bulunamadı."
                )
            )

        except RobloxAPIError:
            self.cog.logger.exception(
                "Roblox API error during verification."
            )

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Roblox API şu anda kullanılamıyor. "
                    "Lütfen daha sonra tekrar deneyin."
                )
            )

        except Exception:
            self.cog.logger.exception(
                "Unexpected verification error."
            )

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Verify işlemi sırasında beklenmeyen "
                    "bir hata oluştu."
                )
            )


class VerifyView(discord.ui.View):
    """
    Verify butonu.
    """

    def __init__(
        self,
        cog: "Verify",
    ) -> None:
        super().__init__(
            timeout=None
        )

        self.cog = cog

    @discord.ui.button(
        label="Verify",
        emoji="🔗",
        style=discord.ButtonStyle.success,
        custom_id="pag_verify",
    )
    async def verify_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """
        Verify butonuna basıldığında modal açılır.
        """

        if interaction.guild is None:
            await interaction.response.send_message(
                "Bu buton sadece sunucuda kullanılabilir.",
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

        # Ally kontrolü modal açılmadan önce yapılır.
        if self.cog.discord_service.is_blocked_from_verification(
            member
        ):
            await interaction.response.send_message(
                embed=PAGEmbeds.error(
                    "Ally üyeleri verify olamaz."
                ),
                ephemeral=True,
            )

            return

        await interaction.response.send_modal(
            VerifyModal(
                self.cog
            )
        )


class Verify(commands.Cog):
    """
    PAG Verification sistemi.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        roblox_service: RobloxService,
        discord_service,
        database,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot

        self.roblox_service = (
            roblox_service
        )

        self.discord_service = (
            discord_service
        )

        self.database = database

        self.logger = logger

        self._view_added = False

    # =========================================================
    # COG LOAD
    # =========================================================

    async def cog_load(
        self,
    ) -> None:
        """
        Persistent verify view'i kaydeder.
        """

        if not self._view_added:

            self.bot.add_view(
                VerifyView(
                    self
                )
            )

            self._view_added = True

    # =========================================================
    # VERIFICATION PROCESS
    # =========================================================

    async def process_verification(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Verify işleminin ana akışı.
        """

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):
            raise RuntimeError(
                "Interaction user is not a guild member."
            )

        # -----------------------------------------------------
        # ALLY CHECK
        # -----------------------------------------------------

        if self.discord_service.is_blocked_from_verification(
            member
        ):
            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Ally üyeleri verify olamaz."
                )
            )

            return

        # -----------------------------------------------------
        # ROBLOX USER
        # -----------------------------------------------------

        user = (
            await self.roblox_service
            .get_user_by_username(
                username
            )
        )

        # -----------------------------------------------------
        # BANNED USER
        # -----------------------------------------------------

        if user.is_banned:

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Bu Roblox hesabı banlı olduğu için "
                    "verify işlemi tamamlanamadı."
                )
            )

            return

        # -----------------------------------------------------
        # AVATAR
        # -----------------------------------------------------

        avatar = (
            await self.roblox_service
            .get_avatar(
                user.id
            )
        )

        # -----------------------------------------------------
        # DATABASE
        # -----------------------------------------------------

        await self.database.execute(
            """
            INSERT OR REPLACE INTO verifications (
                discord_id,
                roblox_id,
                roblox_username,
                verified_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                member.id,
                user.id,
                user.name,
                discord.utils.utcnow().isoformat(),
            ),
        )

        # -----------------------------------------------------
        # VERIFIED ROLE
        # -----------------------------------------------------

        verified_role = (
            self.discord_service
            .find_role(
                interaction.guild,
                "Verified",
            )
        )

        if verified_role is None:
            raise RuntimeError(
                "Verified role was not found."
            )

        await self.discord_service.add_role(
            member,
            verified_role,
            reason="PAG Roblox verification",
        )

        # -----------------------------------------------------
        # SUCCESS EMBED
        # -----------------------------------------------------

        embed = PAGEmbeds.success(
            "Verify başarılı!"
        )

        embed.title = "✅ Verification Successful"

        embed.description = (
            f"**Roblox hesabı:** `{user.name}`\n"
            f"**Display Name:** `{user.display_name}`\n"
            f"**Roblox ID:** `{user.id}`"
        )

        embed.set_thumbnail(
            url=avatar.image_url
        )

        await interaction.edit_original_response(
            embed=embed
        )

    # =========================================================
    # COMMAND
    # =========================================================

    @commands.command(
        name="verify"
    )
    @commands.guild_only()
    async def verify_command(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        Verify panelini gönderir.
        """

        embed = PAGEmbeds.info(
            "Roblox hesabını Discord hesabına "
            "bağlamak için aşağıdaki butona bas."
        )

        embed.title = "🔗 PAG Verification"

        await ctx.send(
            embed=embed,
            view=VerifyView(
                self
            ),
        )


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Cog yükleme fonksiyonu.
    """

    await bot.add_cog(
        Verify(
            bot,
            roblox_service=bot.roblox_service,
            discord_service=bot.discord_service,
            database=bot.database,
            logger=bot.logger,
        )
    )