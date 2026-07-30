
from __future__ import annotations

import asyncio
import logging
import re
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


MAX_REASON_LENGTH = 1000
MAX_RAW_LENGTH = 3000
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


@dataclass(slots=True, frozen=True)
class BlacklistDraft:
    discord_id: int | None = None
    discord_label: str | None = None
    roblox_id: int | None = None
    roblox_username: str | None = None
    roblox_display_name: str | None = None
    avatar_url: str | None = None
    reason: str = "Sebep belirtilmedi."
    kick_now: bool = True
    announcement_channel_id: int | None = None

    @property
    def is_ready(self) -> bool:
        return self.discord_id is not None or self.roblox_username is not None


@dataclass(slots=True)
class BlacklistSession:
    draft: BlacklistDraft
    panel_channel_id: int | None = None
    panel_message_id: int | None = None
    current_view: str = "main"


@dataclass(slots=True, frozen=True)
class BlacklistRecord:
    id: int
    discord_id: int | None
    roblox_id: int | None
    roblox_username: str | None
    reason: str
    added_by: int
    created_at: str
    active: bool
    announcement_channel_id: int | None = None

    @classmethod
    def from_row(cls, row: Any) -> "BlacklistRecord":
        keys = set(row.keys())
        return cls(
            id=int(row["id"]),
            discord_id=int(row["discord_id"]) if row["discord_id"] is not None else None,
            roblox_id=int(row["roblox_id"]) if row["roblox_id"] is not None else None,
            roblox_username=str(row["roblox_username"]) if row["roblox_username"] is not None else None,
            reason=str(row["reason"]),
            added_by=int(row["added_by"]),
            created_at=str(row["created_at"]),
            active=bool(row["active"]),
            announcement_channel_id=(
                int(row["announcement_channel_id"])
                if "announcement_channel_id" in keys and row["announcement_channel_id"] is not None
                else None
            ),
        )


@dataclass(slots=True, frozen=True)
class BlacklistTarget:
    discord_id: int | None = None
    roblox_id: int | None = None
    roblox_username: str | None = None
    roblox_display_name: str | None = None
    avatar_url: str | None = None


@dataclass(slots=True)
class BlacklistOperationResult:
    success: bool
    action: str
    message: str
    record: BlacklistRecord | None = None
    target: BlacklistTarget | None = None
    kicked: bool = False
    kick_error: str | None = None
    announcement_channel_id: int | None = None
    public_embed: discord.Embed | None = None


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return "—"
    value = text.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_discord_id(value: str) -> int | None:
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
    lowered = raw.lower()
    if lowered.startswith(("roblox:", "rbx:", "username:")):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return None
    return raw


def _is_skip(text: str) -> bool:
    return text.strip().lower() in SKIP_MARKERS


def _is_cancel(text: str) -> bool:
    return text.strip().lower() in CANCEL_MARKERS


class BlacklistQuickModal(discord.ui.Modal, title="PAG Blacklist • Hızlı Giriş"):
    raw = discord.ui.TextInput(
        label="Tek Satır Giriş",
        placeholder="discord:@user | roblox:Username | reason:Sebep",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=1,
        max_length=MAX_RAW_LENGTH,
    )

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        draft = self.cog.parse_quick_input(self.raw.value)
        if draft is None:
            await self.cog.safe_followup(interaction, "❌ Tek satır formatı çözümlenemedi.")
            return

        error = self.cog.validate_draft(draft)
        if error:
            await self.cog.safe_followup(interaction, f"❌ {error}")
            return

        self.cog.set_session(
            interaction.user.id,
            draft=draft,
            channel_id=interaction.channel_id,
            current_view="main",
        )
        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Hızlı giriş uygulandı.",
        )


class BlacklistDiscordModal(discord.ui.Modal, title="PAG Blacklist • Discord Hedef"):
    target = discord.ui.TextInput(
        label="Discord Kullanıcı ID / Mention",
        placeholder="@user veya 1234567890",
        required=True,
        min_length=1,
        max_length=50,
    )
    reason = discord.ui.TextInput(
        label="Sebep",
        placeholder="Sebep belirtilmedi.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_REASON_LENGTH,
    )

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        discord_id = _parse_discord_id(self.target.value)
        if discord_id is None:
            await self.cog.safe_followup(interaction, "❌ Geçerli bir Discord ID veya mention gir.")
            return

        draft = self.cog.get_draft(interaction.user.id) or BlacklistDraft()
        draft = replace(
            draft,
            discord_id=discord_id,
            discord_label=self.target.value.strip(),
            reason=self.cog.normalize_reason(self.reason.value),
        )

        error = self.cog.validate_draft(draft)
        if error:
            await self.cog.safe_followup(interaction, f"❌ {error}")
            return

        self.cog.set_session(
            interaction.user.id,
            draft=draft,
            channel_id=interaction.channel_id,
            current_view="main",
        )
        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Discord hedefi kaydedildi.",
        )


class BlacklistRobloxModal(discord.ui.Modal, title="PAG Blacklist • Roblox Hedef"):
    username = discord.ui.TextInput(
        label="Roblox Kullanıcı Adı",
        placeholder="Roblox username",
        required=True,
        min_length=3,
        max_length=20,
    )
    reason = discord.ui.TextInput(
        label="Sebep",
        placeholder="Sebep belirtilmedi.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_REASON_LENGTH,
    )

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        username = _parse_roblox_username_hint(self.username.value)
        if not username:
            await self.cog.safe_followup(interaction, "❌ Roblox kullanıcı adı boş olamaz.")
            return

        draft = self.cog.get_draft(interaction.user.id) or BlacklistDraft()
        draft = replace(
            draft,
            roblox_username=username,
            reason=self.cog.normalize_reason(self.reason.value),
        )

        try:
            resolved = await self.cog.resolve_roblox_target(username)
        except RobloxNotFoundError:
            await self.cog.safe_followup(interaction, "❌ Roblox kullanıcısı bulunamadı.")
            return
        except RobloxAPIError:
            self.cog.logger.exception("Roblox API error while resolving target.")
            await self.cog.safe_followup(interaction, "❌ Roblox API hatası oluştu.")
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
            roblox_id=resolved.roblox_id,
            roblox_username=resolved.roblox_username,
            roblox_display_name=resolved.roblox_display_name,
            avatar_url=resolved.avatar_url,
        )

        self.cog.set_session(
            interaction.user.id,
            draft=draft,
            channel_id=interaction.channel_id,
            current_view="main",
        )
        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Roblox hedefi kaydedildi.",
        )


