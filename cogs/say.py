from __future__ import annotations

import asyncio
import logging
import re
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

PROMPT_TIMEOUT_SECONDS = 120
PREVIEW_TIMEOUT_SECONDS = 180

SKIP_MARKERS = {
    "",
    "-",
    "skip",
    "none",
    "yok",
    "atla",
    "pass",
}

CANCEL_MARKERS = {
    "cancel",
    "iptal",
    "vazgeç",
    "vazgec",
    "stop",
    "quit",
}


# ============================================================
# DATA MODEL
# ============================================================


@dataclass(slots=True, frozen=True)
class SayMessageData:
    """
    /say ve !say için normalize edilmiş veri.
    """

    title: str
    main_text: str
    second_text: Optional[str]
    third_text: Optional[str]
    roblox_username: Optional[str]


# ============================================================
# HELPERS
# ============================================================


def _is_skip_text(value: str) -> bool:
    return value.strip().lower() in SKIP_MARKERS


def _is_cancel_text(value: str) -> bool:
    return value.strip().lower() in CANCEL_MARKERS


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


# ============================================================
# PREVIEW VIEW
# ============================================================


class SayPreviewView(discord.ui.View):
    """
    Önizleme onay paneli.

    Özellikler:
        - Gönder
        - Düzenle
        - İptal
        - Timeout koruması

    Not:
        Buradaki gönderim işlemi doğrudan kanal mesajı atar.
        Roblox avatarı önceden çözülmüşse embed içine eklenir.
    """

    def __init__(
        self,
        *,
        cog: "Say",
        data: SayMessageData,
        author_id: int,
        source_label: str,
        timeout: float = PREVIEW_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.data = data
        self.author_id = author_id
        self.source_label = source_label
        self._locked = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu önizleme sana ait değil.",
                ephemeral=True,
            )
            return False

        return True

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True

    @discord.ui.button(
        label="Gönder",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def send_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self._locked:
            await interaction.response.send_message(
                "⏳ Bu işlem zaten sürüyor.",
                ephemeral=True,
            )
            return

        self._locked = True
        self._disable_all()

        try:
            await interaction.response.defer(ephemeral=True)

            sent_message = await self.cog.dispatch_say_message(
                interaction=interaction,
                data=self.data,
            )

            self.cog.logger.info(
                "Say preview confirmed and sent: user=%s guild=%s channel=%s message=%s",
                interaction.user.id,
                interaction.guild.id if interaction.guild else None,
                interaction.channel.id if interaction.channel else None,
                getattr(sent_message, "id", None),
            )

            try:
                await interaction.message.edit(
                    content="✅ Mesaj başarıyla gönderildi.",
                    embed=None,
                    view=None,
                )
            except Exception:
                pass

            await interaction.followup.send(
                "✅ Mesaj başarıyla gönderildi.",
                ephemeral=True,
            )

        except PermissionError:
            await interaction.followup.send(
                "❌ Botun bu kanala mesaj gönderme yetkisi yok.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Discord botun bu mesajı göndermesine izin vermedi.",
                ephemeral=True,
            )

        except discord.NotFound:
            await interaction.followup.send(
                "❌ Kanal veya interaction artık bulunamıyor.",
                ephemeral=True,
            )

        except discord.HTTPException:
            self.cog.logger.exception("Discord API error while sending /say preview.")
            await interaction.followup.send(
                "❌ Discord API hatası oluştu.",
                ephemeral=True,
            )

        except Exception:
            self.cog.logger.exception("Unexpected error while sending /say preview.")
            await interaction.followup.send(
                "❌ Mesaj gönderilirken beklenmeyen bir hata oluştu.",
                ephemeral=True,
            )

        finally:
            self._locked = False

    @discord.ui.button(
        label="Düzenle",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """
        Hızlı geri dönüş için boş modal açar.
        Gerekirse kullanıcı yeniden doldurur.
        """

        await interaction.response.send_modal(
            SayModal(self.cog),
        )

    @discord.ui.button(
        label="İptal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self._disable_all()

        try:
            await interaction.response.edit_message(
                content="❎ Say işlemi iptal edildi.",
                embed=None,
                view=None,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Say işlemi iptal edildi.",
                ephemeral=True,
            )

        self.stop()

    async def on_timeout(self) -> None:
        self._disable_all()


# ============================================================
# SAY MODAL
# ============================================================


class SayModal(discord.ui.Modal, title="PAG Say Panel"):
    """
    Slash command için modal.
    Prefix tarafı bu modalı kullanmaz.
    """

    title_input = discord.ui.TextInput(
        label="Başlık",
        placeholder="Örn: 🏆 Haftanın Oyuncusu",
        required=True,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
    )

    main_text_input = discord.ui.TextInput(
        label="Ana Yazı",
        placeholder="Ana duyuru metnini yaz...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=1,
        max_length=MAX_MAIN_TEXT_LENGTH,
    )

    second_text_input = discord.ui.TextInput(
        label="Ek Yazı 1",
        placeholder="İsteğe bağlı ek yazı...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_EXTRA_TEXT_LENGTH,
    )

    third_text_input = discord.ui.TextInput(
        label="Ek Yazı 2",
        placeholder="İsteğe bağlı ek yazı...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_EXTRA_TEXT_LENGTH,
    )

    roblox_username_input = discord.ui.TextInput(
        label="Roblox Kullanıcı Adı",
        placeholder="Avatar eklemek için isteğe bağlı...",
        required=False,
        max_length=MAX_ROBLOX_USERNAME_LENGTH,
    )

    def __init__(self, cog: "Say") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return
        except discord.HTTPException:
            self.cog.logger.exception("Failed to defer /say modal interaction.")
            return

        data = SayMessageData(
            title=self.title_input.value.strip(),
            main_text=self.main_text_input.value.strip(),
            second_text=self.second_text_input.value.strip() or None,
            third_text=self.third_text_input.value.strip() or None,
            roblox_username=self.roblox_username_input.value.strip() or None,
        )

        validation_error = self.cog.validate_message_data(data)
        if validation_error:
            await self.cog.safe_followup(
                interaction,
                content=f"❌ {validation_error}",
            )
            return

        await self.cog.present_preview(
            interaction=interaction,
            data=data,
            source_label="Slash",
        )


# ============================================================
# SAY COG
# ============================================================


class Say(commands.Cog):
    """
    PAG say/yayın sistemi.

    Slash:
        /say

    Prefix:
        !say

    Gelişmiş özellikler:
        - Hızlı tek satır giriş
        - Adım adım soru-cevap akışı
        - Önizleme onayı
        - Avatar zenginleştirme
        - Güvenli hata yönetimi
        - Timeout koruması
        - Prefix ve slash birlikte
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.roblox_service = roblox_service
        self.logger = logger

    # ========================================================
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="say",
        description="PAG adına özel bir mesaj oluşturur.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def say(self, interaction: discord.Interaction) -> None:
        """
        Slash say komutu: modal açar.
        """

        if interaction.guild is None:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komut yalnızca sunucularda kullanılabilir.",
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await self.safe_initial_response(
                interaction,
                content="❌ Sunucu üye bilgisi alınamadı.",
            )
            return

        if not member.guild_permissions.administrator:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komutu yalnızca sunucu yöneticileri kullanabilir.",
            )
            self.logger.warning(
                "Unauthorized /say attempt: user=%s guild=%s",
                member.id,
                interaction.guild.id,
            )
            return

        try:
            await interaction.response.send_modal(
                SayModal(self),
            )
        except discord.HTTPException:
            self.logger.exception("Failed to open SayModal.")
            if not interaction.response.is_done():
                await self.safe_initial_response(
                    interaction,
                    content="❌ Say paneli açılırken bir hata oluştu.",
                )

    # ========================================================
    # PREFIX COMMAND
    # ========================================================

    @commands.command(name="say")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def say_prefix(
        self,
        ctx: commands.Context,
        *,
        raw: str | None = None,
    ) -> None:
        """
        Prefix say komutu.

        Hızlı kullanım:
            !say Başlık | Ana yazı | Ek yazı 1 | Ek yazı 2 | RobloxAdı

        Alternatif:
            !say
            → adım adım soru-cevap akışı
        """

        if ctx.guild is None:
            await ctx.send("❌ Bu komut yalnızca sunucularda kullanılabilir.")
            return

        if not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ Sunucu üye bilgisi alınamadı.")
            return

        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bu komutu yalnızca sunucu yöneticileri kullanabilir.")
            return

        if raw and raw.strip():
            parsed = self.parse_raw_prefix_input(raw)
            if parsed is not None:
                validation_error = self.validate_message_data(parsed)
                if validation_error:
                    await ctx.send(f"❌ {validation_error}")
                    return

                await self.present_preview_ctx(
                    ctx=ctx,
                    data=parsed,
                    source_label="Prefix (tek satır)",
                )
                return

        await self.run_prompt_flow(ctx)

    # ========================================================
    # PROMPT FLOW
    # ========================================================

    async def run_prompt_flow(self, ctx: commands.Context) -> None:
        """
        !say için adım adım veri toplama.
        """

        await ctx.send(
            "📢 **PAG Say Paneli**\n"
            "Aşağıdaki sorulara sırayla cevap ver.\n"
            f"Her soru için `{PROMPT_TIMEOUT_SECONDS}` saniyen var.\n"
            "İptal etmek için `iptal`, `cancel` veya `vazgeç` yazabilirsin."
        )

        title = await self.ask_user_text(
            ctx,
            prompt="Başlık nedir?",
            required=True,
            max_length=MAX_TITLE_LENGTH,
            paragraph=False,
        )
        if title is None:
            await ctx.send("❌ İşlem iptal edildi veya süre doldu.")
            return

        main_text = await self.ask_user_text(
            ctx,
            prompt="Ana yazı nedir?",
            required=True,
            max_length=MAX_MAIN_TEXT_LENGTH,
            paragraph=True,
        )
        if main_text is None:
            await ctx.send("❌ İşlem iptal edildi veya süre doldu.")
            return

        second_text = await self.ask_user_text(
            ctx,
            prompt="Ek Yazı 1 (atlamak için `skip` yaz)",
            required=False,
            max_length=MAX_EXTRA_TEXT_LENGTH,
            paragraph=True,
        )
        if second_text is None:
            await ctx.send("❌ İşlem iptal edildi veya süre doldu.")
            return

        third_text = await self.ask_user_text(
            ctx,
            prompt="Ek Yazı 2 (atlamak için `skip` yaz)",
            required=False,
            max_length=MAX_EXTRA_TEXT_LENGTH,
            paragraph=True,
        )
        if third_text is None:
            await ctx.send("❌ İşlem iptal edildi veya süre doldu.")
            return

        roblox_username = await self.ask_user_text(
            ctx,
            prompt="Roblox kullanıcı adı (atlamak için `skip` yaz)",
            required=False,
            max_length=MAX_ROBLOX_USERNAME_LENGTH,
            paragraph=False,
        )
        if roblox_username is None:
            await ctx.send("❌ İşlem iptal edildi veya süre doldu.")
            return

        data = SayMessageData(
            title=title.strip(),
            main_text=main_text.strip(),
            second_text=second_text.strip() or None,
            third_text=third_text.strip() or None,
            roblox_username=roblox_username.strip() or None,
        )

        validation_error = self.validate_message_data(data)
        if validation_error:
            await ctx.send(f"❌ {validation_error}")
            return

        await self.present_preview_ctx(
            ctx=ctx,
            data=data,
            source_label="Prefix (adım adım)",
        )

    async def ask_user_text(
        self,
        ctx: commands.Context,
        *,
        prompt: str,
        required: bool,
        max_length: int,
        paragraph: bool,
    ) -> str | None:
        """
        Kullanıcıdan güvenli şekilde veri alır.

        Kurallar:
            - timeout olursa None
            - cancel marker gelirse None
            - required alan boş gelirse tekrar sor
            - optional alan skip ile atlanabilir
        """

        for attempt in range(3):
            try:
                await ctx.send(
                    f"**{prompt}**",
                    delete_after=45,
                )
            except discord.HTTPException:
                self.logger.exception("Failed to send prompt message.")
                return None

            def check(message: discord.Message) -> bool:
                return (
                    message.author.id == ctx.author.id
                    and message.channel.id == ctx.channel.id
                )

            try:
                reply = await self.bot.wait_for(
                    "message",
                    check=check,
                    timeout=PROMPT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return None
            except Exception:
                self.logger.exception("Unexpected wait_for error in /say prompt.")
                return None

            content = reply.content.strip()

            if _is_cancel_text(content):
                return None

            if _is_skip_text(content):
                if required:
                    await ctx.send(
                        "❌ Bu alan zorunlu. Lütfen geçerli bir değer yaz.",
                        delete_after=15,
                    )
                    continue
                return ""

            if not content:
                if required:
                    await ctx.send(
                        "❌ Bu alan boş bırakılamaz. Lütfen tekrar yaz.",
                        delete_after=15,
                    )
                    continue
                return ""

            if len(content) > max_length:
                if attempt < 2:
                    await ctx.send(
                        f"❌ Metin çok uzun. En fazla `{max_length}` karakter olmalı.",
                        delete_after=15,
                    )
                    continue
                return content[:max_length]

            return content

        return None

    # ========================================================
    # RAW PARSER
    # ========================================================

    def parse_raw_prefix_input(self, raw: str) -> SayMessageData | None:
        """
        Tek satırlık giriş formatı:

            !say Başlık | Ana yazı | Ek yazı 1 | Ek yazı 2 | RobloxAdı

        En az:
            Başlık | Ana yazı

        gerekir.
        """

        raw = raw.strip()
        if not raw:
            return None

        parts = [part.strip() for part in re.split(r"\s*\|\s*", raw)]
        if len(parts) < 2:
            return None

        title = parts[0]
        main_text = parts[1]
        second_text = parts[2] if len(parts) > 2 and parts[2].strip() else None
        third_text = parts[3] if len(parts) > 3 and parts[3].strip() else None
        roblox_username = parts[4] if len(parts) > 4 and parts[4].strip() else None

        return SayMessageData(
            title=title,
            main_text=main_text,
            second_text=second_text,
            third_text=third_text,
            roblox_username=roblox_username,
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_message_data(self, data: SayMessageData) -> Optional[str]:
        if not data.title:
            return "Başlık boş bırakılamaz."

        if not data.main_text:
            return "Ana yazı boş bırakılamaz."

        if len(data.title) > MAX_TITLE_LENGTH:
            return "Başlık çok uzun."

        if len(data.main_text) > MAX_MAIN_TEXT_LENGTH:
            return "Ana yazı çok uzun."

        if data.second_text and len(data.second_text) > MAX_EXTRA_TEXT_LENGTH:
            return "Ek Yazı 1 çok uzun."

        if data.third_text and len(data.third_text) > MAX_EXTRA_TEXT_LENGTH:
            return "Ek Yazı 2 çok uzun."

        if data.roblox_username and len(data.roblox_username) > MAX_ROBLOX_USERNAME_LENGTH:
            return "Roblox kullanıcı adı çok uzun."

        return None

    # ========================================================
    # PREVIEW
    # ========================================================

    async def present_preview(
        self,
        *,
        interaction: discord.Interaction,
        data: SayMessageData,
        source_label: str,
    ) -> None:
        """
        Slash modal sonrası önizleme gönderir.
        """

        preview_embed = await self.build_preview_embed(
            data=data,
            source_label=source_label,
        )

        view = SayPreviewView(
            cog=self,
            data=data,
            author_id=interaction.user.id,
            source_label=source_label,
        )

        try:
            await interaction.followup.send(
                embed=preview_embed,
                view=view,
                ephemeral=True,
            )
        except discord.HTTPException:
            self.logger.exception("Failed to send preview message for /say.")

    async def present_preview_ctx(
        self,
        *,
        ctx: commands.Context,
        data: SayMessageData,
        source_label: str,
    ) -> None:
        """
        Prefix akışında önizleme gönderir.
        """

        preview_embed = await self.build_preview_embed(
            data=data,
            source_label=source_label,
        )

        view = SayPreviewView(
            cog=self,
            data=data,
            author_id=ctx.author.id,
            source_label=source_label,
        )

        try:
            await ctx.send(
                embed=preview_embed,
                view=view,
            )
        except discord.HTTPException:
            self.logger.exception("Failed to send preview message for prefix /say.")
            await ctx.send("❌ Önizleme gönderilemedi.")

    async def build_preview_embed(
        self,
        *,
        data: SayMessageData,
        source_label: str,
    ) -> discord.Embed:
        """
        Mesaj gönderilmeden önce önizleme embed'i.
        """

        embed = discord.Embed(
            title=f"👁️ Önizleme • {data.title}",
            description=data.main_text,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if data.second_text:
            embed.add_field(
                name="Ek Yazı 1",
                value=_shorten(data.second_text, 1024),
                inline=False,
            )

        if data.third_text:
            embed.add_field(
                name="Ek Yazı 2",
                value=_shorten(data.third_text, 1024),
                inline=False,
            )

        if data.roblox_username:
            embed.add_field(
                name="Roblox Kullanıcı Adı",
                value=f"`{data.roblox_username}`",
                inline=False,
            )

        embed.add_field(
            name="Kaynak",
            value=source_label,
            inline=True,
        )

        embed.add_field(
            name="Durum",
            value="Gönderilmedi",
            inline=True,
        )

        embed.set_footer(
            text="Göndermeden önce onay ver.",
        )

        if data.roblox_username:
            await self.add_roblox_avatar(
                embed=embed,
                username=data.roblox_username,
            )

        return embed

    # ========================================================
    # FINAL SEND
    # ========================================================

    async def dispatch_say_message(
        self,
        *,
        interaction: discord.Interaction,
        data: SayMessageData,
    ) -> discord.Message:
        """
        Mesajı kanala gönderir.

        Roblox zenginleştirme hata verse bile ana
        mesajın gönderimi durmaz.
        """

        channel = interaction.channel
        if channel is None:
            raise PermissionError("Interaction channel unavailable.")

        if not isinstance(channel, discord.abc.Messageable):
            raise PermissionError("Channel is not messageable.")

        embed = await self.build_final_embed(data)

        sent_message = await channel.send(
            content="@everyone",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=False,
                roles=False,
                replied_user=False,
            ),
        )

        return sent_message

    async def build_final_embed(self, data: SayMessageData) -> discord.Embed:
        """
        Nihai gönderilecek embed.
        """

        embed = discord.Embed(
            title=data.title,
            description=data.main_text,
            timestamp=discord.utils.utcnow(),
        )

        if data.second_text:
            embed.add_field(
                name="\u200b",
                value=data.second_text,
                inline=False,
            )

        if data.third_text:
            embed.add_field(
                name="\u200b",
                value=data.third_text,
                inline=False,
            )

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

        Roblox API başarısız olsa bile ana akış bozulmaz.
        """

        try:
            user = await self.roblox_service.get_user_by_username(username)
            avatar = await self.roblox_service.get_avatar(user.id)

            if avatar.image_url:
                embed.set_thumbnail(url=avatar.image_url)

            embed.set_footer(text=f"Roblox: {user.display_name}")

        except RobloxNotFoundError:
            self.logger.warning("Roblox user not found for /say: %s", username)

        except RobloxAPIError:
            self.logger.warning(
                "Roblox API failed while enriching /say.",
                exc_info=True,
            )

        except Exception:
            self.logger.exception("Unexpected Roblox error while enriching /say.")

    # ========================================================
    # SAFE RESPONSES
    # ========================================================

    async def safe_initial_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
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
            self.logger.warning("Interaction expired before response.")

        except discord.HTTPException:
            self.logger.exception("Failed to send initial interaction response.")

    async def safe_followup(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
        try:
            await interaction.followup.send(
                content=content,
                ephemeral=True,
            )

        except discord.NotFound:
            self.logger.warning("Interaction expired before followup.")

        except discord.HTTPException:
            self.logger.exception("Failed to send interaction followup.")

    # ========================================================
    # PREFIX ERROR HANDLER
    # ========================================================

    @say_prefix.error
    async def say_prefix_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.NoPrivateMessage):
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                "❌ Bu komutu kullanmak için yönetici yetkisine sahip olmalısın.",
                delete_after=8,
            )
            return

        self.logger.exception("Prefix /say error: %s", error)

        try:
            await ctx.send(
                "❌ /say çalıştırılırken beklenmeyen bir hata oluştu.",
                delete_after=8,
            )
        except discord.HTTPException:
            self.logger.exception("Failed to send prefix /say error.")

    # ========================================================
    # SLASH ERROR HANDLER
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ Bu komutu kullanmak için Administrator yetkisi gerekir."
        else:
            self.logger.exception("Say slash command error.")
            message = "❌ İşlem sırasında beklenmeyen bir hata oluştu."

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
        Say(
            bot,
            roblox_service=bot.roblox_service,
            logger=bot.logger,
        ),
    )