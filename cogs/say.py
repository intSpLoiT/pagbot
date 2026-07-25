from __future__ import annotations

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
# CONSTANTS
# ============================================================


MAX_TITLE_LENGTH = 256

MAX_MAIN_TEXT_LENGTH = 4000

MAX_EXTRA_TEXT_LENGTH = 1000

MAX_ROBLOX_USERNAME_LENGTH = 20


# ============================================================
# DATA MODEL
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class SayMessageData:
    """
    /say mesajı için normalize edilmiş veri modeli.
    """

    title: str

    main_text: str

    second_text: Optional[str]

    third_text: Optional[str]

    roblox_username: Optional[str]


# ============================================================
# SAY MODAL
# ============================================================


class SayModal(discord.ui.Modal):
    """
    PAG Say mesajı oluşturma paneli.

    Alanlar:

        1. Başlık
        2. Ana yazı
        3. Ek yazı 1
        4. Ek yazı 2
        5. Roblox kullanıcı adı

    Roblox kullanıcı adı girilirse:

        Username
            ↓
        RobloxUser
            ↓
        Avatar
            ↓
        Embed Thumbnail
    """

    def __init__(
        self,
        cog: "Say",
    ) -> None:

        super().__init__(
            title="PAG Say Panel",
        )

        self.cog = cog

        # ====================================================
        # TITLE
        # ====================================================

        self.title_input = discord.ui.TextInput(
            label="Başlık",
            placeholder=(
                "Örn: 🏆 Haftanın Oyuncusu"
            ),
            required=True,
            min_length=1,
            max_length=MAX_TITLE_LENGTH,
        )

        # ====================================================
        # MAIN TEXT
        # ====================================================

        self.main_text_input = discord.ui.TextInput(
            label="Ana Yazı",
            placeholder=(
                "Ana duyuru metnini yaz..."
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=1,
            max_length=MAX_MAIN_TEXT_LENGTH,
        )

        # ====================================================
        # SECOND TEXT
        # ====================================================

        self.second_text_input = discord.ui.TextInput(
            label="Ek Yazı 1",
            placeholder=(
                "İsteğe bağlı ek yazı..."
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=MAX_EXTRA_TEXT_LENGTH,
        )

        # ====================================================
        # THIRD TEXT
        # ====================================================

        self.third_text_input = discord.ui.TextInput(
            label="Ek Yazı 2",
            placeholder=(
                "İsteğe bağlı ek yazı..."
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=MAX_EXTRA_TEXT_LENGTH,
        )

        # ====================================================
        # ROBLOX USERNAME
        # ====================================================

        self.roblox_username_input = discord.ui.TextInput(
            label="Roblox Kullanıcı Adı",
            placeholder=(
                "Avatar eklemek için isteğe bağlı..."
            ),
            required=False,
            max_length=MAX_ROBLOX_USERNAME_LENGTH,
        )

        # ====================================================
        # REGISTER INPUTS
        # ====================================================

        self.add_item(
            self.title_input,
        )

        self.add_item(
            self.main_text_input,
        )

        self.add_item(
            self.second_text_input,
        )

        self.add_item(
            self.third_text_input,
        )

        self.add_item(
            self.roblox_username_input,
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Modal submit işlemi.
        """

        # ----------------------------------------------------
        # IMMEDIATE ACKNOWLEDGEMENT
        # ----------------------------------------------------

        try:

            await interaction.response.defer(
                ephemeral=True,
            )

        except discord.InteractionResponded:

            return

        except discord.HTTPException:

            self.cog.logger.exception(
                "Failed to defer /say modal interaction.",
            )

            return

        # ----------------------------------------------------
        # NORMALIZE
        # ----------------------------------------------------

        data = SayMessageData(
            title=(
                self.title_input.value.strip()
            ),

            main_text=(
                self.main_text_input.value.strip()
            ),

            second_text=(
                self.second_text_input.value.strip()
                or None
            ),

            third_text=(
                self.third_text_input.value.strip()
                or None
            ),

            roblox_username=(
                self.roblox_username_input.value.strip()
                or None
            ),
        )

        # ----------------------------------------------------
        # VALIDATE
        # ----------------------------------------------------

        validation_error = (
            self.cog.validate_message_data(
                data,
            )
        )

        if validation_error:

            await self.cog.safe_followup(
                interaction,
                content=(
                    f"❌ {validation_error}"
                ),
            )

            return

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        try:

            await self.cog.send_message(
                interaction=interaction,
                data=data,
            )

        except PermissionError:

            await self.cog.safe_followup(
                interaction,
                content=(
                    "❌ Botun bu kanala mesaj gönderme "
                    "yetkisi bulunmuyor."
                ),
            )

        except discord.Forbidden:

            await self.cog.safe_followup(
                interaction,
                content=(
                    "❌ Discord botun bu mesajı göndermesine "
                    "izin vermedi."
                ),
            )

        except discord.NotFound:

            await self.cog.safe_followup(
                interaction,
                content=(
                    "❌ Kanal veya interaction artık "
                    "bulunamıyor."
                ),
            )

        except discord.HTTPException:

            self.cog.logger.exception(
                "Discord API error while executing /say.",
            )

            await self.cog.safe_followup(
                interaction,
                content=(
                    "❌ Discord API hatası oluştu."
                ),
            )

        except Exception:

            self.cog.logger.exception(
                "Unexpected error while executing /say.",
            )

            await self.cog.safe_followup(
                interaction,
                content=(
                    "❌ Beklenmeyen bir hata oluştu."
                ),
            )


# ============================================================
# SAY COG
# ============================================================


class Say(commands.Cog):
    """
    PAG Say sistemi.

    Slash:

        /say

    Prefix:

        !say

    /say:

        Admin
            ↓
        Modal
            ↓
        Validation
            ↓
        Roblox enrichment
            ↓
        Embed
            ↓
        @everyone
            ↓
        Success response

    Roblox API başarısız olursa
    ana mesaj yine gönderilir.
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
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="say",
        description=(
            "PAG adına özel bir duyuru mesajı oluşturur."
        ),
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(
        administrator=True,
    )
    async def say(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        /say komutu.

        Discord'da slash command olarak görünür.
        """

        # ----------------------------------------------------
        # GUILD CHECK
        # ----------------------------------------------------

        if interaction.guild is None:

            await self.safe_initial_response(
                interaction,
                content=(
                    "❌ Bu komut yalnızca sunucularda "
                    "kullanılabilir."
                ),
            )

            return

        # ----------------------------------------------------
        # MEMBER CHECK
        # ----------------------------------------------------

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):

            await self.safe_initial_response(
                interaction,
                content=(
                    "❌ Sunucu üye bilgisi alınamadı."
                ),
            )

            return

        # ----------------------------------------------------
        # ADMIN CHECK
        # ----------------------------------------------------

        if not member.guild_permissions.administrator:

            await self.safe_initial_response(
                interaction,
                content=(
                    "❌ Bu komutu yalnızca sunucu "
                    "yöneticileri kullanabilir."
                ),
            )

            self.logger.warning(
                (
                    "Unauthorized /say attempt: "
                    "user=%s guild=%s"
                ),
                member.id,
                interaction.guild.id,
            )

            return

        # ----------------------------------------------------
        # OPEN MODAL
        # ----------------------------------------------------

        try:

            await interaction.response.send_modal(
                SayModal(
                    self,
                ),
            )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to open SayModal.",
            )

            if not interaction.response.is_done():

                await self.safe_initial_response(
                    interaction,
                    content=(
                        "❌ Say paneli açılırken "
                        "bir hata oluştu."
                    ),
                )

    # ========================================================
    # PREFIX COMMAND
    # ========================================================

    @commands.command(
        name="say",
    )
    @commands.guild_only()
    async def say_prefix(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        !say komutu.

        Prefix komutları doğrudan Modal açamaz.
        Bu nedenle kullanıcıya slash command kullanması
        gerektiğini bildirir.

        Asıl panel:

            /say
        """

        if ctx.guild is None:

            await ctx.send(
                "❌ Bu komut yalnızca sunucularda "
                "kullanılabilir.",
            )

            return

        if not isinstance(
            ctx.author,
            discord.Member,
        ):

            return

        if not ctx.author.guild_permissions.administrator:

            await ctx.send(
                "❌ Bu komutu yalnızca sunucu "
                "yöneticileri kullanabilir.",
            )

            return

        await ctx.send(
            (
                "📢 **PAG Say Paneli**\n\n"
                "Say mesajı oluşturmak için "
                "slash command kullan:\n\n"
                "`/say`"
            ),
            delete_after=10,
        )

    # ========================================================
    # VALIDATE
    # ========================================================

    def validate_message_data(
        self,
        data: SayMessageData,
    ) -> Optional[str]:
        """
        Kullanıcı verilerini doğrular.
        """

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        if not data.title:

            return (
                "Başlık boş bırakılamaz."
            )

        if len(data.title) > MAX_TITLE_LENGTH:

            return (
                "Başlık izin verilen maksimum "
                "uzunluğu aşıyor."
            )

        # ----------------------------------------------------
        # MAIN TEXT
        # ----------------------------------------------------

        if not data.main_text:

            return (
                "Ana yazı boş bırakılamaz."
            )

        if len(data.main_text) > MAX_MAIN_TEXT_LENGTH:

            return (
                "Ana yazı çok uzun."
            )

        # ----------------------------------------------------
        # SECOND TEXT
        # ----------------------------------------------------

        if data.second_text:

            if len(data.second_text) > MAX_EXTRA_TEXT_LENGTH:

                return (
                    "Ek Yazı 1 çok uzun."
                )

        # ----------------------------------------------------
        # THIRD TEXT
        # ----------------------------------------------------

        if data.third_text:

            if len(data.third_text) > MAX_EXTRA_TEXT_LENGTH:

                return (
                    "Ek Yazı 2 çok uzun."
                )

        # ----------------------------------------------------
        # ROBLOX USERNAME
        # ----------------------------------------------------

        if data.roblox_username:

            if len(data.roblox_username) > (
                MAX_ROBLOX_USERNAME_LENGTH
            ):

                return (
                    "Roblox kullanıcı adı çok uzun."
                )

        return None

    # ========================================================
    # SEND MESSAGE
    # ========================================================

    async def send_message(
        self,
        *,
        interaction: discord.Interaction,
        data: SayMessageData,
    ) -> None:
        """
        Say mesajını oluşturur ve gönderir.
        """

        # ----------------------------------------------------
        # CHANNEL
        # ----------------------------------------------------

        channel = interaction.channel

        if channel is None:

            raise PermissionError(
                "Interaction channel unavailable.",
            )

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):

            raise PermissionError(
                "Channel is not messageable.",
            )

        # ----------------------------------------------------
        # BUILD EMBED
        # ----------------------------------------------------

        embed = await self.build_embed(
            data,
        )

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        await channel.send(
            content="@everyone",
            embed=embed,
            allowed_mentions=(
                discord.AllowedMentions(
                    everyone=True,
                )
            ),
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        await self.safe_followup(
            interaction,
            content=(
                "✅ Mesaj başarıyla gönderildi."
            ),
        )

        self.logger.info(
            (
                "Say message sent: "
                "user=%s guild=%s channel=%s"
            ),
            interaction.user.id,
            interaction.guild.id
            if interaction.guild
            else None,
            channel.id,
        )

    # ========================================================
    # BUILD EMBED
    # ========================================================

    async def build_embed(
        self,
        data: SayMessageData,
    ) -> discord.Embed:
        """
        Embed oluşturur.
        """

        embed = discord.Embed(
            title=data.title,
            description=data.main_text,
            timestamp=discord.utils.utcnow(),
        )

        # ----------------------------------------------------
        # EXTRA TEXT 1
        # ----------------------------------------------------

        if data.second_text:

            embed.add_field(
                name="\u200b",
                value=data.second_text,
                inline=False,
            )

        # ----------------------------------------------------
        # EXTRA TEXT 2
        # ----------------------------------------------------

        if data.third_text:

            embed.add_field(
                name="\u200b",
                value=data.third_text,
                inline=False,
            )

        # ----------------------------------------------------
        # ROBLOX ENRICHMENT
        # ----------------------------------------------------

        if data.roblox_username:

            await self.add_roblox_avatar(
                embed=embed,
                username=data.roblox_username,
            )

        return embed

    # ========================================================
    # ROBLOX AVATAR
    # ========================================================

    async def add_roblox_avatar(
        self,
        *,
        embed: discord.Embed,
        username: str,
    ) -> None:
        """
        Roblox avatarını eklemeyi dener.

        ÖNEMLİ:

        Roblox API başarısız olursa
        ana mesajın gönderilmesi engellenmez.
        """

        try:

            user = (
                await self.roblox_service
                .get_user_by_username(
                    username,
                )
            )

            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

            if avatar.image_url:

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
                (
                    "Roblox user not found "
                    "for /say: %s"
                ),
                username,
            )

        except RobloxAPIError:

            self.logger.warning(
                (
                    "Roblox API failed "
                    "while enriching /say."
                ),
                exc_info=True,
            )

        except Exception:

            self.logger.exception(
                (
                    "Unexpected Roblox error "
                    "while enriching /say."
                ),
            )

    # ========================================================
    # SAFE INITIAL RESPONSE
    # ========================================================

    async def safe_initial_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
        """
        Henüz cevap verilmemiş interaction için güvenli cevap.
        """

        try:

            if interaction.response.is_done():

                await self.safe_followup(
                    interaction,
                    content=content,
                )

                return

            await interaction.response.send_message(
                content,
                ephemeral=True,
            )

        except discord.NotFound:

            self.logger.warning(
                "Interaction expired before response.",
            )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to send initial interaction response.",
            )

    # ========================================================
    # SAFE FOLLOWUP
    # ========================================================

    async def safe_followup(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
        """
        Defer edilmiş interaction'a güvenli cevap verir.
        """

        try:

            await interaction.followup.send(
                content=content,
                ephemeral=True,
            )

        except discord.NotFound:

            self.logger.warning(
                "Interaction expired before followup.",
            )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to send interaction followup.",
            )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    @say.error
    async def say_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """
        Prefix command hata yöneticisi.
        """

        if isinstance(
            error,
            commands.NoPrivateMessage,
        ):

            return

        if isinstance(
            error,
            commands.MissingPermissions,
        ):

            await ctx.send(
                (
                    "❌ Bu komutu kullanmak için "
                    "yönetici yetkisine sahip olmalısın."
                ),
                delete_after=8,
            )

            return

        self.logger.exception(
            "Prefix /say error: %s",
            error,
        )

        try:

            await ctx.send(
                (
                    "❌ /say çalıştırılırken "
                    "beklenmeyen bir hata oluştu."
                ),
                delete_after=8,
            )

        except discord.HTTPException:

            self.logger.exception(
                "Failed to send prefix /say error.",
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
        ),
    )