from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from services.top10_service import (
    InvalidPositionError,
    PlayerAlreadyExistsError,
    PlayerNotFoundError,
    PositionOccupiedError,
    Top10Entry,
    Top10Error,
    Top10Service,
)


# ============================================================
# SMALL HELPERS
# ============================================================


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None

    value = text.strip()
    if len(value) <= limit:
        return value

    return value[: limit - 3] + "..."


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_true_like(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "evet",
        "on",
        "ok",
        "confirm",
    }


# ============================================================
# EMBEDS
# ============================================================


class Top10Embeds:
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def empty() -> discord.Embed:
        return discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "PAG Top 10 şu anda boş.\n\n"
                "Henüz listede kayıtlı oyuncu yok."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def overview(entries: list[Top10Entry]) -> discord.Embed:
        if not entries:
            return Top10Embeds.empty()

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        lines: list[str] = []

        for entry in entries:
            prefix = medals.get(entry.position, f"`#{entry.position}`")
            rank_text = f"`{entry.rank}`" if entry.rank else "`Bilinmiyor`"
            username_text = (
                f"`{entry.roblox_username}`"
                if entry.roblox_username
                else "`Bilinmiyor`"
            )

            lines.append(
                (
                    f"{prefix} **{entry.roblox_display_name}**\n"
                    f"└ {username_text} • {rank_text}"
                )
            )

        embed = discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "Resmî sıralama görünümü.\n\n"
                + "\n\n".join(lines)
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(
            text=f"PAG • {len(entries)}/{Top10Service.MAX_ENTRIES} dolu",
        )
        return embed

    @staticmethod
    def player(
        entry: Top10Entry,
        *,
        page_index: int,
        total_pages: int,
    ) -> discord.Embed:
        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        icon = medals.get(entry.position, "🏆")
        profile_url = entry.profile_url or None

        embed = discord.Embed(
            title=f"{icon} #{entry.position} {entry.roblox_display_name}",
            url=profile_url,
            description=(
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"**Roblox Username**\n"
                f"`{entry.roblox_username}`\n\n"
                f"**PAG Rank**\n"
                f"`{entry.rank}`"
            ),
            color=discord.Color.gold() if entry.is_first_place else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🏆 Position",
            value=f"**#{entry.position}**",
            inline=True,
        )
        embed.add_field(
            name="👤 Roblox ID",
            value=f"`{entry.roblox_user_id}`",
            inline=True,
        )
        embed.add_field(
            name="🎖️ Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        if entry.notes:
            embed.add_field(
                name="📝 Notes",
                value=_truncate(entry.notes, 1024) or "Bilinmiyor",
                inline=False,
            )

        embed.add_field(
            name="➕ Added By",
            value=f"<@{entry.added_by}>",
            inline=True,
        )
        embed.add_field(
            name="✏️ Updated By",
            value=f"<@{entry.updated_by}>",
            inline=True,
        )

        created_dt = _parse_iso_dt(entry.created_at)
        updated_dt = _parse_iso_dt(entry.updated_at)

        if created_dt is not None:
            embed.add_field(
                name="📅 Created",
                value=discord.utils.format_dt(created_dt, style="R"),
                inline=True,
            )

        if updated_dt is not None:
            embed.add_field(
                name="🕒 Updated",
                value=discord.utils.format_dt(updated_dt, style="R"),
                inline=True,
            )

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        embed.set_footer(
            text=f"PAG Top 10 • Sayfa {page_index + 1}/{total_pages}",
        )
        return embed

    @staticmethod
    def management(count: int) -> discord.Embed:
        status_text = "Dolu" if count >= Top10Service.MAX_ENTRIES else "Açık"

        embed = discord.Embed(
            title="🏆 PAG TOP 10 MANAGEMENT",
            description=(
                "Top 10 sistemini aşağıdaki kontrollerle yönet.\n\n"
                "➕ **Add Player**\n"
                "Boş pozisyona oyuncu ekler.\n\n"
                "♻️ **Replace Player**\n"
                "Dolu pozisyondaki oyuncuyu değiştirir.\n\n"
                "✏️ **Edit Player**\n"
                "Var olan kaydı günceller.\n\n"
                "🗑️ **Remove Player**\n"
                "Bir oyuncuyu kaldırır.\n\n"
                "📊 **View Rankings**\n"
                "Güncel sıralamayı gösterir.\n\n"
                "⚠️ **Reset**\n"
                "Tüm listeyi sıfırlar."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📈 Current Entries",
            value=f"`{count}/{Top10Service.MAX_ENTRIES}`",
            inline=True,
        )
        embed.add_field(
            name="📌 Status",
            value=f"`{status_text}`",
            inline=True,
        )
        embed.set_footer(
            text="PAG • Admin tools",
        )
        return embed


# ============================================================
# ERROR MAPPER
# ============================================================


class Top10ErrorMapper:
    @staticmethod
    def map(
        error: Exception,
        *,
        position: int | None = None,
        username: str | None = None,
    ) -> tuple[str, str]:
        if isinstance(error, InvalidPositionError):
            return (
                "❌ Geçersiz Pozisyon",
                "Pozisyon **1** ile **10** arasında olmalı.",
            )

        if isinstance(error, PlayerAlreadyExistsError):
            return (
                "❌ Oyuncu Zaten Var",
                f"**{username or 'Bu oyuncu'}** zaten Top 10 içinde.",
            )

        if isinstance(error, PositionOccupiedError):
            if position is None:
                return (
                    "❌ Pozisyon Dolu",
                    "Bu pozisyon zaten dolu.",
                )
            return (
                "❌ Pozisyon Dolu",
                f"**#{position}** pozisyonu zaten dolu.",
            )

        if isinstance(error, PlayerNotFoundError):
            if position is None:
                return (
                    "❌ Oyuncu Bulunamadı",
                    f"**{username or 'İstenen oyuncu'}** bulunamadı.",
                )
            return (
                "❌ Oyuncu Bulunamadı",
                f"**#{position}** pozisyonunda oyuncu yok.",
            )

        if isinstance(error, Top10Error):
            return (
                "❌ Top 10 Hatası",
                "Top 10 servisi işlemi tamamlayamadı.",
            )

        return (
            "❌ Beklenmeyen Hata",
            "İşlem sırasında beklenmeyen bir hata oluştu.",
        )


# ============================================================
# RANKING VIEW
# ============================================================


class Top10RankingView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        entries: list[Top10Entry],
        author_id: int | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.service = service
        self.entries = entries
        self.author_id = author_id
        self.current_index = 0
        self.show_overview = False
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_entries = bool(self.entries)

        self.previous_button.disabled = (
            not has_entries
            or self.show_overview
            or self.current_index <= 0
        )
        self.next_button.disabled = (
            not has_entries
            or self.show_overview
            or self.current_index >= len(self.entries) - 1
        )
        self.overview_button.disabled = not has_entries
        self.refresh_button.disabled = not has_entries

    def _current_embed(self) -> discord.Embed:
        if not self.entries:
            return Top10Embeds.empty()

        if self.show_overview:
            return Top10Embeds.overview(self.entries)

        return Top10Embeds.player(
            self.entries[self.current_index],
            page_index=self.current_index,
            total_pages=len(self.entries),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu paneli kullanamazsın.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = False
        if self.current_index > 0:
            self.current_index -= 1

        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self._current_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Overview",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def overview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = not self.show_overview
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self._current_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = False
        if self.current_index < len(self.entries) - 1:
            self.current_index += 1

        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self._current_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer()

        try:
            self.entries = await self.service.get_all()
        except Exception:
            self._sync_buttons()
            self.logger = logging.getLogger("Top10RankingView")
            self.logger.exception("Top 10 yenilenemedi.")

            await interaction.edit_original_response(
                embed=Top10Embeds.error(
                    "❌ Yenileme Başarısız",
                    "Güncel sıralama alınamadı.",
                ),
                view=None,
            )
            return

        if not self.entries:
            await interaction.edit_original_response(
                embed=Top10Embeds.empty(),
                view=None,
            )
            self.stop()
            return

        if self.current_index >= len(self.entries):
            self.current_index = len(self.entries) - 1

        self.show_overview = False
        self._sync_buttons()

        await interaction.edit_original_response(
            embed=self._current_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            view=None,
        )
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# ADD MODAL
# ============================================================


class Top10AddModal(discord.ui.Modal, title="PAG Top 10 Oyuncu Ekle"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Roblox kullanıcı adı",
        min_length=1,
        max_length=20,
        required=True,
    )

    rank = discord.ui.TextInput(
        label="PAG Rank",
        placeholder="PT1, ET3, LT vb.",
        min_length=1,
        max_length=50,
        required=True,
    )

    notes = discord.ui.TextInput(
        label="Notes",
        placeholder="İsteğe bağlı not",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        added_by: int,
        replace_existing: bool,
    ) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self.added_by = added_by
        self.replace_existing = replace_existing

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Geçersiz Pozisyon",
                    "Pozisyon sayısal olmalı.",
                ),
                ephemeral=True,
            )
            return

        username = self.username.value.strip()
        rank = self.rank.value.strip()
        notes = self.notes.value.strip() or None

        if not username:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Geçersiz Kullanıcı Adı",
                    "Roblox kullanıcı adı boş olamaz.",
                ),
                ephemeral=True,
            )
            return

        if not rank:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Geçersiz Rank",
                    "PAG rank boş olamaz.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.add(
                position=position,
                username=username,
                rank=rank,
                added_by=self.added_by,
                notes=notes,
                replace_existing=self.replace_existing,
            )
        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=position,
                username=username,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except sqlite3.IntegrityError:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Veritabanı Çakışması",
                    "Kayıt veritabanına yazılamadı.",
                ),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Top 10 ekleme sırasında beklenmeyen hata.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Beklenmeyen Hata",
                    "Oyuncu eklenemedi.",
                ),
                ephemeral=True,
            )
            return

        embed = Top10Embeds.success(
            "✅ Oyuncu Eklendi",
            f"**{entry.roblox_display_name}** başarıyla **#{entry.position}** konumuna yazıldı.",
        )
        embed.add_field(
            name="Roblox",
            value=f"`{entry.roblox_username}`",
            inline=True,
        )
        embed.add_field(
            name="Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )
        embed.add_field(
            name="User ID",
            value=f"`{entry.roblox_user_id}`",
            inline=True,
        )

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# EDIT MODAL
# ============================================================


class Top10EditModal(discord.ui.Modal, title="PAG Top 10 Oyuncu Düzenle"):
    position = discord.ui.TextInput(
        label="Current Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    username = discord.ui.TextInput(
        label="New Roblox Username",
        placeholder="Boş bırakırsan aynı kalır",
        required=False,
        max_length=20,
    )

    rank = discord.ui.TextInput(
        label="New PAG Rank",
        placeholder="Boş bırakırsan aynı kalır",
        required=False,
        max_length=50,
    )

    new_position = discord.ui.TextInput(
        label="New Position",
        placeholder="Boş bırakırsan aynı kalır",
        required=False,
        max_length=2,
    )

    notes = discord.ui.TextInput(
        label="New Notes",
        placeholder="Boş bırakırsan aynı kalır",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        updated_by: int,
    ) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self.updated_by = updated_by

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Geçersiz Pozisyon",
                    "Mevcut pozisyon sayısal olmalı.",
                ),
                ephemeral=True,
            )
            return

        username = self.username.value.strip() or None
        rank = self.rank.value.strip() or None
        notes = self.notes.value.strip() or None

        new_position: int | None = None
        if self.new_position.value.strip():
            try:
                new_position = int(self.new_position.value.strip())
            except ValueError:
                await interaction.response.send_message(
                    embed=Top10Embeds.error(
                        "❌ Geçersiz Yeni Pozisyon",
                        "Yeni pozisyon sayısal olmalı.",
                    ),
                    ephemeral=True,
                )
                return

        if username is None and rank is None and notes is None and new_position is None:
            await interaction.response.send_message(
                embed=Top10Embeds.warning(
                    "⚠️ Değiştirilecek Alan Yok",
                    "Kaydetmeden önce en az bir alan değişmeli.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.update(
                position=position,
                updated_by=self.updated_by,
                username=username,
                rank=rank,
                notes=notes,
                new_position=new_position,
            )
        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=new_position or position,
                username=username,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except sqlite3.IntegrityError:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Veritabanı Çakışması",
                    "Güncelleme veritabanına yazılamadı.",
                ),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Top 10 düzenleme sırasında beklenmeyen hata.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Beklenmeyen Hata",
                    "Oyuncu güncellenemedi.",
                ),
                ephemeral=True,
            )
            return

        embed = Top10Embeds.success(
            "✅ Oyuncu Güncellendi",
            f"**{entry.roblox_display_name}** başarıyla güncellendi.",
        )
        embed.add_field(
            name="Position",
            value=f"**#{entry.position}**",
            inline=True,
        )
        embed.add_field(
            name="Roblox",
            value=f"`{entry.roblox_username}`",
            inline=True,
        )
        embed.add_field(
            name="Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# REMOVE CONFIRM VIEW
# ============================================================


class Top10RemoveConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        entry: Top10Entry,
        author_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.logger = logger
        self.entry = entry
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu onay paneli sana ait değil.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Remove",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_remove(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.defer(ephemeral=True)

        try:
            removed = await self.service.remove(self.entry.position)
        except (
            InvalidPositionError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=self.entry.position,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            self.stop()
            return
        except Exception:
            self.logger.exception("Top 10 silme sırasında beklenmeyen hata.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Silme Başarısız",
                    "Oyuncu kaldırılamadı.",
                ),
                ephemeral=True,
            )
            self.stop()
            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Oyuncu Kaldırıldı",
                f"**{removed.roblox_display_name}** başarıyla **#{removed.position}** konumundan kaldırıldı.",
            ),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_remove(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❎ Kaldırma iptal edildi.",
            embed=None,
            view=None,
        )
        self.stop()


