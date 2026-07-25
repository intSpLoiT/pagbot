from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
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
MAX_QUICK_RAW_LENGTH = 4000
PANEL_TIMEOUT_SECONDS = 300
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
class SayDraft:
    """
    Say panelinde toplanan veriler.
    """

    title: str = ""
    main_text: str = ""
    second_text: Optional[str] = None
    third_text: Optional[str] = None
    roblox_username: Optional[str] = None
    everyone_ping: bool = True

    @property
    def is_ready(self) -> bool:
        return bool(self.title.strip() and self.main_text.strip())


# ============================================================
# HELPERS
# ============================================================


def _normalize_optional_text(value: str) -> Optional[str]:
    value = value.strip()
    if not value:
        return None
    if value.lower() in SKIP_MARKERS:
        return None
    return value


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


# ============================================================
# BASE VIEW
# ============================================================


class SayPanelViewBase(discord.ui.View):
    """
    Panel görünümleri için ortak temel.

    Her panel:
        - sadece komutu başlatan admin tarafından kullanılabilir
        - draft oturumu yoksa kullanıcı bilgilendirilir
    """

    def __init__(
        self,
        cog: "Say",
        author_id: int,
        *,
        timeout: float = PANEL_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu panel sana ait değil.",
                ephemeral=True,
            )
            return False

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Sunucu üye bilgisi alınamadı.",
                ephemeral=True,
            )
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Bu panel için Administrator yetkisi gerekir.",
                ephemeral=True,
            )
            return False

        if not self.cog.has_draft(self.author_id):
            await interaction.response.send_message(
                "❌ Bu panel oturumu artık geçerli değil. `!say` ile yeniden aç.",
                ephemeral=True,
            )
            return False

        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

        self.cog.clear_draft(self.author_id)


# ============================================================
# QUICK MODAL
# ============================================================


