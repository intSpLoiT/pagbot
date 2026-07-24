from __future__ import annotations


import logging


from dataclasses import dataclass
from datetime import datetime
from typing import Optional


import discord


from discord import app_commands
from discord.ext import commands


from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)


from utils.embeds import PAGEmbeds


# ============================================================
# VERIFY RESULT
# ============================================================


@dataclass(
    slots=True,
)
class VerificationResult:
    """
    Verify işleminin sonucunu temsil eder.

    Gelecekte burada:

        - Roblox ban durumu
        - Roblox grup üyeliği
        - Yaş doğrulaması
        - Hesap yaşı
        - Güven skoru

    gibi bilgiler de tutulabilir.
    """

    roblox_id: int

    roblox_username: str

    roblox_display_name: str

    avatar_url: Optional[str] = None

    verified_at: Optional[datetime] = None


# ============================================================
# VERIFY MODAL
# ============================================================


class VerifyModal(
    discord.ui.Modal,
):
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
            placeholder=(
                "Roblox kullanıcı adını gir..."
            ),
            required=True,
            min_length=3,
            max_length=20,
        )

        self.add_item(
            self.username,
        )

    # ========================================================
    # MODAL SUBMIT
    # ========================================================

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        username = (
            self.username.value
            .strip()
        )

        try:

            result = (
                await self.cog.verify_user(
                    interaction=interaction,
                    username=username,
                )
            )

            await self.cog.send_success_response(
                interaction=interaction,
                result=result,
            )

        except RobloxNotFoundError:

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    "Roblox hesabı bulunamadı.",
                ),
            )

        except RobloxAPIError:

            self.cog.logger.exception(
                (
                    "Roblox API error during "
                    "verification."
                ),
            )

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    (
                        "Roblox API şu anda "
                        "kullanılamıyor. "
                        "Lütfen daha sonra tekrar "
                        "deneyin."
                    ),
                ),
            )

        except PermissionError:

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    (
                        "Bu işlemi gerçekleştirmek "
                        "için gerekli izinler yok."
                    ),
                ),
            )

        except Exception:

            self.cog.logger.exception(
                (
                    "Unexpected verification "
                    "error."
                ),
            )

            await interaction.edit_original_response(
                embed=PAGEmbeds.error(
                    (
                        "Verify işlemi sırasında "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
            )


# ============================================================
# VERIFY VIEW
# ============================================================


class VerifyView(
    discord.ui.View,
):
    """
    Persistent PAG Verify paneli.
    """

    def __init__(
        self,
        cog: "Verify",
    ) -> None:

        super().__init__(
            timeout=None,
        )

        self.cog = cog

    # ========================================================
    # VERIFY BUTTON
    # ========================================================

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

        if interaction.guild is None:

            await interaction.response.send_message(
                (
                    "Bu buton sadece sunucuda "
                    "kullanılabilir."
                ),
                ephemeral=True,
            )

            return

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):

            await interaction.response.send_message(
                (
                    "Üye bilgisi alınamadı."
                ),
                ephemeral=True,
            )

            return

        if (
            self.cog
            .discord_service
            .is_blocked_from_verification(
                member,
            )
        ):

            await interaction.response.send_message(
                embed=PAGEmbeds.error(
                    (
                        "Ally üyeleri verify "
                        "olamaz."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.send_modal(
            VerifyModal(
                self.cog,
            ),
        )


# ============================================================
# VERIFY COG
# ============================================================


class Verify(
    commands.Cog,
):
    """
    PAG Roblox Verification sistemi.

    Bu Cog şu anda:

        /verify
        !verify
        Verify Button
        Roblox Username Modal
        Roblox API
        Database
        Verified Role

    sistemlerini yönetir.

    Gelecekte:

        /unlink
        /roblox
        /roblox-profile
        /change-roblox

    gibi komutlar buraya eklenebilir.
    """

    # ========================================================
    # CONSTANTS
    # ========================================================

    VERIFIED_ROLE_NAME = (
        "Verified"
    )

    # ========================================================
    # INIT
    # ========================================================

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

        self.database = (
            database
        )

        self.logger = (
            logger
        )

        self._view_added = False

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(
        self,
    ) -> None:

        if self._view_added:

            return

        self.bot.add_view(
            VerifyView(
                self,
            ),
        )

        self._view_added = True

        self.logger.info(
            "Persistent verify view registered.",
        )

    # ========================================================
    # VERIFICATION
    # ========================================================

    async def verify_user(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> VerificationResult:
        """
        Roblox hesabını doğrular.

        Bu metod yalnızca verify işlemini yapar.
        Discord mesajı göndermeyi ayrı metotlara
        bırakır.

        Böylece gelecekte:

            - API
            - Web panel
            - Admin command
            - Automatic verification

        aynı sistemi kullanabilir.
        """

        member = (
            interaction.user
        )

        if not isinstance(
            member,
            discord.Member,
        ):

            raise RuntimeError(
                (
                    "Interaction user is "
                    "not a guild member."
                ),
            )

        # ====================================================
        # ALLY CHECK
        # ====================================================

        if (
            self.discord_service
            .is_blocked_from_verification(
                member,
            )
        ):

            raise PermissionError(
                (
                    "Member is blocked "
                    "from verification."
                ),
            )

        # ====================================================
        # ROBLOX USER
        # ====================================================

        user = (
            await self.roblox_service
            .get_user_by_username(
                username,
            )
        )

        # ====================================================
        # BANNED USER
        # ====================================================

        if user.is_banned:

            raise PermissionError(
                (
                    "Roblox user is banned."
                ),
            )

        # ====================================================
        # AVATAR
        # ====================================================

        avatar = (
            await self.roblox_service
            .get_avatar(
                user.id,
            )
        )

        # ====================================================
        # TIMESTAMP
        # ====================================================

        verified_at = (
            discord.utils.utcnow()
        )

        # ====================================================
        # DATABASE
        # ====================================================

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
                verified_at.isoformat(),
            ),
        )

        # ====================================================
        # VERIFIED ROLE
        # ====================================================

        verified_role = (
            self.discord_service
            .find_role(
                interaction.guild,
                self.VERIFIED_ROLE_NAME,
            )
        )

        if verified_role is None:

            raise RuntimeError(
                (
                    "Verified role was not found."
                ),
            )

        await self.discord_service.add_role(
            member,
            verified_role,
            reason=(
                "PAG Roblox verification"
            ),
        )

        # ====================================================
        # RESULT
        # ====================================================

        return VerificationResult(
            roblox_id=user.id,
            roblox_username=user.name,
            roblox_display_name=(
                user.display_name
            ),
            avatar_url=(
                avatar.image_url
            ),
            verified_at=verified_at,
        )

    # ========================================================
    # SUCCESS RESPONSE
    # ========================================================

    async def send_success_response(
        self,
        interaction: discord.Interaction,
        result: VerificationResult,
    ) -> None:

        embed = (
            PAGEmbeds.success(
                "Verify başarılı!",
            )
        )

        embed.title = (
            "✅ Verification Successful"
        )

        embed.description = (
            f"**Roblox hesabı:** "
            f"`{result.roblox_username}`\n"
            f"**Display Name:** "
            f"`{result.roblox_display_name}`\n"
            f"**Roblox ID:** "
            f"`{result.roblox_id}`"
        )

        if result.verified_at:

            embed.description += (
                "\n"
                f"**Verified:** "
                f"<t:{int(result.verified_at.timestamp())}:R>"
            )

        if result.avatar_url:

            embed.set_thumbnail(
                url=result.avatar_url,
            )

        await interaction.edit_original_response(
            embed=embed,
        )

    # ========================================================
    # VERIFY PANEL
    # ========================================================

    async def send_verify_panel(
        self,
        target: discord.abc.Messageable,
    ) -> None:

        embed = (
            PAGEmbeds.info(
                (
                    "Roblox hesabını Discord "
                    "hesabına bağlamak için "
                    "aşağıdaki butona bas."
                ),
            )
        )

        embed.title = (
            "🔗 PAG Verification"
        )

        embed.add_field(
            name="📌 Nasıl çalışır?",
            value=(
                "1. Verify butonuna bas.\n"
                "2. Roblox kullanıcı adını gir.\n"
                "3. Hesabın doğrulansın.\n"
                "4. Verified rolünü al."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛡️ Güvenlik",
            value=(
                "Yalnızca Roblox kullanıcı "
                "adını girmen yeterlidir."
            ),
            inline=False,
        )

        await target.send(
            embed=embed,
            view=VerifyView(
                self,
            ),
        )

    # ========================================================
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="verify",
        description=(
            "Open the PAG Roblox "
            "verification panel."
        ),
    )
    @app_commands.guild_only()
    async def verify_slash(
        self,
        interaction: discord.Interaction,
    ) -> None:

        self.logger.info(
            "Verify panel opened by %s (%s).",
            interaction.user,
            interaction.user.id,
        )

        await self.send_verify_panel(
            interaction,
        )

    # ========================================================
    # PREFIX COMMAND
    # ========================================================

    @commands.command(
        name="verify",
    )
    @commands.guild_only()
    async def verify_prefix(
        self,
        ctx: commands.Context,
    ) -> None:

        self.logger.info(
            "Prefix verify panel opened by %s (%s).",
            ctx.author,
            ctx.author.id,
        )

        await self.send_verify_panel(
            ctx,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Verify(
            bot,
            roblox_service=(
                bot.roblox_service
            ),
            discord_service=(
                bot.discord_service
            ),
            database=(
                bot.database
            ),
            logger=(
                bot.logger
            ),
        ),
    )