class BlacklistReasonModal(discord.ui.Modal, title="PAG Blacklist • Sebep"):
    reason = discord.ui.TextInput(
        label="Sebep",
        placeholder="Blacklist sebebi...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=1,
        max_length=MAX_REASON_LENGTH,
    )

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        draft = self.cog.get_draft(interaction.user.id)
        if draft is None:
            await self.cog.safe_followup(interaction, "❌ Panel oturumu bulunamadı.")
            return

        draft = replace(draft, reason=self.cog.normalize_reason(self.reason.value))
        self.cog.set_session(
            interaction.user.id,
            draft=draft,
            channel_id=interaction.channel_id,
            current_view="main",
        )
        await self.cog.refresh_panel_message(
            author_id=interaction.user.id,
            notice="✅ Sebep güncellendi.",
        )


class BlacklistRemoveModal(discord.ui.Modal, title="PAG Blacklist • Kaldır"):
    target = discord.ui.TextInput(
        label="Discord ID / Roblox Username",
        placeholder="1234567890 veya RobloxAdı",
        required=True,
        min_length=1,
        max_length=50,
    )

    def __init__(self, cog: "Blacklist") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            return

        result = await self.cog.remove_by_text(
            moderator=interaction.user,
            target_text=self.target.value,
            announce_channel_id=interaction.channel_id,
        )
        await self.cog.safe_followup(interaction, result.message)