class SayQuickModal(discord.ui.Modal):
    """
    Tek satır hızlı giriş paneli.

    Format:
        Başlık | Ana yazı | Ek yazı 1 | Ek yazı 2 | RobloxAdı

    Alternatif:
        Başlık
        (sadece başlık doldurur, diğer alanlar sonradan tamamlanabilir)
    """

    def __init__(
        self,
        cog: "Say",
        *,
        author_id: int,
        source_message: discord.Message | None,
        return_view_kind: str,
    ) -> None:
        super().__init__(title="PAG Say • Hızlı Giriş")
        self.cog = cog
        self.author_id = author_id
        self.source_message = source_message
        self.return_view_kind = return_view_kind

        self.raw_input = discord.ui.TextInput(
            label="Tek Satır",
            placeholder="Başlık | Ana yazı | Ek yazı 1 | Ek yazı 2 | RobloxAdı",
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=1,
            max_length=MAX_QUICK_RAW_LENGTH,
        )
        self.add_item(self.raw_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return
        except discord.HTTPException:
            self.cog.logger.exception("Hızlı giriş paneli onaylanamadı.")
            return

        raw = self.raw_input.value.strip()
        if not raw:
            await self.cog.safe_followup(
                interaction,
                "❌ Tek satır girişi boş bırakılamaz.",
            )
            return

        draft = self.cog.parse_quick_input(raw)
        if draft is None:
            await self.cog.safe_followup(
                interaction,
                "❌ Tek satır formatı çözümlenemedi. `Başlık | Ana yazı | Ek1 | Ek2 | RobloxAdı` biçimini kullan.",
            )
            return

        self.cog.set_draft(self.author_id, draft)

        await self.cog.refresh_panel_after_edit(
            interaction=interaction,
            author_id=self.author_id,
            source_message=self.source_message,
            return_view_kind=self.return_view_kind,
            notice="✅ Hızlı giriş uygulandı.",
        )


# ============================================================
# FIELD MODAL
# ============================================================


class SayFieldModal(discord.ui.Modal):
    """
    Tek alan düzenleme paneli.
    """

    def __init__(
        self,
        cog: "Say",
        *,
        author_id: int,
        source_message: discord.Message | None,
        return_view_kind: str,
        field_key: str,
        field_label: str,
        placeholder: str,
        required: bool,
        max_length: int,
        paragraph: bool = False,
    ) -> None:
        super().__init__(title=f"PAG Say • {field_label}")
        self.cog = cog
        self.author_id = author_id
        self.source_message = source_message
        self.return_view_kind = return_view_kind
        self.field_key = field_key
        self.required = required
        self.max_length = max_length

        self.input = discord.ui.TextInput(
            label=field_label,
            placeholder=placeholder,
            required=required,
            min_length=1 if required else 0,
            max_length=max_length,
            style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return
        except discord.HTTPException:
            self.cog.logger.exception("Alan düzenleme paneli onaylanamadı.")
            return

        value = self.input.value.strip()

        if self.required and not value:
            await self.cog.safe_followup(
                interaction,
                "❌ Bu alan boş bırakılamaz.",
            )
            return

        if value and len(value) > self.max_length:
            await self.cog.safe_followup(
                interaction,
                f"❌ Metin çok uzun. En fazla `{self.max_length}` karakter olmalı.",
            )
            return

        updated = self.cog.update_draft_field(
            self.author_id,
            self.field_key,
            value,
        )

        if updated is None:
            await self.cog.safe_followup(
                interaction,
                "❌ Panel oturumu bulunamadı. `!say` ile yeniden aç.",
            )
            return

        await self.cog.refresh_panel_after_edit(
            interaction=interaction,
            author_id=self.author_id,
            source_message=self.source_message,
            return_view_kind=self.return_view_kind,
            notice="✅ Alan güncellendi.",
        )


# ============================================================
# VIEWS
# ============================================================


class SayMainPanelView(SayPanelViewBase):
    """
    Ana kontrol paneli.

    Buradan:
        - hızlı giriş
        - ayrıntılı panel
        - önizleme
        - herkesi etiketle aç/kapat
        - sıfırla
        - iptal
    yapılır.
    """

    @discord.ui.button(
        label="Tek Satır",
        emoji="⚡",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def quick_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayQuickModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="main",
            )
        )

    @discord.ui.button(
        label="Ayrıntılı",
        emoji="🧩",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def detail_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ana Panel",
            ),
            view=self.cog.build_view("detail", self.author_id),
        )

    @discord.ui.button(
        label="Önizleme",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def preview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        preview_embed = await self.cog.build_preview_embed(draft)
        await interaction.edit_original_response(
            embed=preview_embed,
            view=self.cog.build_view(
                "preview",
                self.author_id,
                return_to="main",
            ),
        )

    @discord.ui.button(
        label="@everyone",
        emoji="📣",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def toggle_everyone_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.toggle_everyone(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ana Panel",
            ),
            view=self,
        )

    @discord.ui.button(
        label="Sıfırla",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.set_draft(self.author_id, SayDraft())
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                self.cog.get_draft(self.author_id) or SayDraft(),
                panel_name="Ana Panel",
            ),
            view=self,
        )

    @discord.ui.button(
        label="İptal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.clear_draft(self.author_id)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ Say paneli kapatıldı.",
                embed=None,
                view=self,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Say paneli kapatıldı.",
                ephemeral=True,
            )