class Top10RemoveModal(discord.ui.Modal, title="PAG Top 10 Oyuncu Kaldır"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Geçersiz Pozisyon",
                    "Pozisyon sayısal olmalı.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.get_by_position(position)
        except (
            InvalidPositionError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=position,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Silmeden önce oyuncu yüklenemedi.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Yükleme Başarısız",
                    "Oyuncu kontrol edilemedi.",
                ),
                ephemeral=True,
            )
            return

        if entry is None:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Pozisyon Boş",
                    f"**#{position}** pozisyonunda oyuncu yok.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=Top10Embeds.warning(
                "⚠️ Silmeyi Onayla",
                f"**{entry.roblox_display_name}** oyuncusu **#{entry.position}** konumundan kaldırılsın mı?",
            ),
            view=Top10RemoveConfirmView(
                service=self.service,
                logger=self.logger,
                entry=entry,
                author_id=self.author_id,
            ),
            ephemeral=True,
        )


# ============================================================
# RESET CONFIRM VIEW
# ============================================================


class Top10ResetConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu onay paneli sana ait değil.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm Reset",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.defer(ephemeral=True)

        try:
            deleted_count = await self.service.clear()
        except Exception:
            self.logger.exception("Top 10 sıfırlanamadı.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Reset Başarısız",
                    "Top 10 listesi sıfırlanamadı.",
                ),
                ephemeral=True,
            )
            self.stop()
            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Top 10 Sıfırlandı",
                f"Listeden **{deleted_count}** kayıt silindi.",
            ),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❎ Reset iptal edildi.",
            embed=None,
            view=None,
        )
        self.stop()


