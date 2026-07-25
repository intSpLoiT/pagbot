from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional

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

MAX_REASON_LENGTH = 1000
MAX_PANEL_NOTE_LENGTH = 1500
MAX_QUICK_RAW_LENGTH = 3000
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
# DATA MODELS
# ============================================================


@dataclass(slots=True, frozen=True)
class BlacklistDraft:
    """
    Panelde toplanan veriler.

    discord_id:
        Discord target varsa tutulur.

    roblox_id / roblox_username:
        Roblox target varsa tutulur.

    reason:
        Blacklist sebebi.

    kick_now:
        Kayıt sırasında hedef server'daysa kick edilsin mi.
    """

    discord_id: int | None = None
    discord_label: str | None = None

    roblox_id: int | None = None
    roblox_username: str | None = None
    roblox_display_name: str | None = None
    avatar_url: str | None = None

    reason: str = "Sebep belirtilmedi."
    kick_now: bool = True

    @property
    def is_ready(self) -> bool:
        return self.discord_id is not None or self.roblox_id is not None


@dataclass(slots=True)
class BlacklistSession:
    """
    Panel oturumu.

    Her yönetici için tek aktif oturum tutulur.
    Panel kapanınca veya timeout olunca silinir.
    """

    draft: BlacklistDraft
    panel_channel_id: int | None = None
    panel_message_id: int | None = None
    current_view: str = "main"  # main | detail | preview | manage | history


@dataclass(slots=True)
class BlacklistResolvedTarget:
    """
    Blacklist işlemi için çözülmüş hedef.
    """

    discord_member: discord.Member | None = None
    discord_id: int | None = None
    roblox_id: int | None = None
    roblox_username: str | None = None
    roblox_display_name: str | None = None
    avatar_url: str | None = None


# ============================================================
# HELPERS
# ============================================================


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return "—"

    value = text.strip()
    if len(value) <= limit:
        return value

    return value[: limit - 3] + "..."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_skip(text: str) -> bool:
    return text.strip().lower() in SKIP_MARKERS


def _is_cancel(text: str) -> bool:
    return text.strip().lower() in CANCEL_MARKERS


def _parse_discord_id(value: str) -> int | None:
    """
    Mention / ID / boşluklu girişten Discord ID çıkarmaya çalışır.
    """
    raw = value.strip()

    if not raw:
        return None

    mention = re.fullmatch(r"<@!?(\d+)>", raw)
    if mention:
        return int(mention.group(1))

    if raw.isdigit():
        return int(raw)

    return None