class SayDetailPanelView(SayPanelViewBase):
    """
    Ayrıntılı düzenleme paneli.
    """

    @discord.ui.button(
        label="Başlık",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def title_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayFieldModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
                field_key="title",
                field_label="Başlık",
                placeholder="Örn: 🏆 Haftanın Oyuncusu",
                required=True,
                max_length=MAX_TITLE_LENGTH,
            )
        )

    @discord.ui.button(
        label="Ana Yazı",
        emoji="📄",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def main_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayFieldModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
                field_key="main_text",
                field_label="Ana Yazı",
                placeholder="Ana duyuru metnini yaz...",
                required=True,
                max_length=MAX_MAIN_TEXT_LENGTH,
                paragraph=True,
            )
        )

    @discord.ui.button(
        label="Ek Yazı 1",
        emoji="➕",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def extra_one_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayFieldModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
                field_key="second_text",
                field_label="Ek Yazı 1",
                placeholder="İsteğe bağlı ek yazı...",
                required=False,
                max_length=MAX_EXTRA_TEXT_LENGTH,
                paragraph=True,
            )
        )

    @discord.ui.button(
        label="Ek Yazı 2",
        emoji="➕",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def extra_two_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayFieldModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
                field_key="third_text",
                field_label="Ek Yazı 2",
                placeholder="İsteğe bağlı ek yazı...",
                required=False,
                max_length=MAX_EXTRA_TEXT_LENGTH,
                paragraph=True,
            )
        )

    @discord.ui.button(
        label="Roblox",
        emoji="🎮",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def roblox_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayFieldModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
                field_key="roblox_username",
                field_label="Roblox Kullanıcı Adı",
                placeholder="Avatar eklemek için isteğe bağlı...",
                required=False,
                max_length=MAX_ROBLOX_USERNAME_LENGTH,
            )
        )

    @discord.ui.button(
        label="Tek Satır",
        emoji="⚡",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def quick_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            SayQuickModal(
                self.cog,
                author_id=self.author_id,
                source_message=interaction.message,
                return_view_kind="detail",
            )
        )

    @discord.ui.button(
        label="Önizleme",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def preview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        preview_embed = await self.cog.build_preview_embed(draft)
        await interaction.edit_original_response(
            embed=preview_embed,
            view=self.cog.build_view(
                "preview",
                self.author_id,
                return_to="detail",
            ),
        )

    @discord.ui.button(
        label="@everyone",
        emoji="📣",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle_everyone_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.toggle_everyone(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ayrıntılı Panel",
            ),
            view=self,
        )

    @discord.ui.button(
        label="Sıfırla",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.set_draft(self.author_id, SayDraft())
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                self.cog.get_draft(self.author_id) or SayDraft(),
                panel_name="Ayrıntılı Panel",
            ),
            view=self,
        )

    @discord.ui.button(
        label="Geri",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ana Panel",
            ),
            view=self.cog.build_view("main", self.author_id),
        )

    @discord.ui.button(
        label="İptal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.clear_draft(self.author_id)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ Say paneli kapatıldı.",
                embed=None,
                view=self,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Say paneli kapatıldı.",
                ephemeral=True,
            )


class SayPreviewView(SayPanelViewBase):
    """
    Önizleme paneli.

    Burada kullanıcı son kararını verir.
    """

    def __init__(
        self,
        cog: "Say",
        author_id: int,
        *,
        return_to: str,
        timeout: float = PREVIEW_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(cog, author_id, timeout=timeout)
        self.return_to = return_to
        self._sending = False

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
        if self._sending:
            await interaction.response.send_message(
                "⏳ İşlem zaten sürüyor.",
                ephemeral=True,
            )
            return

        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        validation_error = self.cog.validate_message_data(draft)
        if validation_error:
            await interaction.response.send_message(
                f"❌ {validation_error}",
                ephemeral=True,
            )
            return

        self._sending = True

        try:
            await interaction.response.defer(ephemeral=True)

            await self.cog.dispatch_say_message(
                interaction=interaction,
                draft=draft,
            )

            self.cog.clear_draft(self.author_id)

            for child in self.children:
                child.disabled = True

            try:
                await interaction.edit_original_response(
                    content="✅ Mesaj başarıyla gönderildi.",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                pass

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
            self.cog.logger.exception("Discord API error while sending /say.")
            await interaction.followup.send(
                "❌ Discord API hatası oluştu.",
                ephemeral=True,
            )

        except Exception:
            self.cog.logger.exception("Unexpected error while sending /say.")
            await interaction.followup.send(
                "❌ Mesaj gönderilirken beklenmeyen bir hata oluştu.",
                ephemeral=True,
            )

        finally:
            self._sending = False

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
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ayrıntılı Panel" if self.return_to == "detail" else "Ana Panel",
            ),
            view=self.cog.build_view(self.return_to, self.author_id),
        )

    @discord.ui.button(
        label="Ana Panel",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def main_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                draft,
                panel_name="Ana Panel",
            ),
            view=self.cog.build_view("main", self.author_id),
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
        self.cog.clear_draft(self.author_id)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ Say işlemi iptal edildi.",
                embed=None,
                view=self,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Say işlemi iptal edildi.",
                ephemeral=True,
            )


# ============================================================
# MAIN COG
# ============================================================


