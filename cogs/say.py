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
    Say mesajının normalize edilmiş verisi.

    Gelecekte buraya:

        - color
        - image_url
        - footer
        - mention_type
        - target_channel_id

    gibi alanlar eklenebilir.
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
    PAG yayın mesajı oluşturma modalı.

    Kullanıcıdan:

        - Başlık
        - Ana yazı
        - Ek yazı 1
        - Ek yazı 2
        - Roblox kullanıcı adı

    alır.
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

        self.main_text = discord.ui.TextInput(
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

        self.second_text = discord.ui.TextInput(
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

        self.third_text = discord.ui.TextInput(
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

        self.roblox_username = discord.ui.TextInput(
            label="Roblox Kullanıcı Adı",
            placeholder=(
                "Avatar eklemek için isteğe bağlı..."
            ),
            required=False,
            max_length=MAX_ROBLOX_USERNAME_LENGTH,
        )

        # ====================================================
        # ADD COMPONENTS
        # ====================================================

        self.add_item(
            self.title_input,
        )

        self.add_item(
            self.main_text,
        )

        self.add_item(
            self.second_text,
        )

        self.add_item(
            self.third_text,
        )

        self.add_item(
            self.roblox_username,
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Modal gönderildiğinde çalışır.
        """

        # ----------------------------------------------------
        # IMMEDIATE RESPONSE
        # ----------------------------------------------------

        try:

            await interaction.response.defer(
                ephemeral=True,
            )

        except discord.InteractionResponded:

            return

        except discord.HTTPException:

            self.cog.logger.exception(
                "Failed to acknowledge /say modal.",
            )

            return

        # ----------------------------------------------------
        # NORMALIZE INPUT
        # ----------------------------------------------------

        data = SayMessageData(
            title=self.title_input.value.strip(),

            main_text=self.main_text.value.strip(),

            second_text=(
                self.second_text.value.strip()
                or None
            ),

            third_text=(
                self.third_text.value.strip()
                or None
            ),

            roblox_username=(
                self.roblox_username.value.strip()
                or None
            ),
        )

        # ----------------------------------------------------
        # VALIDATE INPUT
        # ----------------------------------------------------

        validation_error = (
            self.cog.validate_message_data(
                data,
            )
        )

        if validation_error:

            await self.cog.safe_edit_response(
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

            await self.cog.safe_edit_response(
                interaction,
                content=(
                    "❌ Botun bu kanala mesaj gönderme "
                    "yetkisi yok."
                ),
            )

        except discord.Forbidden:

            await self.cog.safe_edit_response(
                interaction,
                content=(
                    "❌ Discord botun bu mesajı göndermesine "
                    "izin vermedi."
                ),
            )

        except discord.NotFound:

            await self.cog.safe_edit_response(
                interaction,
                content=(
                    "❌ Kanal veya Discord mesajı artık "
                    "bulunamıyor."
                ),
            )

        except discord.HTTPException:

            self.cog.logger.exception(
                "Discord API error while executing /say.",
            )

            await self.cog.safe_edit_response(
                interaction,
                content=(
                    "❌ Discord API hatası oluştu. "
                    "Lütfen tekrar deneyin."
                ),
            )

        except Exception:

            self.cog.logger.exception(
                "Unexpected error while executing /say.",
            )

            await self.cog.safe_edit_response(
                interaction,
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

    Mimari:

        /say
          ↓
        Permission Check
          ↓
        Modal
          ↓
        Input Validation
          ↓
        Roblox Enrichment
          ↓
        Embed Builder
          ↓
        Discord Message Sender
          ↓
        Private Result
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
        description=(
            "PAG adına özel bir mesaj gönderir."
        ),
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

        # ----------------------------------------------------
        # GUILD CHECK
        # ----------------------------------------------------

        if interaction.guild is None:

            await self.safe_send_response(
                interaction,
                content=(
                    "❌ Bu komut yalnızca sunucuda "
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

            await self.safe_send_response(
                interaction,
                content=(
                    "❌ Sunucu üye bilgisi alınamadı."
                ),
            )

            return

        # ----------------------------------------------------
        # PERMISSION CHECK
        # ----------------------------------------------------

        if not member.guild_permissions.administrator:

            await self.safe_send_response(
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

                await self.safe_send_response(
                    interaction,
                    content=(
                        "❌ Say paneli açılırken "
                        "bir hata oluştu."
                    ),
                )

    # ========================================================
    # VALIDATE MESSAGE DATA
    # ========================================================

    def validate_message_data(
        self,
        data: SayMessageData,
    ) -> Optional[str]:
        """
        Say mesajı verilerini doğrular.

        Gelecekte yeni validation kuralları
        buraya eklenebilir.
        """

        if not data.title:

            return (
                "Başlık boş bırakılamaz."
            )

        if not data.main_text:

            return (
                "Ana yazı boş bırakılamaz."
            )

        if (
            len(data.title)
            > MAX_TITLE_LENGTH
        ):

            return (
                "Başlık çok uzun."
            )

        if (
            len(data.main_text)
            > MAX_MAIN_TEXT_LENGTH
        ):

            return (
                "Ana yazı çok uzun."
            )

        if data.second_text:

            if (
                len(data.second_text)
                > MAX_EXTRA_TEXT_LENGTH
            ):

                return (
                    "Ek Yazı 1 çok uzun."
                )

        if data.third_text:

            if (
                len(data.third_text)
                > MAX_EXTRA_TEXT_LENGTH
            ):

                return (
                    "Ek Yazı 2 çok uzun."
                )

        if data.roblox_username:

            if (
                len(data.roblox_username)
                > MAX_ROBLOX_USERNAME_LENGTH
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
        Say mesajının ana akışını yönetir.
        """

        # ----------------------------------------------------
        # CHANNEL
        # ----------------------------------------------------

        channel = interaction.channel

        if channel is None:

            raise PermissionError(
                "Interaction channel is unavailable."
            )

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):

            raise PermissionError(
                "Interaction channel is not messageable."
            )

        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = await self.build_embed(
            data,
        )

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        try:

            await channel.send(
                content="@everyone",
                embed=embed,
                allowed_mentions=(
                    discord.AllowedMentions(
                        everyone=True,
                    )
                ),
            )

        except discord.Forbidden:

            self.logger.error(
                (
                    "Bot lacks permission to send "
                    "message in channel=%s"
                ),
                channel.id,
            )

            raise

        except discord.HTTPException:

            self.logger.exception(
                (
                    "Discord HTTP error while sending "
                    "say message."
                ),
            )

            raise

        # ----------------------------------------------------
        # PRIVATE RESULT
        # ----------------------------------------------------

        await self.safe_edit_response(
            interaction,
            content=(
                "✅ Mesaj başarıyla gönderildi."
            ),
        )

        self.logger.info(
            (
                "Say message sent successfully: "
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
        Say embed'ini oluşturur.
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
        # ROBLOX DATA
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
        Roblox avatarını embed'e eklemeyi dener.

        Roblox başarısız olursa ana mesajın
        gönderilmesi engellenmez.
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
                    "for /say."
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
    # SAFE SEND RESPONSE
    # ========================================================

    async def safe_send_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
        """
        Interaction'a güvenli şekilde cevap verir.
        """

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    content,
                    ephemeral=True,
                )

            else:

                await interaction.response.send_message(
                    content,
                    ephemeral=True,
                )
        except discord.HTTPException:

            self.logger.exception(
                (
                    "Failed to edit original "
                    "interaction response."
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
        Say(
            bot,
            roblox_service=bot.roblox_service,
            logger=bot.logger,
        ),
    )