def _parse_roblox_username_hint(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None

    if raw.lower().startswith(("roblox:", "rbx:", "rbx=")):
        raw = raw.split(":", 1)[-1].split("=", 1)[-1].strip()

    if not raw:
        return None

    return raw


# ============================================================
# PAGES / VIEWS
# ============================================================


class BlacklistBaseView(discord.ui.View):
    def __init__(
        self,
        cog: "Blacklist",
        author_id: int,
        *,
        timeout: float = PANEL_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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

        if not self.cog.has_session(self.author_id):
            await interaction.response.send_message(
                "❌ Bu panel oturumu artık geçerli değil. `!blacklistpanel` ile yeniden aç.",
                ephemeral=True,
            )
            return False

        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        self.cog.clear_session(self.author_id)


class BlacklistQuickModal(discord.ui.Modal):
    """
    Hızlı giriş paneli.

    Tek satır formatı:
        discord:<id|mention> | roblox:<username> | reason

    Parçalar isteğe bağlıdır, ama en az bir hedef olmalı.
    """

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__(title="PAG Blacklist • Hızlı Giriş")
        self.cog = cog

        self.raw = discord.ui.TextInput(
            label="Tek Satır",
            placeholder="discord:@user | roblox:Username | sebep",
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=1,
            max_length=MAX_QUICK_RAW_LENGTH,
        )
        self.add_item(self.raw)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return
        except discord.HTTPException:
            self.cog.logger.exception("Quick modal defer failed.")
            return

        draft = self.cog.parse_quick_input(self.raw.value)
        if draft is None:
            await self.cog.safe_followup(
                interaction,
                "❌ Tek satır formatı çözümlenemedi.",
            )
            return

        if not draft.is_ready:
            await self.cog.safe_followup(
                interaction,
                "❌ En az bir hedef belirtmelisin. Discord kullanıcısı veya Roblox kullanıcı adı gir.",
            )
            return

        validation_error = self.cog.validate_draft(draft)
        if validation_error:
            await self.cog.safe_followup(
                interaction,
                f"❌ {validation_error}",
            )
            return

        self.cog.set_session(interaction.user.id, draft=draft)

        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Hızlı giriş uygulandı.",
        )


class BlacklistDiscordModal(discord.ui.Modal):
    def __init__(self, cog: "Blacklist") -> None:
        super().__init__(title="PAG Blacklist • Discord Hedef")
        self.cog = cog

        self.target_input = discord.ui.TextInput(
            label="Discord Kullanıcı ID / Mention",
            placeholder="@user veya 1234567890",
            required=True,
            min_length=1,
            max_length=50,
        )
        self.reason_input = discord.ui.TextInput(
            label="Sebep",
            placeholder="Sebep belirtilmedi.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=MAX_REASON_LENGTH,
        )
        self.add_item(self.target_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        discord_id = _parse_discord_id(self.target_input.value)
        if discord_id is None:
            await self.cog.safe_followup(
                interaction,
                "❌ Geçerli bir Discord ID veya mention gir.",
            )
            return

        draft = self.cog.get_draft(interaction.user.id) or BlacklistDraft()
        draft = replace(
            draft,
            discord_id=discord_id,
            discord_label=self.target_input.value.strip(),
            reason=self.cog.normalize_reason(self.reason_input.value),
        )

        validation_error = self.cog.validate_draft(draft)
        if validation_error:
            await self.cog.safe_followup(
                interaction,
                f"❌ {validation_error}",
            )
            return

        self.cog.set_session(interaction.user.id, draft=draft)

        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Discord hedefi kaydedildi.",
        )


class BlacklistRobloxModal(discord.ui.Modal):
    def __init__(self, cog: "Blacklist") -> None:
        super().__init__(title="PAG Blacklist • Roblox Hedef")
        self.cog = cog

        self.username_input = discord.ui.TextInput(
            label="Roblox Kullanıcı Adı",
            placeholder="Roblox username",
            required=True,
            min_length=3,
            max_length=20,
        )
        self.reason_input = discord.ui.TextInput(
            label="Sebep",
            placeholder="Sebep belirtilmedi.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=MAX_REASON_LENGTH,
        )
        self.add_item(self.username_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        username = _parse_roblox_username_hint(self.username_input.value)
        if not username:
            await self.cog.safe_followup(
                interaction,
                "❌ Roblox kullanıcı adı boş olamaz.",
            )
            return

        draft = self.cog.get_draft(interaction.user.id) or BlacklistDraft()
        draft = replace(
            draft,
            roblox_username=username,
            reason=self.cog.normalize_reason(self.reason_input.value),
        )

        validation_error = self.cog.validate_draft(draft)
        if validation_error:
            await self.cog.safe_followup(
                interaction,
                f"❌ {validation_error}",
            )
            return

        try:
            target = await self.cog.resolve_roblox_target(username)
        except RobloxNotFoundError:
            await self.cog.safe_followup(
                interaction,
                "❌ Roblox kullanıcısı bulunamadı.",
            )
            return
        except RobloxAPIError:
            self.cog.logger.exception("Roblox API error while resolving target.")
            await self.cog.safe_followup(
                interaction,
                "❌ Roblox API hatası oluştu.",
            )
            return
        except Exception:
            self.cog.logger.exception("Unexpected error while resolving Roblox target.")
            await self.cog.safe_followup(
                interaction,
                "❌ Roblox hedefi çözümlenirken beklenmeyen bir hata oluştu.",
            )
            return

        draft = replace(
            draft,
            roblox_id=target.roblox_id,
            roblox_display_name=target.roblox_display_name,
            avatar_url=target.avatar_url,
            roblox_username=target.roblox_username,
        )

        self.cog.set_session(interaction.user.id, draft=draft)

        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Roblox hedefi kaydedildi.",
        )


class BlacklistReasonModal(discord.ui.Modal):
    def __init__(self, cog: "Blacklist") -> None:
        super().__init__(title="PAG Blacklist • Sebep")
        self.cog = cog

        self.reason_input = discord.ui.TextInput(
            label="Sebep",
            placeholder="Blacklist sebebi...",
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=1,
            max_length=MAX_REASON_LENGTH,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        draft = self.cog.get_draft(interaction.user.id)
        if draft is None:
            await self.cog.safe_followup(
                interaction,
                "❌ Panel oturumu bulunamadı.",
            )
            return

        draft = replace(
            draft,
            reason=self.cog.normalize_reason(self.reason_input.value),
        )
        self.cog.set_session(interaction.user.id, draft=draft)

        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Sebep güncellendi.",
        )


class BlacklistRemoveModal(discord.ui.Modal):
    def __init__(self, cog: "Blacklist") -> None:
        super().__init__(title="PAG Blacklist • Kaldır")
        self.cog = cog

        self.target_input = discord.ui.TextInput(
            label="Discord ID / Roblox Username",
            placeholder="1234567890 veya RobloxAdı",
            required=True,
            min_length=1,
            max_length=50,
        )
        self.add_item(self.target_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        target_text = self.target_input.value.strip()
        if not target_text:
            await self.cog.safe_followup(
                interaction,
                "❌ Hedef boş olamaz.",
            )
            return

        operation = await self.cog.remove_by_text(
            moderator=interaction.user,
            target_text=target_text,
        )

        await self.cog.safe_followup(
            interaction,
            operation.message or "✅ Kayıt kaldırıldı.",
        )


class BlacklistPreviewView(BlacklistBaseView):
    def __init__(
        self,
        cog: "Blacklist",
        author_id: int,
    ) -> None:
        super().__init__(cog, author_id, timeout=PREVIEW_TIMEOUT_SECONDS)

    @discord.ui.button(
        label="Blacklist & Kick",
        emoji="🚫",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def send_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.cog.get_draft(self.author_id) is None:
            await interaction.response.send_message(
                "❌ Panel oturumu bulunamadı.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            result = await self.cog.execute_blacklist(
                moderator=interaction.user,
                kick_now=True,
            )
        except Exception:
            self.cog.logger.exception("Blacklist execution failed.")
            await self.cog.safe_followup(
                interaction,
                "❌ Blacklist işlemi sırasında beklenmeyen bir hata oluştu.",
            )
            return

        await self.cog.safe_followup(
            interaction,
            result.message or "✅ Blacklist tamamlandı.",
        )
        self.cog.clear_session(self.author_id)

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
                panel_name="Ana Panel",
            ),
            view=self.cog.build_view("main", self.author_id),
        )

    @discord.ui.button(
        label="Geri",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=0,
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
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.clear_session(self.author_id)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ İşlem iptal edildi.",
                embed=None,
                view=None,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ İşlem iptal edildi.",
                ephemeral=True,
            )


class BlacklistManageView(BlacklistBaseView):
    def __init__(self, cog: "Blacklist", author_id: int) -> None:
        super().__init__(cog, author_id, timeout=PANEL_TIMEOUT_SECONDS)

    @discord.ui.button(
        label="Kaldır",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def remove_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BlacklistRemoveModal(self.cog),
        )

    @discord.ui.button(
        label="Durum",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def status_button(
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
            embed=await self.cog.build_status_embed(
                draft,
                moderator=interaction.user,
            ),
            view=self,
        )

    @discord.ui.button(
        label="Geri",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=0,
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
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.clear_session(self.author_id)
        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ Yönetim paneli kapatıldı.",
                embed=None,
                view=None,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Yönetim paneli kapatıldı.",
                ephemeral=True,
            )


class BlacklistMainView(BlacklistBaseView):
    @discord.ui.button(
        label="Discord Hedef",
        emoji="👤",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def discord_target_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BlacklistDiscordModal(self.cog),
        )

    @discord.ui.button(
        label="Roblox Hedef",
        emoji="🎮",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def roblox_target_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BlacklistRobloxModal(self.cog),
        )

    @discord.ui.button(
        label="Sebep",
        emoji="📝",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def reason_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BlacklistReasonModal(self.cog),
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
            BlacklistQuickModal(self.cog),
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

        await interaction.response.edit_message(
            embed=await self.cog.build_preview_embed(draft),
            view=self.cog.build_view("preview", self.author_id),
        )

    @discord.ui.button(
        label="Yönetim",
        emoji="🧰",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def manage_button(
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
            embed=await self.cog.build_status_embed(
                draft,
                moderator=interaction.user,
            ),
            view=self.cog.build_view("manage", self.author_id),
        )

    @discord.ui.button(
        label="@everyone",
        emoji="📣",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def everyone_button(
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
        row=2,
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.set_session(
            self.author_id,
            BlacklistDraft(),
        )
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                self.cog.get_draft(self.author_id) or BlacklistDraft(),
                panel_name="Ana Panel",
            ),
            view=self,
        )

    @discord.ui.button(
        label="Kapat",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.cog.clear_session(self.author_id)

        for child in self.children:
            child.disabled = True

        try:
            await interaction.response.edit_message(
                content="❎ Blacklist paneli kapatıldı.",
                embed=None,
                view=None,
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "❎ Blacklist paneli kapatıldı.",
                ephemeral=True,
            )


# ============================================================
# COG
# ============================================================


class Blacklist(commands.Cog):
    """
    PAG Blacklist sistemi.

    Özellikler:
        - !blacklistpanel
        - !blacklist
        - !unblacklist
        - /blacklistpanel
        - /blacklist
        - /unblacklist
        - panel tabanlı akış
        - hızlı giriş
        - tek satır giriş
        - önizleme
        - yönetim paneli
        - aktif blacklist join koruması

    Not:
        Discord join koruması, active blacklist
        kaydı ve discord_id üzerinden çalışır.
        Roblox-only kayıtlar da saklanır; Roblox/Discord
        eşleşmesi geldikçe zenginleştirilir.
    """

    TABLE_NAME = "blacklist"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger: logging.Logger = bot.logger
        self.database = bot.database
        self.roblox_service: RobloxService = bot.roblox_service

        self._lock = asyncio.Lock()
        self._sessions: dict[int, BlacklistSession] = {}
        self._recent_actions: deque[str] = deque(maxlen=12)

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(self) -> None:
        await self._initialize_database()
        self.logger.info("Blacklist system initialized.")

    async def _initialize_database(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER UNIQUE,
                roblox_id INTEGER UNIQUE,
                roblox_username TEXT,
                reason TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_blacklist_active
            ON blacklist(active)
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_blacklist_discord
            ON blacklist(discord_id)
            """
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_blacklist_roblox
            ON blacklist(roblox_id)
            """
        )

    # ========================================================
    # SESSION
    # ========================================================

    def has_session(self, author_id: int) -> bool:
        return author_id in self._sessions

    def get_session(self, author_id: int) -> BlacklistSession | None:
        return self._sessions.get(author_id)

    def clear_session(self, author_id: int) -> None:
        self._sessions.pop(author_id, None)

    def set_session(
        self,
        author_id: int,
        draft: BlacklistDraft,
        *,
        channel_id: int | None = None,
        message_id: int | None = None,
        current_view: str | None = None,
    ) -> BlacklistSession:
        session = self._sessions.get(author_id)
        if session is None:
            session = BlacklistSession(draft=draft)
            self._sessions[author_id] = session

        session.draft = draft
        if channel_id is not None:
            session.panel_channel_id = channel_id
        if message_id is not None:
            session.panel_message_id = message_id
        if current_view is not None:
            session.current_view = current_view

        return session

    def get_draft(self, author_id: int) -> BlacklistDraft | None:
        session = self._sessions.get(author_id)
        return None if session is None else session.draft

    def _push_history(self, text: str) -> None:
        self._recent_actions.appendleft(
            f"{_now_iso()} • {text}"
        )

    # ========================================================
    # PARSING / VALIDATION
    # ========================================================

    def normalize_reason(self, reason: str | None) -> str:
        if not reason:
            return "Sebep belirtilmedi."

        value = reason.strip()
        if not value:
            return "Sebep belirtilmedi."

        return value[:MAX_REASON_LENGTH]

    def parse_quick_input(self, raw: str) -> BlacklistDraft | None:
        raw = raw.strip()
        if not raw:
            return None

        parts = [part.strip() for part in re.split(r"\s*\|\s*", raw)]
        if not parts:
            return None

        discord_id = None
        roblox_username = None
        reason = "Sebep belirtilmedi."

        for part in parts:
            low = part.lower()
            if low.startswith(("discord:", "dc:", "member:")):
                discord_id = _parse_discord_id(part.split(":", 1)[1])
            elif low.startswith(("roblox:", "rbx:", "username:")):
                roblox_username = _parse_roblox_username_hint(part.split(":", 1)[1])
            elif low.startswith(("reason:", "sebep:", "r:")):
                reason = self.normalize_reason(part.split(":", 1)[1])
            else:
                # ilk boş olmayan serbest metni hedef gibi değerlendir
                if discord_id is None and roblox_username is None:
                    parsed_id = _parse_discord_id(part)
                    if parsed_id is not None:
                        discord_id = parsed_id
                    else:
                        roblox_username = _parse_roblox_username_hint(part)
                else:
                    reason = self.normalize_reason(part)

        return BlacklistDraft(
            discord_id=discord_id,
            discord_label=str(discord_id) if discord_id else None,
            roblox_username=roblox_username,
            reason=reason,
            kick_now=True,
        )

    def validate_reason(self, reason: str) -> Optional[str]:
        if not reason.strip():
            return "Sebep boş bırakılamaz."

        if len(reason) > MAX_REASON_LENGTH:
            return "Sebep çok uzun."

        return None

    def validate_draft(self, draft: BlacklistDraft) -> Optional[str]:
        if not draft.is_ready:
            return "En az bir hedef belirtmelisin. Discord kullanıcısı veya Roblox kullanıcı adı girebilirsin."

        if draft.discord_id is None and draft.roblox_username is None:
            return "En az bir hedef belirtmelisin."

        if draft.roblox_username is not None:
            username = draft.roblox_username.strip()
            if len(username) < 3:
                return "Roblox kullanıcı adı çok kısa."
            if len(username) > 20:
                return "Roblox kullanıcı adı çok uzun."

        if draft.reason and len(draft.reason) > MAX_REASON_LENGTH:
            return "Sebep çok uzun."

        return None

    # ========================================================
    # RESOLUTION
    # ========================================================

    async def resolve_roblox_target(
        self,
        username: str,
    ) -> BlacklistResolvedTarget:
        user = await self.roblox_service.get_user_by_username(username)

        avatar_url = None
        try:
            avatar = await self.roblox_service.get_avatar(user.id)
            avatar_url = avatar.image_url
        except (RobloxNotFoundError, RobloxAPIError):
            avatar_url = None

        return BlacklistResolvedTarget(
            roblox_id=user.id,
            roblox_username=user.name,
            roblox_display_name=user.display_name,
            avatar_url=avatar_url,
        )

    async def resolve_discord_target(
        self,
        interaction: discord.Interaction,
        discord_id: int,
    ) -> BlacklistResolvedTarget:
        member = None
        if interaction.guild is not None:
            member = interaction.guild.get_member(discord_id)

        if member is None and interaction.guild is not None:
            try:
                member = await interaction.guild.fetch_member(discord_id)
            except discord.NotFound:
                member = None
            except discord.HTTPException:
                member = None

        return BlacklistResolvedTarget(
            discord_member=member,
            discord_id=discord_id,
        )

    # ========================================================
    # DATABASE HELPERS
    # ========================================================

    async def _find_active_record(
        self,
        *,
        discord_id: int | None = None,
        roblox_id: int | None = None,
    ) -> Any | None:
        conditions: list[str] = []
        params: list[Any] = []

        if discord_id is not None:
            conditions.append("discord_id = ?")
            params.append(discord_id)

        if roblox_id is not None:
            conditions.append("roblox_id = ?")
            params.append(roblox_id)

        if not conditions:
            return None

        query = (
            "SELECT * FROM blacklist WHERE ("
            + " OR ".join(conditions)
            + ") AND active = 1 "
            "ORDER BY id DESC LIMIT 1"
        )

        return await self.database.fetchone(query, tuple(params))

    async def _find_inactive_record(
        self,
        *,
        discord_id: int | None = None,
        roblox_id: int | None = None,
    ) -> Any | None:
        conditions: list[str] = []
        params: list[Any] = []

        if discord_id is not None:
            conditions.append("discord_id = ?")
            params.append(discord_id)

        if roblox_id is not None:
            conditions.append("roblox_id = ?")
            params.append(roblox_id)

        if not conditions:
            return None

        query = (
            "SELECT * FROM blacklist WHERE ("
            + " OR ".join(conditions)
            + ") AND active = 0 "
            "ORDER BY id DESC LIMIT 1"
        )

        return await self.database.fetchone(query, tuple(params))

    async def _upsert_record(
        self,
        *,
        target: BlacklistResolvedTarget,
        reason: str,
        added_by: int,
    ) -> tuple[Any | None, str]:
        """
        Aktif kayıt varsa günceller, yoksa ekler.
        """
        async with self._lock:
            existing = await self._find_active_record(
                discord_id=target.discord_id,
                roblox_id=target.roblox_id,
            )

            inactive_existing = None
            if existing is None:
                inactive_existing = await self._find_inactive_record(
                    discord_id=target.discord_id,
                    roblox_id=target.roblox_id,
                )

            now = _now_iso()

            if existing is not None:
                await self.database.execute(
                    """
                    UPDATE blacklist
                    SET
                        discord_id = ?,
                        roblox_id = ?,
                        roblox_username = ?,
                        reason = ?,
                        added_by = ?,
                        created_at = ?,
                        active = 1
                    WHERE id = ?
                    """,
                    (
                        target.discord_id,
                        target.roblox_id,
                        target.roblox_username,
                        reason,
                        added_by,
                        now,
                        existing["id"],
                    ),
                )
                return existing, "updated"

            if inactive_existing is not None:
                await self.database.execute(
                    """
                    UPDATE blacklist
                    SET
                        discord_id = ?,
                        roblox_id = ?,
                        roblox_username = ?,
                        reason = ?,
                        added_by = ?,
                        created_at = ?,
                        active = 1
                    WHERE id = ?
                    """,
                    (
                        target.discord_id,
                        target.roblox_id,
                        target.roblox_username,
                        reason,
                        added_by,
                        now,
                        inactive_existing["id"],
                    ),
                )
                return inactive_existing, "reactivated"

            await self.database.execute(
                """
                INSERT INTO blacklist (
                    discord_id,
                    roblox_id,
                    roblox_username,
                    reason,
                    added_by,
                    created_at,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    target.discord_id,
                    target.roblox_id,
                    target.roblox_username,
                    reason,
                    added_by,
                    now,
                ),
            )
            return None, "inserted"

    async def _deactivate_record(self, record: Any) -> None:
        await self.database.execute(
            """
            UPDATE blacklist
            SET active = 0
            WHERE id = ?
            """,
            (record["id"],),
        )

    async def _count_active(self) -> int:
        row = await self.database.fetchone(
            "SELECT COUNT(*) AS c FROM blacklist WHERE active = 1",
            (),
        )
        return int(row["c"]) if row else 0

    async def _latest_action_record(self) -> Any | None:
        return await self.database.fetchone(
            "SELECT * FROM blacklist ORDER BY id DESC LIMIT 1",
            (),
        )

    # ========================================================
    # EMBEDS
    # ========================================================

    async def build_panel_embed(
        self,
        draft: BlacklistDraft,
        *,
        panel_name: str,
    ) -> discord.Embed:
        count = await self._count_active()

        embed = discord.Embed(
            title="🚫 PAG BLACKLIST PANEL",
            description=(
                "Buradan blacklist ekleyebilir, düzenleyebilir, önizleyebilir ve kaldırabilirsin.\n\n"
                "Discord hedefi veya Roblox hedefi seç.\n"
                "İstersen tek satır hızlı giriş kullan.\n"
                "Göndermeden önce önizleme aç."
            ),
            color=discord.Color.dark_red() if draft.is_ready else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Panel",
            value=panel_name,
            inline=True,
        )
        embed.add_field(
            name="Durum",
            value="Hazır" if draft.is_ready else "Eksik",
            inline=True,
        )
        embed.add_field(
            name="Aktif Kayıt",
            value=f"`{count}`",
            inline=True,
        )
        embed.add_field(
            name="Discord",
            value=_truncate(draft.discord_label or ("<@" + str(draft.discord_id) + ">" if draft.discord_id else "—"), 256),
            inline=True,
        )
        embed.add_field(
            name="Roblox",
            value=_truncate(draft.roblox_username or "—", 256),
            inline=True,
        )
        embed.add_field(
            name="Sebep",
            value=_truncate(draft.reason or "Sebep belirtilmedi.", MAX_PANEL_NOTE_LENGTH),
            inline=False,
        )
        embed.add_field(
            name="Kick",
            value="Açık" if draft.kick_now else "Kapalı",
            inline=True,
        )
        embed.add_field(
            name="Hızlı Format",
            value="`discord:@user | roblox:Username | reason:sebep`",
            inline=False,
        )

        embed.set_footer(
            text="Panel • Butonlar ile hedef ekle, önizle ve gönder.",
        )

        if draft.avatar_url:
            embed.set_thumbnail(url=draft.avatar_url)

        return embed

    async def build_preview_embed(self, draft: BlacklistDraft) -> discord.Embed:
        title = "🚫 BLACKLIST ÖNİZLEME"
        if draft.roblox_display_name:
            title = f"🚫 {draft.roblox_display_name}"

        embed = discord.Embed(
            title=title,
            description="Blacklist işlemi gönderilmeden önce son kontrol.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        if draft.discord_id is not None:
            embed.add_field(
                name="Discord",
                value=f"<@{draft.discord_id}>\n`{draft.discord_id}`",
                inline=True,
            )

        if draft.roblox_username:
            embed.add_field(
                name="Roblox",
                value=(
                    f"**{_truncate(draft.roblox_username, 50)}**"
                    + (f"\n`{draft.roblox_id}`" if draft.roblox_id else "")
                ),
                inline=True,
            )

        embed.add_field(
            name="Sebep",
            value=_truncate(draft.reason, 1024),
            inline=False,
        )

        embed.add_field(
            name="Kick",
            value="Açık" if draft.kick_now else "Kapalı",
            inline=True,
        )

        embed.set_footer(
            text="Göndermeden önce doğrula.",
        )

        if draft.avatar_url:
            embed.set_thumbnail(url=draft.avatar_url)

        return embed

    async def build_status_embed(
        self,
        draft: BlacklistDraft,
        *,
        moderator: discord.Member | discord.User,
    ) -> discord.Embed:
        count = await self._count_active()
        latest = await self._latest_action_record()

        embed = discord.Embed(
            title="📊 BLACKLIST DURUM",
            description="Aktif kayıt ve son işlem bilgileri.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Aktif Kayıt",
            value=f"`{count}`",
            inline=True,
        )
        embed.add_field(
            name="Son İşlem",
            value=(
                f"`#{latest['id']}`"
                if latest is not None
                else "—"
            ),
            inline=True,
        )
        embed.add_field(
            name="Moderator",
            value=moderator.mention if isinstance(moderator, discord.Member) else str(moderator),
            inline=True,
        )

        embed.add_field(
            name="Discord Hedef",
            value=(
                f"<@{draft.discord_id}>"
                if draft.discord_id is not None
                else "—"
            ),
            inline=True,
        )
        embed.add_field(
            name="Roblox Hedef",
            value=_truncate(draft.roblox_username or "—", 256),
            inline=True,
        )
        embed.add_field(
            name="Sebep",
            value=_truncate(draft.reason or "Sebep belirtilmedi.", 1024),
            inline=False,
        )

        if latest is not None:
            embed.add_field(
                name="Son Kayıt",
                value=(
                    f"Discord: {latest['discord_id'] or '—'}\n"
                    f"Roblox: {latest['roblox_username'] or '—'}\n"
                    f"Durum: {'Aktif' if latest['active'] else 'Pasif'}"
                ),
                inline=False,
            )

        embed.set_footer(
            text="Durum • Kaldır, önizle, geri dön.",
        )

        if draft.avatar_url:
            embed.set_thumbnail(url=draft.avatar_url)

        return embed

    def build_view(self, kind: str, author_id: int) -> BlacklistBaseView:
        if kind == "preview":
            return BlacklistPreviewView(self, author_id)
        if kind == "manage":
            return BlacklistManageView(self, author_id)
        return BlacklistMainView(self, author_id)

    # ========================================================
    # PANEL REFRESH
    # ========================================================

    async def refresh_panel_message(
        self,
        *,
        author_id: int,
        notice: str | None = None,
    ) -> None:
        session = self.get_session(author_id)
        if session is None:
            return

        draft = session.draft
        channel_id = session.panel_channel_id
        message_id = session.panel_message_id

        if channel_id is None or message_id is None:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None and self.bot.guilds:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                channel = None

        if channel is None or not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return

        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            return

        try:
            await message.edit(
                embed=await self.build_panel_embed(
                    draft,
                    panel_name={
                        "main": "Ana Panel",
                        "detail": "Ayrıntılı Panel",
                        "preview": "Önizleme",
                        "manage": "Yönetim Paneli",
                        "history": "Geçmiş",
                    }.get(session.current_view, "Ana Panel"),
                ),
                view=self.build_view(session.current_view, author_id),
            )
        except Exception:
            pass

        if notice:
            # Ephemeral olmadan paneli kullanan admin için kısa geri bildirim.
            try:
                await channel.send(notice, delete_after=6)
            except Exception:
                pass

    # ========================================================
    # BLACKLIST CORE
    # ========================================================

    async def execute_blacklist(
        self,
        *,
        moderator: discord.Member | discord.User,
        kick_now: bool = True,
    ) -> "BlacklistOperation":
        """
        Mevcut session'daki veriyi blacklist'e yazar.

        Discord target varsa:
            - kayıt yazılır
            - guild içindeyse kick edilir

        Roblox target varsa:
            - kayıt yazılır
            - avatar / isim bilgisi saklanır
        """

        if not isinstance(moderator, (discord.Member, discord.User)):
            raise TypeError("Moderator must be a Discord user object.")

        session = self.get_session(moderator.id)
        if session is None:
            raise RuntimeError("Blacklist session not found.")

        draft = session.draft
        if not draft.is_ready:
            raise ValueError("Blacklist draft is not ready.")

        validation_error = self.validate_draft(draft)
        if validation_error:
            raise ValueError(validation_error)

        target = BlacklistResolvedTarget(
            discord_id=draft.discord_id,
            roblox_id=draft.roblox_id,
            roblox_username=draft.roblox_username,
            roblox_display_name=draft.roblox_display_name,
            avatar_url=draft.avatar_url,
        )

        # Roblox hedefi varsa tekrar çözümleyip güvence altına al.
        if target.roblox_username and target.roblox_id is None:
            roblox_target = await self.resolve_roblox_target(target.roblox_username)
            target.roblox_id = roblox_target.roblox_id
            target.roblox_display_name = roblox_target.roblox_display_name
            target.avatar_url = roblox_target.avatar_url
            target.roblox_username = roblox_target.roblox_username

        if target.discord_id is not None and target.discord_member is None:
            if moderator.guild is not None:
                member = moderator.guild.get_member(target.discord_id)
                if member is None:
                    try:
                        member = await moderator.guild.fetch_member(target.discord_id)
                    except Exception:
                        member = None
                target.discord_member = member

        record, action = await self._upsert_record(
            target=target,
            reason=draft.reason,
            added_by=moderator.id,
        )

        kicked = False
        kick_error: str | None = None

        if kick_now and target.discord_member is not None:
            try:
                await target.discord_member.kick(
                    reason=(
                        f"Blacklist: {draft.reason[:450]}"
                    )
                )
                kicked = True
            except discord.Forbidden:
                kick_error = "Botun bu üyeyi atmaya yetkisi yok."
            except discord.HTTPException:
                kick_error = "Kick işlemi sırasında Discord API hatası oluştu."
            except Exception:
                kick_error = "Kick işlemi sırasında beklenmeyen bir hata oluştu."

        self._push_history(
            f"{'GÜNCELLENDİ' if action != 'inserted' else 'EKLENDİ'} • "
            f"Discord={target.discord_id or '—'} • Roblox={target.roblox_username or '—'} • "
            f"Moderator={moderator.id}"
        )

        embed = discord.Embed(
            title="🚫 BLACKLIST",
            description=(
                "Hedef blacklist'e eklendi."
                if action == "inserted"
                else "Hedef blacklist kaydı güncellendi."
            ),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        if target.discord_id is not None:
            embed.add_field(
                name="Discord",
                value=f"<@{target.discord_id}>\n`{target.discord_id}`",
                inline=True,
            )

        if target.roblox_username:
            embed.add_field(
                name="Roblox",
                value=(
                    f"**{target.roblox_display_name or target.roblox_username}**\n"
                    f"`{target.roblox_id}`"
                ),
                inline=True,
            )

        embed.add_field(
            name="Sebep",
            value=_truncate(draft.reason, 1024),
            inline=False,
        )

        embed.add_field(
            name="Kick",
            value="Başarılı" if kicked else ("Atlandı" if target.discord_member is None else "Başarısız"),
            inline=True,
        )

        if kick_error:
            embed.add_field(
                name="Kick Notu",
                value=_truncate(kick_error, 1024),
                inline=False,
            )

        if target.avatar_url:
            embed.set_thumbnail(url=target.avatar_url)

        return type(
            "BlacklistOperation",
            (),
            {
                "result": "success",
                "target": target,
                "record": record,
                "message": "✅ Blacklist tamamlandı."
                + (" Hedef sunucudan atıldı." if kicked else "")
                + (f" ({kick_error})" if kick_error else ""),
                "embed": embed,
            },
        )()

    async def remove_by_text(
        self,
        *,
        moderator: discord.Member | discord.User,
        target_text: str,
    ) -> "BlacklistOperation":
        """
        Discord ID / Roblox username ile kayıt kaldırır.
        """
        target_text = target_text.strip()
        if not target_text:
            raise ValueError("Hedef boş olamaz.")

        discord_id = _parse_discord_id(target_text)
        roblox_username = None if discord_id is not None else _parse_roblox_username_hint(target_text)

        record = None
        if discord_id is not None:
            record = await self._find_active_record(discord_id=discord_id)
        elif roblox_username is not None:
            # Roblox username ile aktif kayıt araması.
            record = await self.database.fetchone(
                """
                SELECT *
                FROM blacklist
                WHERE roblox_username = ? AND active = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (roblox_username,),
            )

        if record is None:
            return type(
                "BlacklistOperation",
                (),
                {
                    "result": "not_found",
                    "record": None,
                    "message": "❌ Kaldırılacak aktif blacklist kaydı bulunamadı.",
                },
            )()

        await self._deactivate_record(record)

        self._push_history(
            f"KALDIRILDI • Discord={record['discord_id'] or '—'} • Roblox={record['roblox_username'] or '—'} • Moderator={moderator.id}"
        )

        embed = discord.Embed(
            title="✅ UNBLACKLIST",
            description="Aktif blacklist kaydı kaldırıldı.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

        if record["discord_id"]:
            embed.add_field(
                name="Discord",
                value=f"<@{record['discord_id']}>\n`{record['discord_id']}`",
                inline=True,
            )

        if record["roblox_username"]:
            embed.add_field(
                name="Roblox",
                value=f"**{record['roblox_username']}**",
                inline=True,
            )

        embed.add_field(
            name="Sebep",
            value=_truncate(str(record["reason"]), 1024),
            inline=False,
        )
        embed.add_field(
            name="Durum",
            value="🟢 Pasif",
            inline=True,
        )

        return type(
            "BlacklistOperation",
            (),
            {
                "result": "success",
                "record": record,
                "message": "✅ Kayıt kaldırıldı.",
                "embed": embed,
            },
        )()

    # ========================================================
    # COMMANDS: PANEL
    # ========================================================

    @app_commands.command(
        name="blacklistpanel",
        description="Blacklist yönetim panelini açar.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def blacklistpanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komut yalnızca sunucularda kullanılabilir.",
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await self.safe_initial_response(
                interaction,
                content="❌ Sunucu üye bilgisi alınamadı.",
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komutu yalnızca Administrator kullanabilir.",
            )
            return

        draft = BlacklistDraft()
        self.set_session(interaction.user.id, draft=draft)

        embed = await self.build_panel_embed(draft, panel_name="Ana Panel")
        view = self.build_view("main", interaction.user.id)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=False,
        )

        try:
            session = self.get_session(interaction.user.id)
            if session is not None:
                session.panel_channel_id = interaction.channel_id
                session.panel_message_id = interaction.original_response().id if False else None
        except Exception:
            # original_response() burada kullanılmayabilir; panel yine çalışır.
            pass

    @commands.command(name="blacklistpanel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def blacklistpanel_prefix(
        self,
        ctx: commands.Context,
        *,
        raw: str | None = None,
    ) -> None:
        draft = BlacklistDraft()

        if raw and raw.strip():
            parsed = self.parse_quick_input(raw)
            if parsed is not None:
                draft = parsed

        self.set_session(ctx.author.id, draft=draft)

        embed = await self.build_panel_embed(draft, panel_name="Ana Panel")
        view = self.build_view("main", ctx.author.id)

        sent = await ctx.send(embed=embed, view=view)

        session = self.get_session(ctx.author.id)
        if session is not None:
            session.panel_channel_id = sent.channel.id
            session.panel_message_id = sent.id
            session.current_view = "main"

    # ========================================================
    # COMMANDS: BLACKLIST
    # ========================================================

    @app_commands.command(
        name="blacklist",
        description="Bir kullanıcıyı blacklist'e ekler.",
    )
    @app_commands.describe(
        member="Discord kullanıcısı.",
        roblox_username="Roblox kullanıcı adı.",
        reason="Blacklist sebebi.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def blacklist(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        roblox_username: str | None = None,
        reason: str = "Sebep belirtilmedi.",
    ) -> None:
        if interaction.guild is None:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komut yalnızca sunucularda kullanılabilir.",
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await self.safe_initial_response(
                interaction,
                content="❌ Sunucu üye bilgisi alınamadı.",
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await self.safe_initial_response(
                interaction,
                content="❌ Bu komutu yalnızca Administrator kullanabilir.",
            )
            return

        if member is None and not roblox_username:
            # Panel aç.
            await self.blacklistpanel(interaction)
            return

        draft = BlacklistDraft(
            discord_id=member.id if member else None,
            discord_label=member.display_name if member else None,
            roblox_username=_parse_roblox_username_hint(roblox_username or "") if roblox_username else None,
            reason=self.normalize_reason(reason),
            kick_now=True,
        )

        if draft.roblox_username:
            try:
                target = await self.resolve_roblox_target(draft.roblox_username)
                draft = replace(
                    draft,
                    roblox_id=target.roblox_id,
                    roblox_display_name=target.roblox_display_name,
                    avatar_url=target.avatar_url,
                    roblox_username=target.roblox_username,
                )
            except RobloxNotFoundError:
                await self.safe_initial_response(
                    interaction,
                    content="❌ Roblox kullanıcısı bulunamadı.",
                )
                return
            except RobloxAPIError:
                await self.safe_initial_response(
                    interaction,
                    content="❌ Roblox API hatası oluştu.",
                )
                return
            except Exception:
                self.logger.exception("Unexpected Roblox resolution error.")
                await self.safe_initial_response(
                    interaction,
                    content="❌ Roblox hedefi çözümlenirken beklenmeyen bir hata oluştu.",
                )
                return

        self.set_session(interaction.user.id, draft=draft)
        result = await self.execute_blacklist(
            moderator=interaction.user,
            kick_now=True,
        )

        await self.safe_initial_response(
            interaction,
            content=result.message or "✅ Blacklist tamamlandı.",
        )
        # İstersen panel de açık kalsın; burada temizliyoruz.
        self.clear_session(interaction.user.id)

    @commands.command(name="blacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def blacklist_prefix(
        self,
        ctx: commands.Context,
        target: str | None = None,
        *,
        reason: str = "Sebep belirtilmedi.",
    ) -> None:
        if target is None:
            await self.blacklistpanel_prefix(ctx)
            return

        discord_id = _parse_discord_id(target)
        roblox_username = None if discord_id is not None else _parse_roblox_username_hint(target)

        draft = BlacklistDraft(
            discord_id=discord_id,
            discord_label=target if discord_id else None,
            roblox_username=roblox_username,
            reason=self.normalize_reason(reason),
            kick_now=True,
        )

        if draft.roblox_username:
            try:
                target_resolved = await self.resolve_roblox_target(draft.roblox_username)
                draft = replace(
                    draft,
                    roblox_id=target_resolved.roblox_id,
                    roblox_display_name=target_resolved.roblox_display_name,
                    avatar_url=target_resolved.avatar_url,
                    roblox_username=target_resolved.roblox_username,
                )
            except RobloxNotFoundError:
                await ctx.send("❌ Roblox kullanıcısı bulunamadı.")
                return
            except RobloxAPIError:
                await ctx.send("❌ Roblox API hatası oluştu.")
                return
            except Exception:
                self.logger.exception("Unexpected Roblox resolution error.")
                await ctx.send("❌ Roblox hedefi çözümlenirken beklenmeyen bir hata oluştu.")
                return

        self.set_session(ctx.author.id, draft=draft)

        try:
            result = await self.execute_blacklist(
                moderator=ctx.author,
                kick_now=True,
            )
        except Exception:
            self.logger.exception("Blacklist prefix execution failed.")
            await ctx.send("❌ Blacklist işlemi sırasında beklenmeyen bir hata oluştu.")
            return
        finally:
            self.clear_session(ctx.author.id)

        await ctx.send(
            result.message or "✅ Blacklist tamamlandı.",
        )
        if hasattr(result, "embed"):
            try:
                await ctx.send(embed=result.embed)
            except Exception:
                pass

    # ========================================================
    # COMMANDS: UNBLACKLIST
    # ========================================================

    @app_commands.command(
        name="unblacklist",
        description="Aktif blacklist kaydını kaldırır.",
    )
    @app_commands.describe(
        target="Discord ID / Mention / Roblox username.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def unblacklist(
        self,
        interaction: discord.Interaction,
        target: str | None = None,
    ) -> None:
        if target is None:
            await self.safe_initial_response(
                interaction,
                content="❌ Hedef belirtmelisin.",
            )
            return

        result = await self.remove_by_text(
            moderator=interaction.user,
            target_text=target,
        )

        await self.safe_initial_response(
            interaction,
            content=result.message or "✅ Kayıt kaldırıldı.",
        )

    @commands.command(name="unblacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def unblacklist_prefix(
        self,
        ctx: commands.Context,
        target: str | None = None,
    ) -> None:
        if target is None:
            await ctx.send("❌ Hedef belirtmelisin.")
            return

        result = await self.remove_by_text(
            moderator=ctx.author,
            target_text=target,
        )
        await ctx.send(result.message or "✅ Kayıt kaldırıldı.")

    # ========================================================
    # MEMBER JOIN ENFORCEMENT
    # ========================================================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """
        Discord tarafı soft-ban / rejoin engeli.

        Discord ID kayıtlı aktif blacklist varsa:
            - üye anında kick edilir
            - bu, ban gibi davranır ama ban değildir
        """
        try:
            record = await self._find_active_record(discord_id=member.id)
            if record is None:
                return

            reason = f"Blacklist: {str(record['reason'])[:450]}"

            await member.kick(reason=reason)

            self._push_history(
                f"JOIN KICK • Discord={member.id} • Reason={str(record['reason'])[:80]}"
            )

            self.logger.info(
                "Blacklisted member kicked on join: %s (%s)",
                member.id,
                member.guild.id,
            )

        except discord.Forbidden:
            self.logger.warning(
                "Missing permissions to kick blacklisted member on join: %s",
                member.id,
            )
        except discord.HTTPException:
            self.logger.exception(
                "Discord API error while kicking blacklisted member on join: %s",
                member.id,
            )
        except Exception:
            self.logger.exception(
                "Unexpected error in on_member_join for blacklisted member: %s",
                member.id,
            )

    # ========================================================
    # BUILD DRAFT UPDATE HELPERS
    # ========================================================

    def update_draft_field(self, author_id: int, field_key: str, value: str) -> BlacklistDraft | None:
        draft = self.get_draft(author_id)
        if draft is None:
            return None

        if field_key == "reason":
            draft = replace(draft, reason=self.normalize_reason(value))
        elif field_key == "discord":
            discord_id = _parse_discord_id(value)
            if discord_id is None:
                return draft
            draft = replace(draft, discord_id=discord_id, discord_label=value.strip())
        elif field_key == "roblox":
            username = _parse_roblox_username_hint(value)
            if username is None:
                return draft
            draft = replace(draft, roblox_username=username)
        elif field_key == "kick":
            draft = replace(draft, kick_now=value.strip().lower() in {"1", "true", "yes", "on", "evet"})
        else:
            return draft

        self.set_session(author_id, draft=draft)
        return draft

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
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except discord.NotFound:
            self.logger.warning("Interaction expired before response.")
        except discord.HTTPException:
            self.logger.exception("Failed to send interaction response.")

    async def safe_followup(
        self,
        interaction: discord.Interaction,
        content: str,
    ) -> None:
        try:
            await interaction.followup.send(content, ephemeral=True)
        except discord.NotFound:
            self.logger.warning("Interaction expired before followup.")
        except discord.HTTPException:
            self.logger.exception("Failed to send followup response.")

    # ========================================================
    # ERROR HANDLERS
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ Bu komut için Administrator yetkisi gerekir."
        else:
            self.logger.exception("Blacklist slash command error.")
            message = "❌ Beklenmeyen bir hata oluştu."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Bu komut için Administrator yetkisi gerekir.", delete_after=8)
            return

        if isinstance(error, commands.CommandNotFound):
            return

        self.logger.exception("Blacklist prefix command error.")
        await ctx.send("❌ Beklenmeyen bir hata oluştu.", delete_after=8)

    # ========================================================
    # ADDITIONAL UTILITIES
    # ========================================================

    def normalize_reason(self, reason: str | None) -> str:
        if not reason:
            return "Sebep belirtilmedi."

        cleaned = reason.strip()
        if not cleaned:
            return "Sebep belirtilmedi."

        return cleaned[:MAX_REASON_LENGTH]


# ============================================================
# SETUP
# ============================================================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Blacklist(bot),
    )