class Say(commands.Cog):
    """
    PAG say/yayın sistemi.

    Özellikler:
        - !say direkt çalışır
        - /say korunur
        - ana panel
        - ayrıntılı panel
        - tek satır hızlı giriş
        - önizleme paneli
        - @everyone aç/kapat
        - Roblox avatar zenginleştirme
        - güvenli hata yakalama
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
        self._drafts: dict[int, SayDraft] = {}

    # ========================================================
    # DRAFT MANAGEMENT
    # ========================================================

    def create_draft(self, author_id: int, draft: SayDraft | None = None) -> SayDraft:
        draft = draft or SayDraft()
        self._drafts[author_id] = draft
        return draft

    def get_draft(self, author_id: int) -> SayDraft | None:
        return self._drafts.get(author_id)

    def has_draft(self, author_id: int) -> bool:
        return author_id in self._drafts

    def clear_draft(self, author_id: int) -> None:
        self._drafts.pop(author_id, None)

    def set_draft(self, author_id: int, draft: SayDraft) -> SayDraft:
        self._drafts[author_id] = draft
        return draft

    def update_draft_field(
        self,
        author_id: int,
        field_key: str,
        value: str,
    ) -> SayDraft | None:
        draft = self.get_draft(author_id)
        if draft is None:
            return None

        if field_key == "title":
            return self.set_draft(author_id, replace(draft, title=value))

        if field_key == "main_text":
            return self.set_draft(author_id, replace(draft, main_text=value))

        if field_key == "second_text":
            return self.set_draft(author_id, replace(draft, second_text=_normalize_optional_text(value or "")))

        if field_key == "third_text":
            return self.set_draft(author_id, replace(draft, third_text=_normalize_optional_text(value or "")))

        if field_key == "roblox_username":
            return self.set_draft(author_id, replace(draft, roblox_username=_normalize_optional_text(value or "")))

        return draft

    def toggle_everyone(self, author_id: int) -> SayDraft | None:
        draft = self.get_draft(author_id)
        if draft is None:
            return None

        updated = replace(draft, everyone_ping=not draft.everyone_ping)
        return self.set_draft(author_id, updated)

    # ========================================================
    # PARSING
    # ========================================================

    def parse_quick_input(self, raw: str) -> SayDraft | None:
        raw = raw.strip()
        if not raw:
            return None

        # Tek satırda sadece başlık verilirse de kabul et.
        if "|" not in raw:
            return SayDraft(
                title=raw,
                main_text="",
                second_text=None,
                third_text=None,
                roblox_username=None,
                everyone_ping=True,
            )

        parts = [part.strip() for part in re.split(r"\s*\|\s*", raw)]
        if not parts:
            return None

        title = parts[0] if len(parts) > 0 else ""
        main_text = parts[1] if len(parts) > 1 else ""
        second_text = parts[2] if len(parts) > 2 else ""
        third_text = parts[3] if len(parts) > 3 else ""
        roblox_username = parts[4] if len(parts) > 4 else ""

        return SayDraft(
            title=title,
            main_text=main_text,
            second_text=_normalize_optional_text(second_text or ""),
            third_text=_normalize_optional_text(third_text or ""),
            roblox_username=_normalize_optional_text(roblox_username or ""),
            everyone_ping=True,
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_message_data(self, data: SayDraft) -> Optional[str]:
        if not data.title.strip():
            return "Başlık boş bırakılamaz."

        if not data.main_text.strip():
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
    # VIEW FACTORY
    # ========================================================

    def build_view(
        self,
        kind: str,
        author_id: int,
        *,
        return_to: str = "main",
    ) -> SayPanelViewBase:
        if kind == "detail":
            return SayDetailPanelView(self, author_id)
        if kind == "preview":
            return SayPreviewView(self, author_id, return_to=return_to)
        return SayMainPanelView(self, author_id)

    # ========================================================
    # EMBEDS
    # ========================================================

    async def build_panel_embed(
        self,
        draft: SayDraft,
        *,
        panel_name: str,
    ) -> discord.Embed:
        ready = draft.is_ready

        embed = discord.Embed(
            title=draft.title.strip() if draft.title.strip() else "📢 PAG Say Paneli",
            description=_shorten(
                draft.main_text.strip() if draft.main_text.strip() else "Henüz ana yazı girilmedi.",
                4000,
            ),
            color=discord.Color.green() if ready else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Başlık",
            value=_shorten(draft.title.strip() or "—", 1024),
            inline=False,
        )

        embed.add_field(
            name="Ek Yazı 1",
            value=_shorten(draft.second_text or "—", 1024),
            inline=False,
        )

        embed.add_field(
            name="Ek Yazı 2",
            value=_shorten(draft.third_text or "—", 1024),
            inline=False,
        )

        embed.add_field(
            name="Roblox",
            value=_shorten(draft.roblox_username or "—", 1024),
            inline=True,
        )

        embed.add_field(
            name="@everyone",
            value="Açık" if draft.everyone_ping else "Kapalı",
            inline=True,
        )

        embed.add_field(
            name="Durum",
            value="Hazır" if ready else "Eksik",
            inline=True,
        )

        embed.add_field(
            name="Panel",
            value=panel_name,
            inline=True,
        )

        embed.add_field(
            name="Hızlı Format",
            value="`Başlık | Ana yazı | Ek1 | Ek2 | RobloxAdı`",
            inline=False,
        )

        embed.set_footer(
            text="Panel • Butonlar ile düzenle, önizle ve gönder.",
        )

        return embed

    async def build_public_embed(
        self,
        draft: SayDraft,
        *,
        footer_text: str,
    ) -> discord.Embed:
        title = draft.title.strip() or "PAG Say"
        description = draft.main_text.strip() or "Henüz ana yazı girilmedi."

        embed = discord.Embed(
            title=_shorten(title, MAX_TITLE_LENGTH),
            description=_shorten(description, MAX_MAIN_TEXT_LENGTH),
            color=discord.Color.gold() if draft.everyone_ping else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if draft.second_text:
            embed.add_field(
                name="Ek Yazı 1",
                value=_shorten(draft.second_text, 1024),
                inline=False,
            )

        if draft.third_text:
            embed.add_field(
                name="Ek Yazı 2",
                value=_shorten(draft.third_text, 1024),
                inline=False,
            )

        if draft.roblox_username:
            embed.add_field(
                name="Roblox",
                value=_shorten(draft.roblox_username, 1024),
                inline=False,
            )

        if draft.everyone_ping:
            embed.add_field(
                name="Yayın",
                value="@everyone açık",
                inline=True,
            )

        embed.set_footer(
            text=footer_text,
        )

        if draft.roblox_username:
            await self.add_roblox_avatar(
                embed=embed,
                username=draft.roblox_username,
            )

        return embed

    async def build_preview_embed(self, draft: SayDraft) -> discord.Embed:
        return await self.build_public_embed(
            draft,
            footer_text="Önizleme • Göndermeden önce kontrol et.",
        )

    # ========================================================
    # ROBLOX ENRICHMENT
    # ========================================================

    async def add_roblox_avatar(
        self,
        *,
        embed: discord.Embed,
        username: str,
    ) -> None:
        """
        Roblox avatarını eklemeyi dener.

        Başarısız olsa bile ana akış bozulmaz.
        """

        try:
            user = await self.roblox_service.get_user_by_username(username)
            avatar = await self.roblox_service.get_avatar(user.id)

            if avatar.image_url:
                embed.set_thumbnail(url=avatar.image_url)

            embed.set_footer(
                text=f"Roblox: {user.display_name}",
            )

        except RobloxNotFoundError:
            self.logger.warning("Roblox user not found for /say: %s", username)

        except RobloxAPIError:
            self.logger.warning(
                "Roblox API failed while enriching /say.",
                exc_info=True,
            )

        except Exception:
            self.logger.exception(
                "Unexpected Roblox error while enriching /say.",
            )

    # ========================================================
    # CHANNEL DISPATCH
    # ========================================================

    async def dispatch_say_message(
        self,
        *,
        interaction: discord.Interaction,
        draft: SayDraft,
    ) -> discord.Message:
        channel = interaction.channel
        if channel is None:
            raise PermissionError("Interaction channel unavailable.")

        if not isinstance(channel, discord.abc.Messageable):
            raise PermissionError("Channel is not messageable.")

        content = "@everyone" if draft.everyone_ping else None

        embed = await self.build_public_embed(
            draft,
            footer_text="PAG • Say",
        )

        sent_message = await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=draft.everyone_ping,
                users=False,
                roles=False,
                replied_user=False,
            ),
        )

        self.logger.info(
            "Say message sent: user=%s guild=%s channel=%s message=%s",
            interaction.user.id,
            interaction.guild.id if interaction.guild else None,
            getattr(channel, "id", None),
            getattr(sent_message, "id", None),
        )

        return sent_message

    # ========================================================
    # REFRESH HELPERS
    # ========================================================

    async def refresh_panel_after_edit(
        self,
        *,
        interaction: discord.Interaction,
        author_id: int,
        source_message: discord.Message | None,
        return_view_kind: str,
        notice: str,
    ) -> None:
        draft = self.get_draft(author_id)
        if draft is None:
            await self.safe_followup(
                interaction,
                "❌ Panel oturumu bulunamadı. `!say` ile yeniden aç.",
            )
            return

        try:
            embed = await self.build_panel_embed(
                draft,
                panel_name="Ayrıntılı Panel" if return_view_kind == "detail" else "Ana Panel",
            )
            view = self.build_view(return_view_kind, author_id)
        except Exception:
            self.logger.exception("Panel yeniden oluşturulamadı.")
            await self.safe_followup(
                interaction,
                "❌ Panel yeniden oluşturulamadı.",
            )
            return

        if source_message is not None:
            try:
                await source_message.edit(
                    embed=embed,
                    view=view,
                )
            except discord.HTTPException:
                self.logger.exception("Source message edit failed.")
                # Panel edit başarısız olsa da kullanıcıya bilgi ver.
                await self.safe_followup(
                    interaction,
                    notice,
                )
                return

        await self.safe_followup(
            interaction,
            notice,
        )

    # ========================================================
    # SAFE RESPONSE
    # ========================================================

    async def safe_initial_response(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
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
        except discord.NotFound:
            self.logger.warning("Interaction expired before response.")
        except discord.HTTPException:
            self.logger.exception("Failed to send initial interaction response.")

    async def safe_followup(
        self,
        interaction: discord.Interaction,
        content: str,
    ) -> None:
        try:
            await interaction.followup.send(
                content,
                ephemeral=True,
            )
        except discord.NotFound:
            self.logger.warning("Interaction expired before followup.")
        except discord.HTTPException:
            self.logger.exception("Failed to send interaction followup.")

    # ========================================================
    # OPEN PANEL
    # ========================================================

    async def open_panel_for_interaction(
        self,
        interaction: discord.Interaction,
        *,
        draft: SayDraft,
        ephemeral: bool,
    ) -> None:
        self.create_draft(interaction.user.id, draft)

        embed = await self.build_panel_embed(
            draft,
            panel_name="Ana Panel",
        )

        view = self.build_view("main", interaction.user.id)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=ephemeral,
        )

    async def open_panel_for_ctx(
        self,
        ctx: commands.Context,
        *,
        draft: SayDraft,
    ) -> None:
        self.create_draft(ctx.author.id, draft)

        embed = await self.build_panel_embed(
            draft,
            panel_name="Ana Panel",
        )

        view = self.build_view("main", ctx.author.id)

        await ctx.send(
            embed=embed,
            view=view,
        )

    # ========================================================
    # COMMANDS
    # ========================================================

    @app_commands.command(
        name="say",
        description="PAG adına özel bir mesaj paneli açar.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def say(self, interaction: discord.Interaction) -> None:
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
            await self.open_panel_for_interaction(
                interaction,
                draft=SayDraft(),
                ephemeral=True,
            )
        except discord.HTTPException:
            self.logger.exception("Say paneli açılamadı.")
            if not interaction.response.is_done():
                await self.safe_initial_response(
                    interaction,
                    content="❌ Say paneli açılırken bir hata oluştu.",
                )

    @commands.command(
        name="say",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def say_prefix(
        self,
        ctx: commands.Context,
        *,
        raw: str | None = None,
    ) -> None:
        if ctx.guild is None:
            await ctx.send("❌ Bu komut yalnızca sunucularda kullanılabilir.")
            return

        if not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ Sunucu üye bilgisi alınamadı.")
            return

        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bu komutu yalnızca sunucu yöneticileri kullanabilir.")
            return

        draft = SayDraft()

        if raw and raw.strip():
            parsed = self.parse_quick_input(raw)
            if parsed is not None:
                draft = parsed

        await self.open_panel_for_ctx(
            ctx,
            draft=draft,
        )

    # ========================================================
    # ERROR HANDLERS
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