# ============================================================
# MANAGEMENT VIEW
# ============================================================


class Top10ManagementView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu panel başka bir yöneticiye ait.",
                ephemeral=True,
            )
            return False

        if not (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "❌ Bu panel için Administrator yetkisi gerekir.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Add Player",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def add_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10AddModal(
                service=self.service,
                logger=self.logger,
                added_by=interaction.user.id,
                replace_existing=False,
            )
        )

    @discord.ui.button(
        label="Replace Player",
        emoji="♻️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def replace_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10AddModal(
                service=self.service,
                logger=self.logger,
                added_by=interaction.user.id,
                replace_existing=True,
            )
        )

    @discord.ui.button(
        label="Edit Player",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def edit_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10EditModal(
                service=self.service,
                logger=self.logger,
                updated_by=interaction.user.id,
            )
        )

    @discord.ui.button(
        label="Remove Player",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def remove_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10RemoveModal(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            )
        )

    @discord.ui.button(
        label="View Rankings",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def view_rankings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            entries = await self.service.get_all()
        except Exception:
            self.logger.exception("Top 10 listesi yüklenemedi.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Yükleme Başarısız",
                    "Top 10 listesi alınamadı.",
                ),
                ephemeral=True,
            )
            return

        if not entries:
            await interaction.followup.send(
                embed=Top10Embeds.empty(),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=Top10Embeds.player(
                entries[0],
                page_index=0,
                total_pages=len(entries),
            ),
            view=Top10RankingView(
                service=self.service,
                entries=entries,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Reset",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def reset_top10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_message(
            embed=Top10Embeds.warning(
                "⚠️ Top 10 Sıfırlansın mı?",
                (
                    "Bu işlem listedeki tüm oyuncuları siler.\n\n"
                    "Devam etmek için onay vermelisin."
                ),
            ),
            view=Top10ResetConfirmView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def close_panel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            view=None,
        )
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# MAIN COG
# ============================================================


class Top10(commands.Cog):
    """
    PAG Core
    Top 10 Cog

    Slash:
        /top10
        /top10-set
        /top10-edit
        /top10-remove
        /top10-reset

    Prefix:
        !top10
        !top10-set
        !top10-edit
        !top10-remove
        !top10-reset

    Storage:
        Top10Service(database_path=bot.config.database_path, roblox_service=bot.roblox_service)
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        top10_service: Top10Service,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.service = top10_service
        self.logger = logger

    async def _load_entries(self) -> list[Top10Entry]:
        return await self.service.get_all()

    async def _send_ranking_to_interaction(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            entries = await self._load_entries()
        except Exception:
            self.logger.exception("Top 10 listesi yüklenemedi.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Top 10 Ulaşılamıyor",
                    "PAG Top 10 şu anda yüklenemiyor.",
                ),
            )
            return

        if not entries:
            await interaction.followup.send(
                embed=Top10Embeds.empty(),
            )
            return

        await interaction.followup.send(
            embed=Top10Embeds.player(
                entries[0],
                page_index=0,
                total_pages=len(entries),
            ),
            view=Top10RankingView(
                service=self.service,
                entries=entries,
            ),
        )

    async def _send_ranking_to_ctx(
        self,
        ctx: commands.Context,
    ) -> None:
        try:
            entries = await self._load_entries()
        except Exception:
            self.logger.exception("Top 10 listesi yüklenemedi.")
            await ctx.send(
                embed=Top10Embeds.error(
                    "❌ Top 10 Ulaşılamıyor",
                    "PAG Top 10 şu anda yüklenemiyor.",
                ),
            )
            return

        if not entries:
            await ctx.send(embed=Top10Embeds.empty())
            return

        await ctx.send(
            embed=Top10Embeds.player(
                entries[0],
                page_index=0,
                total_pages=len(entries),
            ),
            view=Top10RankingView(
                service=self.service,
                entries=entries,
            ),
        )

    async def _send_management_to_interaction(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            count = await self.service.count()
        except Exception:
            self.logger.exception("Top 10 count alınamadı.")
            count = 0

        await interaction.response.send_message(
            embed=Top10Embeds.management(count),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    async def _send_management_to_ctx(
        self,
        ctx: commands.Context,
    ) -> None:
        try:
            count = await self.service.count()
        except Exception:
            self.logger.exception("Top 10 count alınamadı.")
            count = 0

        await ctx.send(
            embed=Top10Embeds.management(count),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
            ),
        )

    async def _add_player(
        self,
        *,
        interaction: discord.Interaction | None = None,
        ctx: commands.Context | None = None,
        position: int,
        username: str,
        rank: str,
        notes: str | None,
        added_by: int,
        replace_existing: bool,
    ) -> None:
        username = username.strip()
        rank = rank.strip()
        notes = notes.strip() if notes else None

        if interaction is not None:
            await interaction.response.defer(ephemeral=True)
        elif ctx is not None:
            await ctx.trigger_typing()

        try:
            entry = await self.service.add(
                position=position,
                username=username,
                rank=rank,
                added_by=added_by,
                notes=notes,
                replace_existing=replace_existing,
            )
        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=position,
                username=username,
            )
            embed = Top10Embeds.error(title, description)
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return
        except sqlite3.IntegrityError:
            embed = Top10Embeds.error(
                "❌ Veritabanı Çakışması",
                "Kayıt veritabanına yazılamadı.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return
        except Exception:
            self.logger.exception("Top 10 add işlemi beklenmeyen hata verdi.")
            embed = Top10Embeds.error(
                "❌ Beklenmeyen Hata",
                "Oyuncu eklenemedi.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return

        embed = Top10Embeds.success(
            "✅ Oyuncu Eklendi",
            f"**{entry.roblox_display_name}** başarıyla **#{entry.position}** konumuna yazıldı.",
        )
        embed.add_field(name="Roblox", value=f"`{entry.roblox_username}`", inline=True)
        embed.add_field(name="Rank", value=f"`{entry.rank}`", inline=True)
        embed.add_field(name="User ID", value=f"`{entry.roblox_user_id}`", inline=True)

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        if interaction is not None:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed)

    async def _update_player(
        self,
        *,
        interaction: discord.Interaction | None = None,
        ctx: commands.Context | None = None,
        position: int,
        username: str | None,
        rank: str | None,
        notes: str | None,
        new_position: int | None,
        updated_by: int,
    ) -> None:
        if interaction is not None:
            await interaction.response.defer(ephemeral=True)
        elif ctx is not None:
            await ctx.trigger_typing()

        try:
            entry = await self.service.update(
                position=position,
                updated_by=updated_by,
                username=username,
                rank=rank,
                notes=notes,
                new_position=new_position,
            )
        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=new_position or position,
                username=username,
            )
            embed = Top10Embeds.error(title, description)
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return
        except sqlite3.IntegrityError:
            embed = Top10Embeds.error(
                "❌ Veritabanı Çakışması",
                "Güncelleme veritabanına yazılamadı.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return
        except Exception:
            self.logger.exception("Top 10 update işlemi beklenmeyen hata verdi.")
            embed = Top10Embeds.error(
                "❌ Beklenmeyen Hata",
                "Oyuncu güncellenemedi.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return

        embed = Top10Embeds.success(
            "✅ Oyuncu Güncellendi",
            f"**{entry.roblox_display_name}** başarıyla güncellendi.",
        )
        embed.add_field(name="Position", value=f"**#{entry.position}**", inline=True)
        embed.add_field(name="Roblox", value=f"`{entry.roblox_username}`", inline=True)
        embed.add_field(name="Rank", value=f"`{entry.rank}`", inline=True)

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        if interaction is not None:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed)

    async def _remove_player(
        self,
        *,
        interaction: discord.Interaction | None = None,
        ctx: commands.Context | None = None,
        position: int,
        confirm_text: bool = False,
    ) -> None:
        if interaction is not None:
            await interaction.response.defer(ephemeral=True)
        elif ctx is not None:
            await ctx.trigger_typing()

        if confirm_text is False and ctx is not None:
            # Prefix tarafında hızlı ama güvenli akış:
            # önce mevcut kaydı bulup onay paneli gösteriyoruz.
            try:
                entry = await self.service.get_by_position(position)
            except Exception:
                self.logger.exception("Silme öncesi pozisyon yüklenemedi.")
                await ctx.send(
                    embed=Top10Embeds.error(
                        "❌ Yükleme Başarısız",
                        "Oyuncu kontrol edilemedi.",
                    )
                )
                return

            if entry is None:
                await ctx.send(
                    embed=Top10Embeds.error(
                        "❌ Pozisyon Boş",
                        f"**#{position}** konumunda oyuncu yok.",
                    )
                )
                return

            await ctx.send(
                embed=Top10Embeds.warning(
                    "⚠️ Silmeyi Onayla",
                    f"**{entry.roblox_display_name}** oyuncusu **#{entry.position}** konumundan kaldırılsın mı?",
                ),
                view=Top10RemoveConfirmView(
                    service=self.service,
                    logger=self.logger,
                    entry=entry,
                    author_id=ctx.author.id,
                ),
            )
            return

        try:
            removed = await self.service.remove(position)
        except (
            InvalidPositionError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(error, position=position)
            embed = Top10Embeds.error(title, description)
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return
        except Exception:
            self.logger.exception("Top 10 remove işlemi beklenmeyen hata verdi.")
            embed = Top10Embeds.error(
                "❌ Beklenmeyen Hata",
                "Oyuncu kaldırılamadı.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return

        embed = Top10Embeds.success(
            "✅ Oyuncu Kaldırıldı",
            f"**{removed.roblox_display_name}** başarıyla **#{removed.position}** konumundan kaldırıldı.",
        )

        if interaction is not None:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed)

    async def _reset_top10(
        self,
        *,
        interaction: discord.Interaction | None = None,
        ctx: commands.Context | None = None,
        confirm_text: bool = False,
    ) -> None:
        if interaction is not None:
            await interaction.response.defer(ephemeral=True)
        elif ctx is not None:
            await ctx.trigger_typing()

        if not confirm_text:
            if ctx is not None:
                await ctx.send(
                    embed=Top10Embeds.warning(
                        "⚠️ Top 10 Sıfırlansın mı?",
                        "Bu işlem listedeki tüm oyuncuları siler.\n\nDevam etmek için onay ver.",
                    ),
                    view=Top10ResetConfirmView(
                        service=self.service,
                        logger=self.logger,
                        author_id=ctx.author.id,
                    ),
                )
                return

            if interaction is not None:
                await interaction.followup.send(
                    embed=Top10Embeds.warning(
                        "⚠️ Top 10 Sıfırlansın mı?",
                        "Bu işlem listedeki tüm oyuncuları siler.\n\nDevam etmek için onay ver.",
                    ),
                    view=Top10ResetConfirmView(
                        service=self.service,
                        logger=self.logger,
                        author_id=interaction.user.id,
                    ),
                    ephemeral=True,
                )
                return

        try:
            deleted_count = await self.service.clear()
        except Exception:
            self.logger.exception("Top 10 reset işlemi beklenmeyen hata verdi.")
            embed = Top10Embeds.error(
                "❌ Reset Başarısız",
                "Top 10 listesi sıfırlanamadı.",
            )
            if interaction is not None:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return

        embed = Top10Embeds.success(
            "✅ Top 10 Sıfırlandı",
            f"Listeden **{deleted_count}** kayıt silindi.",
        )
        if interaction is not None:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed)

    # ========================================================
    # SLASH COMMANDS
    # ========================================================

    @app_commands.command(
        name="top10",
        description="PAG Top 10 listesini gösterir.",
    )
    @app_commands.guild_only()
    async def top10(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._send_ranking_to_interaction(interaction)

    @app_commands.command(
        name="top10-set",
        description="Top 10 yönetim panelini açar.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_set(self, interaction: discord.Interaction) -> None:
        await self._send_management_to_interaction(interaction)

    @app_commands.command(
        name="top10-edit",
        description="Top 10 içindeki bir oyuncuyu düzenler.",
    )
    @app_commands.describe(
        position="Düzenlenecek mevcut pozisyon.",
        username="Yeni Roblox kullanıcı adı.",
        rank="Yeni PAG rank.",
        new_position="Yeni pozisyon.",
        notes="Yeni not.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_edit(
        self,
        interaction: discord.Interaction,
        position: int,
        username: str | None = None,
        rank: str | None = None,
        new_position: int | None = None,
        notes: str | None = None,
    ) -> None:
        if username is None and rank is None and new_position is None and notes is None:
            await interaction.response.send_modal(
                Top10EditModal(
                    service=self.service,
                    logger=self.logger,
                    updated_by=interaction.user.id,
                )
            )
            return

        await self._update_player(
            interaction=interaction,
            position=position,
            username=username,
            rank=rank,
            notes=notes,
            new_position=new_position,
            updated_by=interaction.user.id,
        )

    @app_commands.command(
        name="top10-remove",
        description="Top 10 içindeki bir oyuncuyu kaldırır.",
    )
    @app_commands.describe(
        position="Kaldırılacak pozisyon.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_remove(
        self,
        interaction: discord.Interaction,
        position: int,
    ) -> None:
        await interaction.response.send_modal(
            Top10RemoveModal(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            )
        )

    @app_commands.command(
        name="top10-reset",
        description="PAG Top 10 listesini sıfırlar.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=Top10Embeds.warning(
                "⚠️ Top 10 Sıfırlansın mı?",
                "Bu işlem listedeki tüm oyuncuları siler.\n\nDevam etmek için onay ver.",
            ),
            view=Top10ResetConfirmView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # PREFIX COMMANDS
    # ========================================================

    @commands.command(name="top10")
    @commands.guild_only()
    async def top10_prefix(self, ctx: commands.Context) -> None:
        await self._send_ranking_to_ctx(ctx)

    @commands.command(name="top10-set")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_set_prefix(
        self,
        ctx: commands.Context,
        position: int | None = None,
        username: str | None = None,
        rank: str | None = None,
        replace_existing: bool = False,
        *,
        notes: str | None = None,
    ) -> None:
        if position is None or username is None or rank is None:
            await self._send_management_to_ctx(ctx)
            return

        await self._add_player(
            ctx=ctx,
            position=position,
            username=username,
            rank=rank,
            notes=notes,
            added_by=ctx.author.id,
            replace_existing=replace_existing,
        )

    @commands.command(name="top10-edit")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_edit_prefix(
        self,
        ctx: commands.Context,
        position: int | None = None,
        username: str | None = None,
        rank: str | None = None,
        new_position: int | None = None,
        *,
        notes: str | None = None,
    ) -> None:
        if position is None:
            await self._send_management_to_ctx(ctx)
            return

        if username is None and rank is None and new_position is None and notes is None:
            await self._send_management_to_ctx(ctx)
            return

        await self._update_player(
            ctx=ctx,
            position=position,
            username=username,
            rank=rank,
            notes=notes,
            new_position=new_position,
            updated_by=ctx.author.id,
        )

    @commands.command(name="top10-remove")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_remove_prefix(
        self,
        ctx: commands.Context,
        position: int | None = None,
        confirm: str | bool = False,
    ) -> None:
        if position is None:
            await self._send_management_to_ctx(ctx)
            return

        await self._remove_player(
            ctx=ctx,
            position=position,
            confirm_text=_is_true_like(confirm),
        )

    @commands.command(name="top10-reset")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_reset_prefix(
        self,
        ctx: commands.Context,
        confirm: str | bool = False,
    ) -> None:
        await self._reset_top10(
            ctx=ctx,
            confirm_text=_is_true_like(confirm),
        )

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ Bu komut için Administrator yetkisi gerekir."
        else:
            self.logger.exception("Top 10 slash komut hatası.")
            message = "❌ İşlem sırasında beklenmeyen bir hata oluştu."

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
            await ctx.send(
                embed=Top10Embeds.error(
                    "❌ Yetki Eksik",
                    "Bu komut için Administrator yetkisi gerekir.",
                ),
                delete_after=8,
            )
            return

        if isinstance(error, commands.CommandNotFound):
            return

        self.logger.exception("Top 10 prefix komut hatası.")
        await ctx.send(
            embed=Top10Embeds.error(
                "❌ Komut Hatası",
                "İşlem sırasında beklenmeyen bir hata oluştu.",
            ),
            delete_after=8,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(bot: commands.Bot) -> None:
    top10_service = Top10Service(
        database_path=bot.config.database_path,
        roblox_service=bot.roblox_service,
    )

    await bot.add_cog(
        Top10(
            bot,
            top10_service=top10_service,
            logger=bot.logger,
        ),
    )