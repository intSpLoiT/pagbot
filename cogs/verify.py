from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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
# VERIFY CONFIGURATION
# ============================================================


class VerifyConfig:
    """
    Verify sistemi için merkezi ayarlar.

    İleride burada:
        - farklı kanal isimleri
        - farklı rol isimleri
        - farklı bildirim kullanıcıları
        - farklı mesaj ayarları

    kolayca değiştirilebilir.
    """

    VERIFIED_ROLE_NAME = "Verified"

    VERIFIED_CHANNEL_NAME = "‽verified"

    NOTIFICATION_USERNAME = "velgrath_"

    MODAL_TITLE = "PAG Verification"

    USERNAME_MIN_LENGTH = 3

    USERNAME_MAX_LENGTH = 20


# ============================================================
# VERIFY RESULT
# ============================================================


@dataclass(
    slots=True,
    frozen=True,
)
class VerificationResult:
    """
    Başarılı verification işleminin sonucu.
    """

    discord_member: discord.Member

    roblox_user: Any

    avatar: Any

    verified_role: discord.Role


# ============================================================
# VERIFY MODAL
# ============================================================


class VerifyModal(
    discord.ui.Modal,
):
    """
    Roblox username alma modalı.

    Modal submit edildiğinde:
        - Kullanıcıya ephemeral response gönderilir.
        - Kanalda gereksiz mesaj oluşturulmaz.
        - İşlem tamamlandığında DM gönderilir.
    """

    def __init__(
        self,
        cog: "Verify",
    ) -> None:

        super().__init__(
            title=VerifyConfig.MODAL_TITLE,
        )

        self.cog = cog

        self.username = discord.ui.TextInput(
            label="Roblox Username",
            placeholder=(
                "Roblox kullanıcı adını gir..."
            ),
            required=True,
            min_length=(
                VerifyConfig.USERNAME_MIN_LENGTH
            ),
            max_length=(
                VerifyConfig.USERNAME_MAX_LENGTH
            ),
        )

        self.add_item(
            self.username,
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Modal gönderildiğinde çalışır.

        İlk response ephemeral defer edilir.

        Böylece:
            - Kanalda mesaj oluşmaz.
            - Başarı/başarısızlık yalnızca kullanıcıya görünür.
        """

        await interaction.response.defer(
            ephemeral=True,
        )

        username = (
            self.username.value.strip()
        )

        if not username:

            await self.cog.respond_ephemeral_error(
                interaction,
                "Roblox kullanıcı adı boş bırakılamaz.",
            )

            return

        try:

            result = (
                await self.cog.process_verification(
                    interaction=interaction,
                    username=username,
                )
            )

        except RobloxNotFoundError:

            await self.cog.handle_verification_failure(
                interaction,
                "Bu Roblox hesabı bulunamadı.",
            )

            return

        except RobloxAPIError:

            self.cog.logger.exception(
                "Roblox API error during verification.",
            )

            await self.cog.handle_verification_failure(
                interaction,
                (
                    "Roblox API şu anda kullanılamıyor. "
                    "Lütfen daha sonra tekrar deneyin."
                ),
            )

            return

        except discord.Forbidden:

            self.cog.logger.exception(
                "Discord permission error during verification.",
            )

            await self.cog.handle_verification_failure(
                interaction,
                (
                    "Botun gerekli Discord izinleri yok. "
                    "Lütfen yöneticilere bildir."
                ),
            )

            return

        except discord.HTTPException:

            self.cog.logger.exception(
                "Discord HTTP error during verification.",
            )

            await self.cog.handle_verification_failure(
                interaction,
                (
                    "Discord ile iletişim kurulurken "
                    "bir hata oluştu."
                ),
            )

            return

        except Exception:

            self.cog.logger.exception(
                "Unexpected verification error.",
            )

            await self.cog.handle_verification_failure(
                interaction,
                (
                    "Verify işlemi sırasında beklenmeyen "
                    "bir hata oluştu."
                ),
            )

            return

        await self.cog.handle_verification_success(
            interaction,
            result,
        )


# ============================================================
# VERIFY VIEW
# ============================================================


class VerifyView(
    discord.ui.View,
):
    """
    Persistent verify paneli.
    """

    def __init__(
        self,
        cog: "Verify",
    ) -> None:

        super().__init__(
            timeout=None,
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

        Burada mesaj gönderilmez.

        Discord'un modal interaction response'u:
            response.send_modal(...)
        """

        if interaction.guild is None:

            await interaction.response.send_message(
                (
                    "Bu buton yalnızca sunucuda "
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
                    "Sunucu üye bilgilerin alınamadı."
                ),
                ephemeral=True,
            )

            return

        if (
            self.cog.discord_service
            .is_blocked_from_verification(
                member,
            )
        ):

            await interaction.response.send_message(
                embed=PAGEmbeds.error(
                    "Ally üyeleri verify olamaz.",
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

    Desteklenen:
        /verify
        !verify

    İşlem akışı:
        Roblox username
            ↓
        Roblox API
            ↓
        Verification kontrolleri
            ↓
        Database
            ↓
        Verified role
            ↓
        User DM
            ↓
        ‽verified log
            ↓
        velgrath_ notification
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        roblox_service: RobloxService,
        discord_service: Any,
        database: Any,
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
        """
        Persistent verify view'i kaydeder.
        """

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
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="verify",
        description=(
            "Link your Roblox account "
            "to your PAG profile."
        ),
    )
    @app_commands.guild_only()
    async def verify_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        /verify

        Verify panelini gönderir.

        Bu command:
            - Guild içinde çalışır.
            - Guild sync ile görünür.
            - Paneli kanal içine gönderir.
        """

        if interaction.guild is None:

            await interaction.response.send_message(
                (
                    "Bu komut yalnızca sunucuda "
                    "kullanılabilir."
                ),
                ephemeral=True,
            )

            return

        embed = PAGEmbeds.info(
            (
                "Roblox hesabını Discord hesabına "
                "bağlamak için aşağıdaki butona bas."
            ),
        )

        embed.title = (
            "🔗 PAG Verification"
        )

        await interaction.response.send_message(
            embed=embed,
            view=VerifyView(
                self,
            ),
        )

    # ========================================================
    # PREFIX COMMAND
    # ========================================================

    @commands.command(
        name="verify",
    )
    @commands.guild_only()
    async def verify_prefix_command(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        !verify

        Slash command ile aynı paneli gönderir.
        """

        embed = PAGEmbeds.info(
            (
                "Roblox hesabını Discord hesabına "
                "bağlamak için aşağıdaki butona bas."
            ),
        )

        embed.title = (
            "🔗 PAG Verification"
        )

        await ctx.send(
            embed=embed,
            view=VerifyView(
                self,
            ),
        )

    # ========================================================
    # MAIN VERIFICATION PROCESS
    # ========================================================

    async def process_verification(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> VerificationResult:
        """
        Ana verification akışı.

        Bu fonksiyon mümkün olduğunca
        küçük kontrol fonksiyonlarına bölünmüştür.
        """

        member = (
            await self.require_guild_member(
                interaction,
            )
        )

        await self.validate_member(
            member,
        )

        username = (
            self.normalize_username(
                username,
            )
        )

        roblox_user = (
            await self.fetch_roblox_user(
                username,
            )
        )

        await self.validate_roblox_user(
            roblox_user,
        )

        await self.check_existing_discord_verification(
            member.id,
        )

        await self.check_roblox_account_ownership(
            roblox_user.id,
            member.id,
        )

        avatar = (
            await self.fetch_avatar_safely(
                roblox_user.id,
            )
        )

        verified_role = (
            await self.get_verified_role(
                interaction.guild,
            )
        )

        await self.save_verification(
            member=member,
            roblox_user=roblox_user,
        )

        await self.assign_verified_role(
            member=member,
            role=verified_role,
        )

        return VerificationResult(
            discord_member=member,
            roblox_user=roblox_user,
            avatar=avatar,
            verified_role=verified_role,
        )

    # ========================================================
    # MEMBER VALIDATION
    # ========================================================

    async def require_guild_member(
        self,
        interaction: discord.Interaction,
    ) -> discord.Member:
        """
        Interaction kullanıcısının guild member
        olduğundan emin olur.
        """

        if interaction.guild is None:

            raise RuntimeError(
                "Verification requires a guild.",
            )

        member = (
            interaction.user
        )

        if not isinstance(
            member,
            discord.Member,
        ):

            raise RuntimeError(
                "Interaction user is not a guild member.",
            )

        return member

    async def validate_member(
        self,
        member: discord.Member,
    ) -> None:
        """
        Üyenin verification yapmasına izin
        verilip verilmediğini kontrol eder.
        """

        if (
            self.discord_service
            .is_blocked_from_verification(
                member,
            )
        ):

            raise PermissionError(
                "Member is blocked from verification.",
            )

    # ========================================================
    # USERNAME
    # ========================================================

    @staticmethod
    def normalize_username(
        username: str,
    ) -> str:
        """
        Username'i normalize eder.
        """

        username = (
            username.strip()
        )

        if not username:

            raise ValueError(
                "Username cannot be empty.",
            )

        return username

    # ========================================================
    # ROBLOX
    # ========================================================

    async def fetch_roblox_user(
        self,
        username: str,
    ) -> Any:
        """
        Roblox kullanıcısını güvenli şekilde bulur.
        """

        return (
            await self.roblox_service
            .get_user_by_username(
                username,
            )
        )

    async def validate_roblox_user(
        self,
        roblox_user: Any,
    ) -> None:
        """
        Roblox hesabı için temel kontroller.
        """

        if roblox_user is None:

            raise RobloxNotFoundError(
                "Roblox user is empty.",
            )

        if roblox_user.id <= 0:

            raise RobloxAPIError(
                "Invalid Roblox user ID.",
            )

        if roblox_user.is_banned:

            raise PermissionError(
                "Roblox account is banned.",
            )

    async def fetch_avatar_safely(
        self,
        roblox_id: int,
    ) -> Any | None:
        """
        Avatar alınamazsa verification işlemini
        tamamen bozmaz.

        Avatar yalnızca görsel bilgidir.
        """

        try:

            return (
                await self.roblox_service
                .get_avatar(
                    roblox_id,
                )
            )

        except (
            RobloxNotFoundError,
            RobloxAPIError,
        ):

            self.logger.warning(
                (
                    "Avatar could not be fetched "
                    "for Roblox user %s."
                ),
                roblox_id,
            )

            return None

    # ========================================================
    # DATABASE CHECKS
    # ========================================================

    async def check_existing_discord_verification(
        self,
        discord_id: int,
    ) -> None:
        """
        Discord hesabının mevcut verify durumunu
        kontrol eder.

        Aynı Discord hesabı yeniden verify olabilir.
        Bu durumda kayıt güncellenecektir.
        """

        row = await self.database.fetchone(
            """
            SELECT
                discord_id,
                roblox_id,
                roblox_username
            FROM verifications
            WHERE discord_id = ?
            LIMIT 1
            """,
            (
                discord_id,
            ),
        )

        if row is None:

            return

        self.logger.info(
            (
                "Existing verification found "
                "for Discord user %s. "
                "Existing record will be replaced."
            ),
            discord_id,
        )

    async def check_roblox_account_ownership(
        self,
        roblox_id: int,
        discord_id: int,
    ) -> None:
        """
        Aynı Roblox hesabının başka bir Discord
        hesabına bağlı olup olmadığını kontrol eder.

        Bu önemli bir anti-abuse kontrolüdür.
        """

        row = await self.database.fetchone(
            """
            SELECT
                discord_id,
                roblox_id,
                roblox_username
            FROM verifications
            WHERE roblox_id = ?
            LIMIT 1
            """,
            (
                roblox_id,
            ),
        )

        if row is None:

            return

        existing_discord_id = (
            int(
                row["discord_id"],
            )
        )

        if existing_discord_id == discord_id:

            return

        raise PermissionError(
            (
                "This Roblox account is already "
                "linked to another Discord account."
            ),
        )

    # ========================================================
    # ROLE
    # ========================================================

    async def get_verified_role(
        self,
        guild: discord.Guild | None,
    ) -> discord.Role:
        """
        Verified rolünü bulur.
        """

        if guild is None:

            raise RuntimeError(
                "Guild is required.",
            )

        role = (
            self.discord_service
            .find_role(
                guild,
                VerifyConfig.VERIFIED_ROLE_NAME,
            )
        )

        if role is None:

            raise RuntimeError(
                (
                    "Verified role was not found: "
                    f"{VerifyConfig.VERIFIED_ROLE_NAME}"
                ),
            )

        return role

    async def assign_verified_role(
        self,
        member: discord.Member,
        role: discord.Role,
    ) -> None:
        """
        Verified rolünü güvenli şekilde verir.
        """

        if role in member.roles:

            self.logger.info(
                (
                    "Member %s already has "
                    "Verified role."
                ),
                member.id,
            )

            return

        await self.discord_service.add_role(
            member,
            role,
            reason=(
                "PAG Roblox verification"
            ),
        )

     # ========================================================
    # DATABASE SAVE
    # ========================================================

    async def save_verification(
        self,
        member: discord.Member,
        roblox_user: Any,
    ) -> None:
        """
        Verification kaydını database'e yazar.

        INSERT OR REPLACE:
            - Aynı Discord hesabının eski kaydını günceller.
            - Yeni hesabı ekler.
        """

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
                roblox_user.id,
                roblox_user.name,
                discord.utils.utcnow().isoformat(),
            ),
        )

    # ========================================================
    # SUCCESS HANDLER
    # ========================================================

    async def handle_verification_success(
        self,
        interaction: discord.Interaction,
        result: VerificationResult,
    ) -> None:
        """
        Başarılı verification işlemini yönetir.

        1. Kullanıcıya ephemeral başarı mesajı
        2. Kullanıcıya DM
        3. ‽verified kanalına log
        4. velgrath_ kullanıcısına bildirim
        """

        roblox_user = (
            result.roblox_user
        )

        embed = PAGEmbeds.success(
            "Verify başarılı!",
        )

        embed.title = (
            "✅ Verification Successful"
        )

        embed.description = (
            f"**Roblox hesabı:** "
            f"`{roblox_user.name}`\n"
            f"**Display Name:** "
            f"`{roblox_user.display_name}`\n"
            f"**Roblox ID:** "
            f"`{roblox_user.id}`"
        )

        if result.avatar is not None:

            embed.set_thumbnail(
                url=result.avatar.image_url,
            )

        # ----------------------------------------------------
        # USER EPHEMERAL RESPONSE
        # ----------------------------------------------------

        await self.respond_ephemeral_success(
            interaction,
            embed,
        )

        # ----------------------------------------------------
        # USER DM
        # ----------------------------------------------------

        await self.send_user_dm(
            result,
        )

        # ----------------------------------------------------
        # VERIFIED CHANNEL LOG
        # ----------------------------------------------------

        await self.send_verification_log(
            result,
        )

        # ----------------------------------------------------
        # OWNER NOTIFICATION
        # ----------------------------------------------------

        await self.notify_verification_owner(
            result,
        )

        self.logger.info(
            (
                "Verification completed: "
                "Discord=%s Roblox=%s"
            ),
            result.discord_member.id,
            result.roblox_user.id,
        )

    # ========================================================
    # FAILURE HANDLER
    # ========================================================

    async def handle_verification_failure(
        self,
        interaction: discord.Interaction,
        message: str,
    ) -> None:
        """
        Tüm başarısız verification işlemlerinde
        ortak hata akışı.
        """

        embed = PAGEmbeds.error(
            message,
        )

        try:

            await self.respond_ephemeral_error(
                interaction,
                message,
            )

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to send ephemeral "
                    "verification error."
                ),
            )

        # Hata logu ileride buraya
        # database audit sistemi eklenerek
        # genişletilebilir.

    # ========================================================
    # EPHEMERAL SUCCESS
    # ========================================================

    async def respond_ephemeral_success(
        self,
        interaction: discord.Interaction,
        embed: discord.Embed,
    ) -> None:
        """
        Başarı mesajını yalnızca işlemi yapan
        kullanıcıya gösterir.
        """

        if interaction.response.is_done():

            await interaction.edit_original_response(
                embed=embed,
            )

            return

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # EPHEMERAL ERROR
    # ========================================================

    async def respond_ephemeral_error(
        self,
        interaction: discord.Interaction,
        message: str,
    ) -> None:
        """
        Hata mesajını yalnızca kullanıcıya gösterir.
        """

        embed = PAGEmbeds.error(
            message,
        )

        if interaction.response.is_done():

            await interaction.edit_original_response(
                embed=embed,
            )

            return

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # USER DM
    # ========================================================

    async def send_user_dm(
        self,
        result: VerificationResult,
    ) -> None:
        """
        Verify yapan kullanıcıya DM gönderir.

        DM kapalıysa verification başarısız sayılmaz.
        """

        member = (
            result.discord_member
        )

        roblox_user = (
            result.roblox_user
        )

        embed = PAGEmbeds.success(
            (
                "Roblox hesabın başarıyla "
                "Discord hesabına bağlandı."
            ),
        )

        embed.title = (
            "🔗 PAG Verification Complete"
        )

        embed.description = (
            f"**Roblox hesabı:** "
            f"`{roblox_user.name}`\n"
            f"**Display Name:** "
            f"`{roblox_user.display_name}`\n"
            f"**Roblox ID:** "
            f"`{roblox_user.id}`"
        )

        try:

            await member.send(
                embed=embed,
            )

        except discord.Forbidden:

            self.logger.warning(
                (
                    "Could not DM verified user %s. "
                    "DMs may be disabled."
                ),
                member.id,
            )

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to send verification DM "
                    "to user %s."
                ),
                member.id,
            )

    # ========================================================
    # VERIFIED CHANNEL
    # ========================================================

    async def send_verification_log(
        self,
        result: VerificationResult,
    ) -> None:
        """
        ‽verified kanalına verification logu gönderir.
        """

        guild = (
            result.discord_member.guild
        )

        channel = (
            discord.utils.get(
                guild.text_channels,
                name=(
                    VerifyConfig
                    .VERIFIED_CHANNEL_NAME
                ),
            )
        )

        if channel is None:

            self.logger.warning(
                (
                    "Verification channel not found: %s"
                ),
                VerifyConfig.VERIFIED_CHANNEL_NAME,
            )

            return

        roblox_user = (
            result.roblox_user
        )

        embed = discord.Embed(
            title=(
                "✅ New Verification"
            ),
            description=(
                f"**Discord:** "
                f"{result.discord_member.mention}\n"
                f"**Roblox:** "
                f"`{roblox_user.name}`\n"
                f"**Display Name:** "
                f"`{roblox_user.display_name}`\n"
                f"**Roblox ID:** "
                f"`{roblox_user.id}`"
            ),
            timestamp=(
                discord.utils.utcnow()
            ),
        )

        if result.avatar is not None:

            embed.set_thumbnail(
                url=result.avatar.image_url,
            )

        try:

            await channel.send(
                embed=embed,
            )

        except discord.Forbidden:

            self.logger.exception(
                (
                    "Missing permission to send "
                    "verification log."
                ),
            )

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to send verification "
                    "channel log."
                ),
            )

    # ========================================================
    # OWNER NOTIFICATION
    # ========================================================

    async def notify_verification_owner(
        self,
        result: VerificationResult,
    ) -> None:
        """
        velgrath_ adlı kullanıcıya DM gönderir.

        Kullanıcı ID'si sabitlenmediği için:
            - Önce guild cache'indeki üyeler aranır.
            - Username veya global name kontrol edilir.
        """

        owner = (
            self.find_notification_user(
                result.discord_member.guild,
            )
        )

        if owner is None:

            self.logger.warning(
                (
                    "Verification notification user "
                    "not found: %s"
                ),
                VerifyConfig.NOTIFICATION_USERNAME,
            )

            return

        roblox_user = (
            result.roblox_user
        )

        embed = discord.Embed(
            title=(
                "🔔 PAG Verification Notification"
            ),
            description=(
                f"**Discord User:** "
                f"{result.discord_member} "
                f"({result.discord_member.id})\n"
                f"**Roblox Username:** "
                f"`{roblox_user.name}`\n"
                f"**Roblox ID:** "
                f"`{roblox_user.id}`"
            ),
            timestamp=(
                discord.utils.utcnow()
            ),
        )

        if result.avatar is not None:

            embed.set_thumbnail(
                url=result.avatar.image_url,
            )

        try:

            await owner.send(
                embed=embed,
            )

        except discord.Forbidden:

            self.logger.warning(
                (
                    "Could not DM notification "
                    "user %s."
                ),
                owner.id,
            )

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to send verification "
                    "notification."
                ),
            )

    # ========================================================
    # FIND NOTIFICATION USER
    # ========================================================

    @staticmethod
    def find_notification_user(
        guild: discord.Guild,
    ) -> discord.Member | None:
        """
        velgrath_ kullanıcısını guild cache'inde arar.

        Öncelik:
            1. username
            2. global_name
            3. display_name
        """

        target = (
            VerifyConfig
            .NOTIFICATION_USERNAME
            .casefold()
        )

        for member in guild.members:

            candidates = (
                member.name,
                member.global_name,
                member.display_name,
            )

            for candidate in candidates:

                if (
                    candidate is not None
                    and candidate.casefold()
                    == target
                ):

                    return member

        return None


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Verify Cog setup.
    """

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