class BlacklistBaseView(discord.ui.View):
    def __init__(self, cog: "Blacklist", author_id: int, *, timeout: float = PANEL_TIMEOUT_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Bu panel sana ait değil.", ephemeral=True)
            return False

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Sunucu üye bilgisi alınamadı.", ephemeral=True)
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Bu panel için Administrator yetkisi gerekir.", ephemeral=True)
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


class BlacklistMainView(BlacklistBaseView):
    @discord.ui.button(label="Discord Hedef", emoji="👤", style=discord.ButtonStyle.primary, row=0)
    async def discord_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BlacklistDiscordModal(self.cog))

    @discord.ui.button(label="Roblox Hedef", emoji="🎮", style=discord.ButtonStyle.primary, row=0)
    async def roblox_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BlacklistRobloxModal(self.cog))

    @discord.ui.button(label="Sebep", emoji="📝", style=discord.ButtonStyle.secondary, row=0)
    async def reason_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BlacklistReasonModal(self.cog))

    @discord.ui.button(label="Tek Satır", emoji="⚡", style=discord.ButtonStyle.success, row=1)
    async def quick_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BlacklistQuickModal(self.cog))

    @discord.ui.button(label="Önizleme", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_preview_embed(draft),
            view=self.cog.build_view("preview", self.author_id),
        )

    @discord.ui.button(label="Yönetim", emoji="🧰", style=discord.ButtonStyle.secondary, row=1)
    async def manage_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_manage_embed(draft),
            view=self.cog.build_view("manage", self.author_id),
        )

    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_kick_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.toggle_kick(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(draft, panel_name="Ana Panel"),
            view=self,
        )

    @discord.ui.button(label="Sıfırla", emoji="🧹", style=discord.ButtonStyle.danger, row=2)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog.set_session(
            self.author_id,
            BlacklistDraft(announcement_channel_id=interaction.channel_id),
            channel_id=interaction.channel_id,
            current_view="main",
        )
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(
                self.cog.get_draft(self.author_id) or BlacklistDraft(),
                panel_name="Ana Panel",
            ),
            view=self,
        )

    @discord.ui.button(label="Kapat", emoji="✖️", style=discord.ButtonStyle.secondary, row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog.clear_session(self.author_id)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(content="❎ Blacklist paneli kapatıldı.", embed=None, view=None)
        except discord.HTTPException:
            await interaction.response.send_message("❎ Blacklist paneli kapatıldı.", ephemeral=True)


class BlacklistPreviewView(BlacklistBaseView):
    def __init__(self, cog: "Blacklist", author_id: int) -> None:
        super().__init__(cog, author_id, timeout=PREVIEW_TIMEOUT_SECONDS)
        self._sending = False

    @discord.ui.button(label="Blacklist & Kick", emoji="✅", style=discord.ButtonStyle.danger, row=0)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._sending:
            await interaction.response.send_message("⏳ İşlem zaten sürüyor.", ephemeral=True)
            return

        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return

        error = self.cog.validate_draft(draft)
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        self._sending = True
        try:
            await interaction.response.defer(ephemeral=True)
            result = await self.cog.execute_blacklist(
                moderator=interaction.user,
                kick_now=draft.kick_now,
                announce_channel_id=interaction.channel_id,
            )

            if result.public_embed is not None:
                await self.cog.send_public_embed(interaction.channel_id, result.public_embed)

            self.cog.clear_session(self.author_id)
            for child in self.children:
                child.disabled = True

            try:
                await interaction.edit_original_response(content=result.message, embed=None, view=None)
            except discord.HTTPException:
                pass

        except discord.Forbidden:
            await interaction.followup.send("❌ Discord botun bu üyeyi işlemeye yetkili değil.", ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send("❌ Kanal veya interaction artık bulunamıyor.", ephemeral=True)
        except discord.HTTPException:
            self.cog.logger.exception("Discord API error while sending blacklist.")
            await interaction.followup.send("❌ Discord API hatası oluştu.", ephemeral=True)
        except Exception:
            self.cog.logger.exception("Unexpected error while sending blacklist.")
            await interaction.followup.send("❌ Blacklist işlemi sırasında beklenmeyen bir hata oluştu.", ephemeral=True)
        finally:
            self._sending = False

    @discord.ui.button(label="Düzenle", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(draft, panel_name="Ana Panel"),
            view=self.cog.build_view("main", self.author_id),
        )

    @discord.ui.button(label="Ana Panel", emoji="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def main_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(draft, panel_name="Ana Panel"),
            view=self.cog.build_view("main", self.author_id),
        )

    @discord.ui.button(label="İptal", emoji="✖️", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog.clear_session(self.author_id)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(content="❎ Blacklist işlemi iptal edildi.", embed=None, view=None)
        except discord.HTTPException:
            await interaction.response.send_message("❎ Blacklist işlemi iptal edildi.", ephemeral=True)


class BlacklistManageView(BlacklistBaseView):
    @discord.ui.button(label="Kaldır", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BlacklistRemoveModal(self.cog))

    @discord.ui.button(label="Geçmiş", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=await self.cog.build_history_embed(),
            view=self,
        )

    @discord.ui.button(label="Duyuru Kanalı", emoji="📢", style=discord.ButtonStyle.secondary, row=0)
    async def channel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        draft = replace(draft, announcement_channel_id=interaction.channel_id)
        self.cog.set_session(
            self.author_id,
            draft=draft,
            channel_id=interaction.channel_id,
            current_view="manage",
        )
        await interaction.response.edit_message(
            embed=await self.cog.build_manage_embed(draft),
            view=self,
        )

    @discord.ui.button(label="Geri", emoji="↩️", style=discord.ButtonStyle.primary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        draft = self.cog.get_draft(self.author_id)
        if draft is None:
            await interaction.response.send_message("❌ Panel oturumu bulunamadı.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=await self.cog.build_panel_embed(draft, panel_name="Ana Panel"),
            view=self.cog.build_view("main", self.author_id),
        )

    @discord.ui.button(label="İptal", emoji="✖️", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog.clear_session(self.author_id)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(content="❎ Yönetim paneli kapatıldı.", embed=None, view=None)
        except discord.HTTPException:
            await interaction.response.send_message("❎ Yönetim paneli kapatıldı.", ephemeral=True)


class Blacklist(commands.Cog):
    TABLE_NAME = "blacklist"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger: logging.Logger = bot.logger
        self.database = bot.database
        self.roblox_service: RobloxService = bot.roblox_service

        self._lock = asyncio.Lock()
        self._sessions: dict[int, BlacklistSession] = {}
        self._history: list[str] = []

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
                active INTEGER NOT NULL DEFAULT 1,
                announcement_channel_id INTEGER
            )
            """
        )

        rows = await self.database.fetchall("PRAGMA table_info(blacklist)", ())
        columns = {row["name"] for row in rows}
        if "announcement_channel_id" not in columns:
            try:
                await self.database.execute(
                    "ALTER TABLE blacklist ADD COLUMN announcement_channel_id INTEGER"
                )
            except Exception:
                pass

        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_blacklist_active ON blacklist(active)"
        )
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_blacklist_discord ON blacklist(discord_id)"
        )
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_blacklist_roblox ON blacklist(roblox_id)"
        )

    def has_session(self, author_id: int) -> bool:
        return author_id in self._sessions

    def get_session(self, author_id: int) -> BlacklistSession | None:
        return self._sessions.get(author_id)

    def clear_session(self, author_id: int) -> None:
        self._sessions.pop(author_id, None)

    def get_draft(self, author_id: int) -> BlacklistDraft | None:
        session = self._sessions.get(author_id)
        return None if session is None else session.draft

    def set_session(
        self,
        author_id: int,
        *,
        draft: BlacklistDraft,
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

    def toggle_kick(self, author_id: int) -> BlacklistDraft | None:
        draft = self.get_draft(author_id)
        if draft is None:
            return None
        updated = replace(draft, kick_now=not draft.kick_now)
        self.set_session(author_id, draft=updated)
        return updated

    def _push_history(self, text: str) -> None:
        self._history.insert(0, f"{_now_iso()} • {text}")
        if len(self._history) > 20:
            self._history.pop()

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
            announcement_channel_id=None,
        )

    def validate_draft(self, draft: BlacklistDraft) -> Optional[str]:
        if not draft.is_ready:
            return "En az bir hedef belirtmelisin."

        if draft.roblox_username is not None:
            if len(draft.roblox_username.strip()) < 3:
                return "Roblox kullanıcı adı çok kısa."
            if len(draft.roblox_username.strip()) > 20:
                return "Roblox kullanıcı adı çok uzun."

        if draft.reason and len(draft.reason) > MAX_REASON_LENGTH:
            return "Sebep çok uzun."

        return None

    async def resolve_roblox_target(self, username: str) -> BlacklistTarget:
        user = await self.roblox_service.get_user_by_username(username)
        avatar_url = None
        try:
            avatar = await self.roblox_service.get_avatar(user.id)
            avatar_url = avatar.image_url
        except (RobloxNotFoundError, RobloxAPIError):
            avatar_url = None

        return BlacklistTarget(
            roblox_id=user.id,
            roblox_username=user.name,
            roblox_display_name=user.display_name,
            avatar_url=avatar_url,
        )

    async def get_by_id(self, record_id: int) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"SELECT * FROM {self.TABLE_NAME} WHERE id = ? LIMIT 1",
            (record_id,),
        )
        return BlacklistRecord.from_row(row) if row else None

    async def get_active_by_discord_id(self, discord_id: int) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE discord_id = ? AND active = 1
            ORDER BY id DESC LIMIT 1
            """,
            (discord_id,),
        )
        return BlacklistRecord.from_row(row) if row else None

    async def get_active_by_roblox_id(self, roblox_id: int) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE roblox_id = ? AND active = 1
            ORDER BY id DESC LIMIT 1
            """,
            (roblox_id,),
        )
        return BlacklistRecord.from_row(row) if row else None

    async def get_active_by_roblox_username(self, roblox_username: str) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE roblox_username = ? AND active = 1
            ORDER BY id DESC LIMIT 1
            """,
            (roblox_username.strip(),),
        )
        return BlacklistRecord.from_row(row) if row else None

    async def count_active(self) -> int:
        row = await self.database.fetchone(
            f"SELECT COUNT(*) AS c FROM {self.TABLE_NAME} WHERE active = 1",
            (),
        )
        return int(row["c"]) if row else 0

    async def list_recent(self, *, limit: int = 20) -> list[BlacklistRecord]:
        rows = await self.database.fetchall(
            f"SELECT * FROM {self.TABLE_NAME} ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [BlacklistRecord.from_row(row) for row in rows]

    async def search(self, query: str, *, limit: int = 20) -> list[BlacklistRecord]:
        q = query.strip()
        if not q:
            return []
        like = f"%{q}%"
        rows = await self.database.fetchall(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE
                CAST(discord_id AS TEXT) LIKE ?
                OR CAST(roblox_id AS TEXT) LIKE ?
                OR LOWER(COALESCE(roblox_username, '')) LIKE LOWER(?)
                OR LOWER(reason) LIKE LOWER(?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        )
        return [BlacklistRecord.from_row(row) for row in rows]

    async def _find_matching_active_record(
        self,
        *,
        discord_id: int | None,
        roblox_id: int | None,
        roblox_username: str | None,
    ) -> BlacklistRecord | None:
        candidates: list[BlacklistRecord] = []

        if discord_id is not None:
            record = await self.get_active_by_discord_id(discord_id)
            if record:
                candidates.append(record)

        if roblox_id is not None:
            record = await self.get_active_by_roblox_id(roblox_id)
            if record:
                candidates.append(record)

        if roblox_username is not None:
            record = await self.get_active_by_roblox_username(roblox_username)
            if record:
                candidates.append(record)

        if not candidates:
            return None

        unique = {r.id for r in candidates}
        if len(unique) > 1:
            raise RuntimeError("Conflicting active blacklist records found.")

        return candidates[0]

    async def _find_matching_inactive_record(
        self,
        *,
        discord_id: int | None,
        roblox_id: int | None,
        roblox_username: str | None,
    ) -> BlacklistRecord | None:
        candidates: list[BlacklistRecord] = []

        if discord_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT * FROM {self.TABLE_NAME}
                WHERE discord_id = ? AND active = 0
                ORDER BY id DESC LIMIT 1
                """,
                (discord_id,),
            )
            if row:
                candidates.append(BlacklistRecord.from_row(row))

        if roblox_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT * FROM {self.TABLE_NAME}
                WHERE roblox_id = ? AND active = 0
                ORDER BY id DESC LIMIT 1
                """,
                (roblox_id,),
            )
            if row:
                candidates.append(BlacklistRecord.from_row(row))

        if roblox_username is not None:
            row = await self.database.fetchone(
                f"""
                SELECT * FROM {self.TABLE_NAME}
                WHERE roblox_username = ? AND active = 0
                ORDER BY id DESC LIMIT 1
                """,
                (roblox_username,),
            )
            if row:
                candidates.append(BlacklistRecord.from_row(row))

        if not candidates:
            return None

        unique = {r.id for r in candidates}
        if len(unique) > 1:
            raise RuntimeError("Conflicting inactive blacklist records found.")

        return candidates[0]

    async def _get_last_record(self) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"SELECT * FROM {self.TABLE_NAME} ORDER BY id DESC LIMIT 1",
            (),
        )
        return BlacklistRecord.from_row(row) if row else None

    async def upsert(
        self,
        *,
        added_by: int,
        reason: str,
        discord_id: int | None = None,
        roblox_id: int | None = None,
        roblox_username: str | None = None,
        announcement_channel_id: int | None = None,
        force_active: bool = True,
    ) -> BlacklistOperationResult:
        await self._initialize_database()

        clean_reason = self.normalize_reason(reason)
        if not clean_reason:
            raise ValueError("Reason cannot be empty.")

        if discord_id is None and roblox_id is None and not roblox_username:
            raise ValueError("At least one target must be provided.")

        normalized_username = roblox_username.strip() if roblox_username else None
        now = _now_iso()

        async with self._lock:
            active_record = await self._find_matching_active_record(
                discord_id=discord_id,
                roblox_id=roblox_id,
                roblox_username=normalized_username,
            )
            inactive_record = None
            if active_record is None:
                inactive_record = await self._find_matching_inactive_record(
                    discord_id=discord_id,
                    roblox_id=roblox_id,
                    roblox_username=normalized_username,
                )

            if active_record is not None:
                await self.database.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET discord_id = ?, roblox_id = ?, roblox_username = ?, reason = ?,
                        added_by = ?, created_at = ?, active = ?, announcement_channel_id = ?
                    WHERE id = ?
                    """,
                    (
                        discord_id,
                        roblox_id,
                        normalized_username,
                        clean_reason,
                        added_by,
                        now,
                        1 if force_active else 0,
                        announcement_channel_id,
                        active_record.id,
                    ),
                )
                updated = await self.get_by_id(active_record.id)
                assert updated is not None
                return BlacklistOperationResult(
                    success=True,
                    action="updated",
                    message="✅ Blacklist kaydı güncellendi.",
                    record=updated,
                    target=BlacklistTarget(
                        discord_id=discord_id,
                        roblox_id=roblox_id,
                        roblox_username=normalized_username,
                    ),
                    announcement_channel_id=announcement_channel_id,
                )

            if inactive_record is not None:
                await self.database.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET discord_id = ?, roblox_id = ?, roblox_username = ?, reason = ?,
                        added_by = ?, created_at = ?, active = ?, announcement_channel_id = ?
                    WHERE id = ?
                    """,
                    (
                        discord_id,
                        roblox_id,
                        normalized_username,
                        clean_reason,
                        added_by,
                        now,
                        1 if force_active else 0,
                        announcement_channel_id,
                        inactive_record.id,
                    ),
                )
                updated = await self.get_by_id(inactive_record.id)
                assert updated is not None
                return BlacklistOperationResult(
                    success=True,
                    action="reactivated" if force_active else "updated",
                    message="✅ Blacklist kaydı yeniden etkinleştirildi.",
                    record=updated,
                    target=BlacklistTarget(
                        discord_id=discord_id,
                        roblox_id=roblox_id,
                        roblox_username=normalized_username,
                    ),
                    announcement_channel_id=announcement_channel_id,
                )

            await self.database.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    discord_id, roblox_id, roblox_username, reason, added_by,
                    created_at, active, announcement_channel_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discord_id,
                    roblox_id,
                    normalized_username,
                    clean_reason,
                    added_by,
                    now,
                    1 if force_active else 0,
                    announcement_channel_id,
                ),
            )
            created = await self._get_last_record()
            assert created is not None
            return BlacklistOperationResult(
                success=True,
                action="inserted",
                message="✅ Blacklist kaydı oluşturuldu.",
                record=created,
                target=BlacklistTarget(
                    discord_id=discord_id,
                    roblox_id=roblox_id,
                    roblox_username=normalized_username,
                ),
                announcement_channel_id=announcement_channel_id,
            )

    async def remove_by_id(self, record_id: int) -> BlacklistOperationResult:
        await self._initialize_database()

        record = await self.get_by_id(record_id)
        if record is None:
            raise LookupError(f"Blacklist record not found: {record_id}")

        if not record.active:
            return BlacklistOperationResult(
                success=True,
                action="already_inactive",
                message="✅ Kayıt zaten pasif.",
                record=record,
            )

        await self.database.execute(
            f"UPDATE {self.TABLE_NAME} SET active = 0 WHERE id = ?",
            (record_id,),
        )

        updated = await self.get_by_id(record_id)
        assert updated is not None
        return BlacklistOperationResult(
            success=True,
            action="deactivated",
            message="✅ Blacklist kaydı kaldırıldı.",
            record=updated,
        )

    async def remove_by_text(self, target_text: str) -> BlacklistOperationResult:
        raw = target_text.strip()
        if not raw:
            raise ValueError("Target text cannot be empty.")

        discord_id = _parse_discord_id(raw)
        if discord_id is not None:
            record = await self.get_active_by_discord_id(discord_id)
            if record is None:
                raise LookupError(f"No active blacklist record found for Discord ID {discord_id}.")
            return await self.remove_by_id(record.id)

        roblox_username = _parse_roblox_username_hint(raw)
        if roblox_username:
            record = await self.get_active_by_roblox_username(roblox_username)
            if record is None:
                raise LookupError(f"No active blacklist record found for Roblox username {roblox_username}.")
            return await self.remove_by_id(record.id)

        raise ValueError("Target text could not be parsed.")

    async def deactivate_member_if_blacklisted(self, member: discord.Member) -> BlacklistOperationResult | None:
        record = await self.get_active_by_discord_id(member.id)
        if record is None:
            return None

        try:
            await member.kick(reason=f"Blacklist: {record.reason[:450]}")
        except discord.Forbidden as error:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Blacklist kaydı var ama kick yetkisi yok.",
                record=record,
                kick_error="Missing kick permissions.",
            )
        except discord.HTTPException:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Kick işlemi sırasında Discord API hatası oluştu.",
                record=record,
                kick_error="Discord API error.",
            )
        except Exception:
            self.cog_logger_warning(
                "Unexpected error while kicking blacklisted member %s",
                member.id,
            )
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Kick işlemi sırasında beklenmeyen bir hata oluştu.",
                record=record,
                kick_error="Unexpected error.",
            )

        return BlacklistOperationResult(
            success=True,
            action="kicked",
            message="✅ Blacklisted kullanıcı sunucudan çıkarıldı.",
            record=record,
            kicked=True,
        )

    def cog_logger_warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)

    def build_announcement_embed(
        self,
        record: BlacklistRecord,
        *,
        moderator_id: int,
        action: str,
        kicked: bool = False,
        kick_error: str | None = None,
    ) -> discord.Embed:
        title = {
            "inserted": "🚫 BLACKLIST UYGULANDI",
            "reactivated": "🚫 BLACKLIST YENİDEN ETKİN",
            "updated": "🚫 BLACKLIST GÜNCELLENDİ",
            "deactivated": "✅ BLACKLIST KALDIRILDI",
            "kicked": "🚫 BLACKLIST • OTO KICK",
        }.get(action, "🚫 BLACKLIST")

        embed = discord.Embed(
            title=title,
            description=(
                "Bu kullanıcı PAG blacklist sistemine işlendi."
                if record.active
                else "Bu kullanıcı blacklist sisteminden çıkarıldı."
            ),
            color=discord.Color.red() if record.active else discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

        if record.discord_id is not None:
            embed.add_field(name="Discord", value=f"<@{record.discord_id}>\n`{record.discord_id}`", inline=True)
        if record.roblox_username is not None:
            embed.add_field(
                name="Roblox",
                value=f"**{record.roblox_username}**" + (f"\n`{record.roblox_id}`" if record.roblox_id is not None else ""),
                inline=True,
            )

        embed.add_field(name="Sebep", value=self._trim_embed_text(record.reason), inline=False)
        embed.add_field(name="Admin", value=f"<@{moderator_id}>", inline=True)
        embed.add_field(name="Durum", value="Aktif" if record.active else "Pasif", inline=True)
        embed.add_field(name="Kayıt ID", value=f"`{record.id}`", inline=True)

        if kicked:
            embed.add_field(name="Kick", value="Başarılı", inline=True)
        if kick_error:
            embed.add_field(name="Kick Notu", value=self._trim_embed_text(kick_error), inline=False)
        if record.announcement_channel_id is not None:
            embed.set_footer(text=f"İşlem kanalı: #{record.announcement_channel_id}")
        return embed

    def build_join_notice_embed(self, record: BlacklistRecord, *, member_mention: str, guild_id: int) -> discord.Embed:
        embed = discord.Embed(
            title="🚫 BLACKLIST • OTO KICK",
            description=f"{member_mention} blacklist listesinde olduğu için sunucudan çıkarıldı.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Sebep", value=self._trim_embed_text(record.reason), inline=False)
        embed.add_field(name="Kayıt ID", value=f"`{record.id}`", inline=True)
        embed.add_field(name="Sunucu", value=f"`{guild_id}`", inline=True)
        if record.announcement_channel_id is not None:
            embed.set_footer(text=f"İşlem kanalı: #{record.announcement_channel_id}")
        return embed

    @staticmethod
    def _trim_embed_text(text: str, limit: int = 1024) -> str:
        value = text.strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    async def send_public_embed(self, channel_id: int | None, *, content: str | None = None, embed: discord.Embed | None = None) -> None:
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return
        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=True,
                    roles=False,
                    replied_user=False,
                ),
            )
        except Exception as error:
            self.logger.warning("Failed to send blacklist announcement to channel %s: %s", channel_id, error)

    async def send_notice_to_session_channel(self, author_id: int, content: str) -> None:
        session = self.get_session(author_id)
        if session is None:
            return
        if session.panel_channel_id is None:
            return
        await self.send_public_embed(session.panel_channel_id, content=content)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def build_panel_embed(self, draft: BlacklistDraft, *, panel_name: str) -> discord.Embed:
        active_count = await self.count_active()
        embed = discord.Embed(
            title="🚫 PAG BLACKLIST PANEL",
            description=(
                "Buradan blacklist ekleyebilir, düzenleyebilir, önizleyebilir ve kaldırabilirsin.\n\n"
                "İşlem yapılan kanal, duyuru kanalı olarak da kullanılır."
            ),
            color=discord.Color.dark_red() if draft.is_ready else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Panel", value=panel_name, inline=True)
        embed.add_field(name="Durum", value="Hazır" if draft.is_ready else "Eksik", inline=True)
        embed.add_field(name="Aktif Kayıt", value=f"`{active_count}`", inline=True)
        embed.add_field(name="Discord Hedef", value=f"<@{draft.discord_id}>" if draft.discord_id is not None else "—", inline=True)
        embed.add_field(name="Roblox Hedef", value=_truncate(draft.roblox_username, 128), inline=True)
        embed.add_field(name="Sebep", value=_truncate(draft.reason, 1024), inline=False)
        embed.add_field(name="Kick", value="Açık" if draft.kick_now else "Kapalı", inline=True)
        embed.add_field(
            name="Duyuru Kanalı",
            value=f"<#{draft.announcement_channel_id}>" if draft.announcement_channel_id is not None else "Bu kanal",
            inline=True,
        )
        embed.add_field(name="Hızlı Format", value="`discord:@user | roblox:Username | reason:sebep`", inline=False)
        if draft.avatar_url:
            embed.set_thumbnail(url=draft.avatar_url)
        embed.set_footer(text="Panel • Butonlar ile hedef ekle, önizle ve gönder.")
        return embed

    async def build_preview_embed(self, draft: BlacklistDraft) -> discord.Embed:
        embed = discord.Embed(
            title="🚫 BLACKLIST ÖNİZLEME",
            description="Blacklist işlemi gönderilmeden önce son kontrol.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        if draft.discord_id is not None:
            embed.add_field(name="Discord", value=f"<@{draft.discord_id}>\n`{draft.discord_id}`", inline=True)
        if draft.roblox_username:
            embed.add_field(
                name="Roblox",
                value=f"**{_truncate(draft.roblox_username, 64)}**" + (f"\n`{draft.roblox_id}`" if draft.roblox_id else ""),
                inline=True,
            )
        embed.add_field(name="Sebep", value=_truncate(draft.reason, 1024), inline=False)
        embed.add_field(name="Kick", value="Açık" if draft.kick_now else "Kapalı", inline=True)
        embed.add_field(
            name="Duyuru Kanalı",
            value=f"<#{draft.announcement_channel_id}>" if draft.announcement_channel_id is not None else "Bu kanal",
            inline=True,
        )
        if draft.avatar_url:
            embed.set_thumbnail(url=draft.avatar_url)
        embed.set_footer(text="Göndermeden önce doğrula.")
        return embed

    async def build_manage_embed(self, draft: BlacklistDraft) -> discord.Embed:
        latest = await self._get_last_record()
        active_count = await self.count_active()

        embed = discord.Embed(
            title="📊 BLACKLIST DURUM",
            description="Aktif kayıt ve son işlem bilgileri.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Aktif Kayıt", value=f"`{active_count}`", inline=True)
        embed.add_field(name="Son İşlem", value=f"`#{latest.id}`" if latest is not None else "—", inline=True)
        embed.add_field(
            name="Duyuru Kanalı",
            value=f"<#{draft.announcement_channel_id}>" if draft.announcement_channel_id is not None else "Bu kanal",
            inline=True,
        )
        embed.add_field(name="Discord Hedef", value=f"<@{draft.discord_id}>" if draft.discord_id is not None else "—", inline=True)
        embed.add_field(name="Roblox Hedef", value=_truncate(draft.roblox_username, 128), inline=True)
        embed.add_field(name="Sebep", value=_truncate(draft.reason, 1024), inline=False)
        embed.set_footer(text="Yönetim • Kaldır, geçmiş, duyuru kanalını seç, geri dön.")
        return embed

    async def build_history_embed(self) -> discord.Embed:
        rows = await self.list_recent(limit=10)
        embed = discord.Embed(
            title="📜 BLACKLIST GEÇMİŞİ",
            description="Son işlemler.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if not rows:
            embed.description = "Henüz geçmiş yok."
            return embed
        embed.description = "\n\n".join(
            f"#{row.id} • {'Aktif' if row.active else 'Pasif'} • {_truncate(row.reason, 90)}"
            for row in rows
        )
        return embed

    def build_view(self, kind: str, author_id: int) -> BlacklistBaseView:
        if kind == "preview":
            return BlacklistPreviewView(self, author_id)
        if kind == "manage":
            return BlacklistManageView(self, author_id)
        return BlacklistMainView(self, author_id)

    async def refresh_panel_message(self, *, author_id: int, notice: str | None = None) -> None:
        session = self.get_session(author_id)
        if session is None or session.panel_channel_id is None or session.panel_message_id is None:
            return

        channel = self.bot.get_channel(session.panel_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(session.panel_channel_id)
            except Exception:
                return

        if not hasattr(channel, "fetch_message"):
            return

        try:
            message = await channel.fetch_message(session.panel_message_id)
        except Exception:
            return

        try:
            embed = await self.build_panel_embed(
                session.draft,
                panel_name={"main": "Ana Panel", "preview": "Önizleme", "manage": "Yönetim Paneli"}.get(session.current_view, "Ana Panel"),
            )
            view = self.build_view(session.current_view, author_id)
            await message.edit(embed=embed, view=view)
        except Exception:
            pass

        if notice:
            try:
                await channel.send(notice, delete_after=6)
            except Exception:
                pass

    async def execute_blacklist(
        self,
        *,
        moderator: discord.Member | discord.User,
        kick_now: bool = True,
        announce_channel_id: int | None = None,
    ) -> BlacklistOperationResult:
        session = self.get_session(moderator.id)
        if session is None:
            raise RuntimeError("Blacklist session not found.")

        draft = session.draft
        error = self.validate_draft(draft)
        if error:
            raise ValueError(error)

        if announce_channel_id is None:
            announce_channel_id = session.panel_channel_id

        target = BlacklistTarget(
            discord_id=draft.discord_id,
            roblox_id=draft.roblox_id,
            roblox_username=draft.roblox_username,
            roblox_display_name=draft.roblox_display_name,
            avatar_url=draft.avatar_url,
        )

        if target.roblox_username and target.roblox_id is None:
            resolved = await self.resolve_roblox_target(target.roblox_username)
            target = replace(
                target,
                roblox_id=resolved.roblox_id,
                roblox_username=resolved.roblox_username,
                roblox_display_name=resolved.roblox_display_name,
                avatar_url=resolved.avatar_url,
            )

        if target.discord_id is not None and isinstance(moderator, discord.Member) and moderator.guild is not None:
            member = moderator.guild.get_member(target.discord_id)
            if member is None:
                try:
                    member = await moderator.guild.fetch_member(target.discord_id)
                except Exception:
                    member = None
            if member is not None:
                target = replace(target, discord_id=member.id)

        record_result = await self.upsert(
            added_by=moderator.id,
            reason=draft.reason,
            discord_id=target.discord_id,
            roblox_id=target.roblox_id,
            roblox_username=target.roblox_username,
            announcement_channel_id=announce_channel_id,
            force_active=True,
        )

        record = record_result.record
        assert record is not None

        kicked = False
        kick_error = None

        if kick_now and isinstance(moderator, discord.Member) and moderator.guild is not None and target.discord_id is not None:
            member = moderator.guild.get_member(target.discord_id)
            if member is None:
                try:
                    member = await moderator.guild.fetch_member(target.discord_id)
                except Exception:
                    member = None

            if member is not None:
                try:
                    await member.kick(reason=f"Blacklist: {draft.reason[:450]}")
                    kicked = True
                except discord.Forbidden:
                    kick_error = "Kick yetkisi yok."
                except discord.HTTPException:
                    kick_error = "Discord API hatası."
                except Exception:
                    kick_error = "Beklenmeyen kick hatası."

        self._push_history(
            f"{'GÜNCELLENDİ' if record_result.action != 'inserted' else 'EKLENDİ'} • Discord={target.discord_id or '—'} • Roblox={target.roblox_username or '—'} • Moderator={moderator.id}"
        )

        public_embed = self.build_announcement_embed(
            record,
            moderator_id=moderator.id,
            action=record_result.action,
            kicked=kicked,
            kick_error=kick_error,
        )

        return BlacklistOperationResult(
            success=True,
            action=record_result.action,
            message="✅ Blacklist tamamlandı." + (" Hedef sunucudan atıldı." if kicked else "") + (f" ({kick_error})" if kick_error else ""),
            record=record,
            target=target,
            kicked=kicked,
            kick_error=kick_error,
            announcement_channel_id=announce_channel_id,
            public_embed=public_embed,
        )

    async def remove_by_text(
        self,
        *,
        moderator: discord.Member | discord.User,
        target_text: str,
        announce_channel_id: int | None = None,
    ) -> BlacklistOperationResult:
        raw = target_text.strip()
        if not raw:
            return BlacklistOperationResult(success=False, action="invalid", message="❌ Hedef boş olamaz.")

        discord_id = _parse_discord_id(raw)
        if discord_id is not None:
            record = await self.get_active_by_discord_id(discord_id)
            if record is None:
                return BlacklistOperationResult(success=False, action="not_found", message="❌ Kaldırılacak aktif blacklist kaydı bulunamadı.")
            result = await self.remove_by_id(record.id)
            if announce_channel_id is not None and result.record is not None:
                result.record = replace(result.record, announcement_channel_id=announce_channel_id)
            return result

        roblox_username = _parse_roblox_username_hint(raw)
        if roblox_username:
            record = await self.get_active_by_roblox_username(roblox_username)
            if record is None:
                return BlacklistOperationResult(success=False, action="not_found", message="❌ Kaldırılacak aktif blacklist kaydı bulunamadı.")
            result = await self.remove_by_id(record.id)
            if announce_channel_id is not None and result.record is not None:
                result.record = replace(result.record, announcement_channel_id=announce_channel_id)
            return result

        return BlacklistOperationResult(success=False, action="invalid", message="❌ Hedef çözümlenemedi.")

    async def deactivate_member_if_blacklisted(self, member: discord.Member) -> BlacklistOperationResult | None:
        record = await self.get_active_by_discord_id(member.id)
        if record is None:
            return None

        try:
            await member.kick(reason=f"Blacklist: {record.reason[:450]}")
        except discord.Forbidden:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Blacklist kaydı var ama kick yetkisi yok.",
                record=record,
                kick_error="Missing kick permissions.",
            )
        except discord.HTTPException:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Kick işlemi sırasında Discord API hatası oluştu.",
                record=record,
                kick_error="Discord API error.",
            )
        except Exception:
            self.logger.warning("Unexpected error while kicking blacklisted member %s", member.id)
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Kick işlemi sırasında beklenmeyen bir hata oluştu.",
                record=record,
                kick_error="Unexpected error.",
            )

        return BlacklistOperationResult(
            success=True,
            action="kicked",
            message="✅ Blacklisted kullanıcı sunucudan çıkarıldı.",
            record=record,
            kicked=True,
        )

    async def should_kick_member(self, member: discord.Member) -> bool:
        record = await self.get_active_by_discord_id(member.id)
        return record is not None

    async def enforce_member_join(self, member: discord.Member) -> BlacklistOperationResult | None:
        return await self.deactivate_member_if_blacklisted(member)

    async def on_member_join_announce(self, member: discord.Member, record: BlacklistRecord) -> None:
        notice_embed = self.build_join_notice_embed(
            record,
            member_mention=member.mention,
            guild_id=member.guild.id,
        )
        await self.send_public_embed(record.announcement_channel_id, embed=notice_embed)

    async def on_member_join(self, member: discord.Member) -> None:
        try:
            result = await self.enforce_member_join(member)
            if result is None or result.record is None or not result.kicked:
                return
            await self.on_member_join_announce(member, result.record)
            self._push_history(f"JOIN KICK • Discord={member.id} • Reason={result.record.reason[:80]}")
        except Exception:
            self.logger.exception("Unexpected error in on_member_join for blacklisted member: %s", member.id)

    async def blacklistpanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await self.safe_initial_response(interaction, "❌ Bu komut yalnızca sunucularda kullanılabilir.")
            return

        if not isinstance(interaction.user, discord.Member):
            await self.safe_initial_response(interaction, "❌ Sunucu üye bilgisi alınamadı.")
            return

        if not interaction.user.guild_permissions.administrator:
            await self.safe_initial_response(interaction, "❌ Bu komutu yalnızca Administrator kullanabilir.")
            return

        draft = BlacklistDraft(announcement_channel_id=interaction.channel_id)
        self.set_session(interaction.user.id, draft=draft, channel_id=interaction.channel_id, current_view="main")
        embed = await self.build_panel_embed(draft, panel_name="Ana Panel")
        view = self.build_view("main", interaction.user.id)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

        try:
            message = await interaction.original_response()
            session = self.get_session(interaction.user.id)
            if session is not None:
                session.panel_message_id = message.id
        except Exception:
            pass

    @app_commands.command(name="blacklistpanel", description="Blacklist yönetim panelini açar.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def blacklistpanel_slash(self, interaction: discord.Interaction) -> None:
        await self.blacklistpanel(interaction)

    @commands.command(name="blacklistpanel")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def blacklistpanel_prefix(self, ctx: commands.Context, *, raw: str | None = None) -> None:
        draft = BlacklistDraft(announcement_channel_id=ctx.channel.id)
        if raw and raw.strip():
            parsed = self.parse_quick_input(raw)
            if parsed is not None:
                draft = replace(parsed, announcement_channel_id=ctx.channel.id)

        self.set_session(ctx.author.id, draft=draft, channel_id=ctx.channel.id, current_view="main")
        embed = await self.build_panel_embed(draft, panel_name="Ana Panel")
        view = self.build_view("main", ctx.author.id)
        sent = await ctx.send(embed=embed, view=view)

        session = self.get_session(ctx.author.id)
        if session is not None:
            session.panel_message_id = sent.id

    @app_commands.command(name="blacklist", description="Bir kullanıcıyı blacklist'e ekler.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Discord üyesi.", roblox_username="Roblox kullanıcı adı.", reason="Blacklist sebebi.")
    async def blacklist_slash(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        roblox_username: str | None = None,
        reason: str = "Sebep belirtilmedi.",
    ) -> None:
        if interaction.guild is None:
            await self.safe_initial_response(interaction, "❌ Bu komut yalnızca sunucularda kullanılabilir.")
            return

        if not isinstance(interaction.user, discord.Member):
            await self.safe_initial_response(interaction, "❌ Sunucu üye bilgisi alınamadı.")
            return

        if not interaction.user.guild_permissions.administrator:
            await self.safe_initial_response(interaction, "❌ Bu komutu yalnızca Administrator kullanabilir.")
            return

        if member is None and not roblox_username:
            await self.blacklistpanel(interaction)
            return

        draft = BlacklistDraft(
            discord_id=member.id if member else None,
            discord_label=member.display_name if member else None,
            roblox_username=_parse_roblox_username_hint(roblox_username or "") if roblox_username else None,
            reason=self.normalize_reason(reason),
            kick_now=True,
            announcement_channel_id=interaction.channel_id,
        )

        if draft.roblox_username:
            try:
                resolved = await self.resolve_roblox_target(draft.roblox_username)
                draft = replace(
                    draft,
                    roblox_id=resolved.roblox_id,
                    roblox_username=resolved.roblox_username,
                    roblox_display_name=resolved.roblox_display_name,
                    avatar_url=resolved.avatar_url,
                )
            except RobloxNotFoundError:
                await self.safe_initial_response(interaction, "❌ Roblox kullanıcısı bulunamadı.")
                return
            except RobloxAPIError:
                await self.safe_initial_response(interaction, "❌ Roblox API hatası oluştu.")
                return
            except Exception:
                self.logger.exception("Unexpected Roblox resolution error.")
                await self.safe_initial_response(interaction, "❌ Roblox hedefi çözümlenirken beklenmeyen bir hata oluştu.")
                return

        self.set_session(interaction.user.id, draft=draft, channel_id=interaction.channel_id, current_view="main")
        result = await self.execute_blacklist(
            moderator=interaction.user,
            kick_now=True,
            announce_channel_id=interaction.channel_id,
        )
        if result.public_embed is not None:
            await self.send_public_embed(interaction.channel_id, embed=result.public_embed)
        self.clear_session(interaction.user.id)
        await self.safe_initial_response(interaction, result.message)

    @commands.command(name="blacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def blacklist_prefix(self, ctx: commands.Context, target: str | None = None, *, reason: str = "Sebep belirtilmedi.") -> None:
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
            announcement_channel_id=ctx.channel.id,
        )

        if draft.roblox_username:
            try:
                resolved = await self.resolve_roblox_target(draft.roblox_username)
                draft = replace(
                    draft,
                    roblox_id=resolved.roblox_id,
                    roblox_username=resolved.roblox_username,
                    roblox_display_name=resolved.roblox_display_name,
                    avatar_url=resolved.avatar_url,
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

        self.set_session(ctx.author.id, draft=draft, channel_id=ctx.channel.id, current_view="main")
        result = await self.execute_blacklist(
            moderator=ctx.author,
            kick_now=True,
            announce_channel_id=ctx.channel.id,
        )
        if result.public_embed is not None:
            await self.send_public_embed(ctx.channel.id, embed=result.public_embed)
        self.clear_session(ctx.author.id)
        await ctx.send(result.message)

    @app_commands.command(name="unblacklist", description="Aktif blacklist kaydını kaldırır.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def unblacklist_slash(self, interaction: discord.Interaction, target: str | None = None) -> None:
        if target is None:
            await self.safe_initial_response(interaction, "❌ Hedef belirtmelisin.")
            return
        result = await self.remove_by_text(moderator=interaction.user, target_text=target, announce_channel_id=interaction.channel_id)
        if result.record is not None:
            notice = result.public_embed or discord.Embed(
                title="✅ UNBLACKLIST",
                description="Aktif blacklist kaydı kaldırıldı.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            await self.send_public_embed(interaction.channel_id, embed=notice)
        await self.safe_initial_response(interaction, result.message)

    @commands.command(name="unblacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def unblacklist_prefix(self, ctx: commands.Context, target: str | None = None) -> None:
        if target is None:
            await ctx.send("❌ Hedef belirtmelisin.")
            return
        result = await self.remove_by_text(moderator=ctx.author, target_text=target, announce_channel_id=ctx.channel.id)
        if result.record is not None:
            notice = result.public_embed or discord.Embed(
                title="✅ UNBLACKLIST",
                description="Aktif blacklist kaydı kaldırıldı.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            await self.send_public_embed(ctx.channel.id, embed=notice)
        await ctx.send(result.message)

    async def build_blacklist_listing_embed(self, records: list[BlacklistRecord], title: str = "📋 BLACKLIST LISTESI") -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description="Aktif blacklist kayıtları.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if not records:
            embed.description = "Kayıt bulunamadı."
            return embed
        for record in records[:10]:
            value = []
            if record.discord_id is not None:
                value.append(f"Discord: <@{record.discord_id}> (`{record.discord_id}`)")
            if record.roblox_username is not None:
                value.append(f"Roblox: **{record.roblox_username}**")
            value.append(f"Sebep: {_truncate(record.reason, 200)}")
            value.append(f"Durum: {'Aktif' if record.active else 'Pasif'}")
            embed.add_field(name=f"#{record.id}", value="\n".join(value), inline=False)
        return embed

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ Bu komut için Administrator yetkisi gerekir."
        else:
            self.logger.exception("Blacklist slash command error.")
            message = "❌ Beklenmeyen bir hata oluştu."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Bu komut için Administrator yetkisi gerekir.", delete_after=8)
            return
        if isinstance(error, commands.CommandNotFound):
            return
        self.logger.exception("Blacklist prefix command error.")
        await ctx.send("❌ Beklenmeyen bir hata oluştu.", delete_after=8)

    async def safe_initial_response(self, interaction: discord.Interaction, content: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except discord.NotFound:
            self.logger.warning("Interaction expired before response.")
        except discord.HTTPException:
            self.logger.exception("Failed to send interaction response.")

    async def safe_followup(self, interaction: discord.Interaction, content: str) -> None:
        try:
            await interaction.followup.send(content, ephemeral=True)
        except discord.NotFound:
            self.logger.warning("Interaction expired before followup.")
        except discord.HTTPException:
            self.logger.exception("Failed to send followup response.")

    async def list_active(self, *, limit: int = 100, offset: int = 0) -> list[BlacklistRecord]:
        rows = await self.database.fetchall(
            f"SELECT * FROM {self.TABLE_NAME} WHERE active = 1 ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [BlacklistRecord.from_row(row) for row in rows]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Blacklist(bot),
    )
