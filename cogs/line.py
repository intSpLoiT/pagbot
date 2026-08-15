from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from cogs.verify import VerifyConfig
from services.line_service import LineService
from services.roblox_service import RobloxAPIError, RobloxNotFoundError


class LineConfig:
    PANEL_COMMAND = "line-panel"
    VERIFY_CHANNEL_NAME = VerifyConfig.VERIFIED_CHANNEL_NAME
    GIF_PATH = Path(__file__).resolve().parent.parent / "gifs" / "pag.gif"
    STAFF_ROLES = frozenset({"owner", "temp owner", "admin", "line manager"})
    MATCH_TYPES = ("FCW", "OCW", "TSBCC", "SCRIM")
    APPLICATION_PUBLIC_COOLDOWN = 1800
    LOG_CHANNEL_NAME = "line-logs"


class LineServiceError(RuntimeError):
    pass


class SlotSelect(discord.ui.Select):
    def __init__(self, cog: "Line") -> None:
        options = [
            discord.SelectOption(label=f"Slot {slot}", value=str(slot), emoji="🔹")
            for slot in range(1, 6)
        ]
        super().__init__(placeholder="Oyuncunun gireceği slotu seç…", options=options, min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.add_player_from_selection(interaction, int(self.values[0]))
        except Exception as exc:
            self.cog.logger.exception("Line slot selection failed: %s", exc)
            await interaction.followup.send("❌ İşlem sırasında bir hata oluştu.", ephemeral=True)


class AddPlayerSelect(discord.ui.UserSelect):
    def __init__(self, cog: "Line") -> None:
        super().__init__(placeholder="Line'a eklenecek üyeyi seç…", min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        member = self.values[0]
        view = discord.ui.View(timeout=120)
        view.add_item(SlotSelect(self.cog))
        self.cog._pending_add_member[interaction.user.id] = member.id
        await interaction.response.send_message(
            embed=self.cog.info_embed(
                "Oyuncu seçildi",
                f"**{member.mention}** için bir slot seç.",
            ),
            view=view,
            ephemeral=True,
        )


class RemovePlayerSelect(discord.ui.Select):
    def __init__(self, cog: "Line", rows: list[dict[str, Any]]) -> None:
        options = [
            discord.SelectOption(
                label=f"Slot {row['slot']} • {row['roblox_username']}",
                value=str(row["slot"]),
            )
            for row in rows
        ]
        super().__init__(placeholder="Çıkarılacak oyuncuyu seç…", options=options, min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        slot = int(self.values[0])
        await self.cog.service.replace_slot(interaction.guild.id, "main_line", slot, None)
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "PLAYER_REMOVED", f"Main Line Slot {slot}")
        await self.cog.send_line_log(interaction.guild, interaction.user, "PLAYER_REMOVED", f"Main Line Slot {slot}")
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.edit_message(content=f"✅ Slot {slot} boşaltıldı.", embed=None, view=None)


class MainCWLineSelect(discord.ui.Select):
    def __init__(self, cog: "Line", rows: list[dict[str, Any]]) -> None:
        self.cog = cog
        options = [
            discord.SelectOption(
                label=f"Slot {row['slot']} • {row['roblox_username']}",
                value=str(row['discord_id']),
                description="Main Line oyuncusu",
            )
            for row in rows
        ]
        super().__init__(
            placeholder="Main Line'dan CW oyuncularını seç…",
            options=options,
            min_values=1,
            max_values=min(5, len(options)),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        main = await self.cog.service.get_line(interaction.guild.id, "main_line")
        selected = {int(value) for value in self.values}
        ordered = [row for row in main if int(row["discord_id"]) in selected]
        players = [
            {
                "discord_id": int(row["discord_id"]),
                "roblox_id": int(row["roblox_id"]),
                "roblox_username": str(row["roblox_username"]),
            }
            for row in ordered
        ]
        await self.cog.service.set_line(interaction.guild.id, "cw_line", players)
        details = ", ".join(p["roblox_username"] for p in players)
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "CW_LINE_SET_FROM_MAIN", details)
        await self.cog.send_line_log(interaction.guild, interaction.user, "CW_LINE_SET_FROM_MAIN", details)
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ Current CW Line Main Line'dan oluşturuldu.", ephemeral=True)


class SetCWLineSelect(discord.ui.UserSelect):
    def __init__(self, cog: "Line") -> None:
        super().__init__(placeholder="Current CW Line oyuncularını seç…", min_values=1, max_values=5)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        members = list(self.values)[:5]
        players: list[dict[str, Any]] = []
        for member in members:
            player = await self.cog.resolve_verified_player(member)
            if player is None:
                await interaction.response.send_message(
                    f"❌ {member.mention} verify olmamış. Current CW Line'a alınamaz.", ephemeral=True
                )
                return
            players.append(player)
        await self.cog.service.set_line(interaction.guild.id, "cw_line", players)
        details = ", ".join(p["roblox_username"] for p in players)
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "CW_LINE_UPDATED", details)
        await self.cog.send_line_log(interaction.guild, interaction.user, "CW_LINE_UPDATED", details)
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ Current CW Line güncellendi.", ephemeral=True)


class ApplicationReviewView(discord.ui.View):
    def __init__(self, cog: "Line", application_id: int) -> None:
        super().__init__(timeout=86400)
        self.cog = cog
        self.application_id = application_id

    @discord.ui.button(label="Kabul Et", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        row = await self.cog.bot.database.fetchone(
            "SELECT * FROM line_applications WHERE id = ? AND status = 'pending' LIMIT 1",
            (self.application_id,),
        )
        if row is None:
            await interaction.response.send_message("❌ Başvuru artık aktif değil.", ephemeral=True)
            return
        await self.cog.service.review_application(self.application_id, interaction.user.id, "accepted")
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "APPLICATION_ACCEPTED", str(self.application_id))
        await self.cog.send_line_log(interaction.guild, interaction.user, "APPLICATION_ACCEPTED", str(self.application_id))
        await interaction.response.edit_message(content="✅ Başvuru kabul edildi.", view=None)

    @discord.ui.button(label="Reddet", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        await self.cog.service.review_application(self.application_id, interaction.user.id, "rejected")
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "APPLICATION_REJECTED", str(self.application_id))
        await self.cog.send_line_log(interaction.guild, interaction.user, "APPLICATION_REJECTED", str(self.application_id))
        await interaction.response.edit_message(content="❌ Başvuru reddedildi.", view=None)


class ApplicationView(discord.ui.View):
    def __init__(self, cog: "Line") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Verify Yap", style=discord.ButtonStyle.primary, emoji="🔗")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Bu buton sadece sunucuda kullanılabilir.", ephemeral=True)
            return
        channel = discord.utils.find(
            lambda c: isinstance(c, discord.TextChannel) and c.name == LineConfig.VERIFY_CHANNEL_NAME,
            interaction.guild.channels,
        )
        if channel is None:
            await interaction.response.send_message(
                f"❌ Verify kanalı `{LineConfig.VERIFY_CHANNEL_NAME}` bulunamadı.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔗 Verify işlemi için {channel.mention} kanalına geçebilirsin.", ephemeral=True
        )

    @discord.ui.button(label="Başvuruyu Gönder", style=discord.ButtonStyle.success, emoji="⚔️")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return
        player = await self.cog.resolve_verified_player(interaction.user)
        if player is None:
            await interaction.response.send_message(
                "❌ Önce Roblox hesabını verify etmelisin. Ardından bu butondan tekrar başvurabilirsin.", ephemeral=True
            )
            return
        created = await self.cog.service.create_application(interaction.guild.id, player)
        if not created:
            await interaction.response.send_message("ℹ️ Zaten bekleyen bir line başvurun var.", ephemeral=True)
            return
        details = player["roblox_username"]
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "APPLICATION_SUBMITTED", details)
        await self.cog.send_line_log(interaction.guild, interaction.user, "APPLICATION_SUBMITTED", details)
        await self.cog.send_application_review(interaction.guild, player)
        await self.cog.send_public_application_notice(interaction.guild, interaction.user, player)
        await interaction.response.send_message(
            "✅ Başvurun yönetime iletildi. Değerlendirme sonucunu bekleyebilirsin.", ephemeral=True
        )


class LinePanelView(discord.ui.View):
    def __init__(self, cog: "Line") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Add Player", style=discord.ButtonStyle.success, emoji="➕", custom_id="pag_line_add")
    async def add_player(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        view = discord.ui.View(timeout=120)
        view.add_item(AddPlayerSelect(self.cog))
        await interaction.response.send_message("Line'a eklenecek oyuncuyu seç:", view=view, ephemeral=True)

    @discord.ui.button(label="Remove Player", style=discord.ButtonStyle.danger, emoji="➖", custom_id="pag_line_remove")
    async def remove_player(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        rows = await self.cog.service.get_line(interaction.guild.id, "main_line")
        if not rows:
            await interaction.response.send_message("ℹ️ Main Line boş.", ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(RemovePlayerSelect(self.cog, rows))
        await interaction.response.send_message("Çıkarılacak oyuncuyu seç:", view=view, ephemeral=True)

    @discord.ui.button(label="Set CW Line", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="pag_line_cw")
    async def set_cw(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        rows = await self.cog.service.get_line(interaction.guild.id, "main_line")
        if not rows:
            await interaction.response.send_message("❌ Önce Main Line'a oyuncu eklemelisin.", ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(MainCWLineSelect(self.cog, rows))
        await interaction.response.send_message("Current CW Line için Main Line oyuncularından seçim yap:", view=view, ephemeral=True)

    @discord.ui.button(label="Reset Line", style=discord.ButtonStyle.danger, emoji="♻️", custom_id="pag_line_reset")
    async def reset_line(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction, require_unlocked=True):
            return
        await self.cog.service.clear_line(interaction.guild.id, "main_line")
        await self.cog.service.clear_line(interaction.guild.id, "cw_line")
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "LINE_RESET")
        await self.cog.send_line_log(interaction.guild, interaction.user, "LINE_RESET", "Main Line + Current CW Line")
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ Main Line ve Current CW Line sıfırlandı.", ephemeral=True)

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="pag_line_lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        settings = await self.cog.service.get_settings(interaction.guild.id)
        new_state = not bool(settings.get("locked"))
        await self.cog.service.upsert_settings(interaction.guild.id, locked=new_state)
        details = "LOCKED" if new_state else "UNLOCKED"
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "LINE_LOCK_CHANGED", details)
        await self.cog.send_line_log(interaction.guild, interaction.user, "LINE_LOCK_CHANGED", details)
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message(
            f"{'🔒 Line kilitlendi.' if new_state else '🔓 Line kilidi açıldı.'}", ephemeral=True
        )

    @discord.ui.button(label="Edit CW Line", style=discord.ButtonStyle.secondary, emoji="🛠️", row=1, custom_id="pag_line_cw_edit")
    async def edit_cw(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        view = discord.ui.View(timeout=120)
        view.add_item(SetCWLineSelect(self.cog))
        await interaction.response.send_message(
            "Current CW Line bağımsızdır. Yeni 1–5 oyunculuk kadroyu seç:", view=view, ephemeral=True
        )

    @discord.ui.button(label="Start Match", style=discord.ButtonStyle.success, emoji="🟢", row=1, custom_id="pag_line_start")
    async def start_match(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        cw = await self.cog.service.get_line(interaction.guild.id, "cw_line")
        if not cw:
            await interaction.response.send_message("❌ Önce Current CW Line oluşturmalısın.", ephemeral=True)
            return
        await interaction.response.send_modal(StartMatchModal(self.cog))

    @discord.ui.button(label="End Match", style=discord.ButtonStyle.danger, emoji="⛔", row=1, custom_id="pag_line_end")
    async def end_match(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.cog.guard_staff(interaction):
            return
        match = await self.cog.service.get_match(interaction.guild.id)
        if match.get("status") in {None, "IDLE", "ENDED"}:
            await interaction.response.send_message("ℹ️ Aktif maç bulunmuyor.", ephemeral=True)
            return
        await self.cog.service.set_match(
            interaction.guild.id,
            match_type=str(match.get("match_type") or ""),
            opponent=str(match.get("opponent") or ""),
            status="ENDED",
        )
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "MATCH_ENDED")
        await self.cog.send_line_log(interaction.guild, interaction.user, "MATCH_ENDED")
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ Maç sona erdirildi.", ephemeral=True)

    @discord.ui.button(label="Katılmak İstiyorum", style=discord.ButtonStyle.primary, emoji="🙋", row=2, custom_id="pag_line_apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=self.cog.application_embed(), view=ApplicationView(self.cog), ephemeral=True)

    @discord.ui.button(label="Watch", style=discord.ButtonStyle.secondary, emoji="👀", row=2, custom_id="pag_line_watch")
    async def watch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return
        watchers = self.cog._watchers.setdefault(interaction.guild.id, set())
        if interaction.user.id in watchers:
            watchers.remove(interaction.user.id)
            state = "izlemeyi bıraktın"
        else:
            watchers.add(interaction.user.id)
            state = "canlı savaşı izliyorsun"
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message(f"👀 Artık {state}.", ephemeral=True)

    @discord.ui.button(label="Player Info", style=discord.ButtonStyle.secondary, emoji="👤", row=2, custom_id="pag_line_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        main = await self.cog.service.get_line(interaction.guild.id, "main_line")
        cw = await self.cog.service.get_line(interaction.guild.id, "cw_line")
        lines = ["**Main Line**", "\n".join(f"Slot {r['slot']}: `{r['roblox_username']}`" for r in main) or "Empty"]
        lines.extend(["", "**Current CW Line**", "\n".join(f"Slot {r['slot']}: `{r['roblox_username']}`" for r in cw) or "Empty"])
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class StartMatchModal(discord.ui.Modal, title="Start TSBCC Match"):
    match_type = discord.ui.TextInput(label="Match Type", placeholder="FCW / OCW / TSBCC / Scrim", required=True, max_length=10)
    opponent = discord.ui.TextInput(label="Opponent", placeholder="Rakip clan", required=True, max_length=100)

    def __init__(self, cog: "Line") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        match_type = str(self.match_type.value).strip().upper()
        if match_type == "SCRIM":
            match_type = "SCRIM"
        if match_type not in LineConfig.MATCH_TYPES:
            await interaction.response.send_message("❌ Match type: FCW, OCW, TSBCC veya Scrim olmalı.", ephemeral=True)
            return
        await self.cog.service.set_match(
            interaction.guild.id,
            match_type=match_type,
            opponent=str(self.opponent.value).strip(),
            status="LIVE",
        )
        details = f"{match_type} vs {self.opponent.value.strip()}"
        await self.cog.service.log(interaction.guild.id, interaction.user.id, "MATCH_STARTED", details)
        await self.cog.send_line_log(interaction.guild, interaction.user, "MATCH_STARTED", details)
        await self.cog.refresh_panel(interaction.guild)
        await interaction.response.send_message(f"⚔️ {match_type} maçı LIVE olarak başlatıldı.", ephemeral=True)


class Line(commands.Cog):
    """PAG TSBCC line, live match and application management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger: logging.Logger = bot.logger
        self.service = LineService(database=bot.database, logger=bot.logger)
        self._view_added = False
        self._pending_add_member: dict[int, int] = {}
        self._watchers: dict[int, set[int]] = {}
        self._panel_locks: dict[int, asyncio.Lock] = {}
        self._last_public_application_notice: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        await self.service.ensure_schema()
        if not self._view_added:
            self.bot.add_view(LinePanelView(self))
            self._view_added = True
        self.logger.info("Persistent TSBCC Line view registered.")

    def role_names(self, member: discord.Member) -> set[str]:
        return {role.name.casefold().strip() for role in member.roles}

    async def guard_staff(self, interaction: discord.Interaction, *, require_unlocked: bool = False) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Bu işlem sunucuda kullanılabilir.", ephemeral=True)
            return False
        member = interaction.user
        allowed = member.guild.owner_id == member.id or bool(self.role_names(member) & LineConfig.STAFF_ROLES)
        if not allowed:
            await interaction.response.send_message("❌ Bu paneli yönetme yetkin yok.", ephemeral=True)
            return False
        if require_unlocked:
            settings = await self.service.get_settings(interaction.guild.id)
            if settings.get("locked"):
                await interaction.response.send_message("🔒 Line şu anda kilitli.", ephemeral=True)
                return False
        return True

    async def resolve_verified_player(self, member: discord.Member) -> dict[str, Any] | None:
        row = await self.bot.database.fetchone(
            "SELECT discord_id, roblox_id, roblox_username FROM verifications WHERE discord_id = ? LIMIT 1",
            (member.id,),
        )
        if row is None:
            return None
        try:
            roblox_id = int(row["roblox_id"])
            roblox_user = await self.bot.roblox_service.get_user(roblox_id)
        except (RobloxNotFoundError, RobloxAPIError, ValueError):
            return None
        return {
            "discord_id": member.id,
            "roblox_id": roblox_id,
            "roblox_username": roblox_user.name,
            "display_name": roblox_user.display_name,
        }

    async def add_player_from_selection(self, interaction: discord.Interaction, slot: int) -> None:
        if interaction.guild is None:
            return
        if not await self.guard_staff(interaction, require_unlocked=True):
            self._pending_add_member.pop(interaction.user.id, None)
            return
        member_id = self._pending_add_member.pop(interaction.user.id, None)
        if member_id is None:
            await interaction.followup.send("❌ Oyuncu seçimi süresi doldu.", ephemeral=True)
            return
        member = interaction.guild.get_member(member_id)
        if member is None:
            await interaction.followup.send("❌ Üye bulunamadı.", ephemeral=True)
            return
        player = await self.resolve_verified_player(member)
        if player is None:
            await interaction.followup.send("❌ Bu kullanıcı verify olmamış veya Roblox bilgisi alınamadı.", ephemeral=True)
            return
        main = await self.service.get_line(interaction.guild.id, "main_line")
        if any(int(row["discord_id"]) == member.id and int(row["slot"]) != slot for row in main):
            await interaction.followup.send("❌ Bu oyuncu zaten başka bir slotta.", ephemeral=True)
            return
        try:
            await self.service.replace_slot(interaction.guild.id, "main_line", slot, player)
        except Exception:
            await interaction.followup.send("❌ Slot güncellenemedi. Muhtemelen oyuncu zaten line içinde.", ephemeral=True)
            raise
        details = f"Slot {slot}: {player['roblox_username']}"
        await self.service.log(interaction.guild.id, interaction.user.id, "PLAYER_ADDED", details)
        await self.send_line_log(interaction.guild, interaction.user, "PLAYER_ADDED", details)
        await self.refresh_panel(interaction.guild)
        await interaction.followup.send(
            f"✅ Slot {slot} → **{player['roblox_username']}**",
            ephemeral=True,
        )

    def application_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ PAG • Line Application",
            description=(
                "TSBCC line kadrosuna katılmak için başvurmadan önce aşağıdakileri tamamlamalısın.\n\n"
                "✅ Roblox hesabın verify edilmiş olmalı.\n"
                "✅ TSBCC / clan kurallarına uymalısın.\n"
                "✅ Başvurular yönetim tarafından değerlendirilir.\n"
                "✅ Başvuru yapmak otomatik olarak line'a girmek anlamına gelmez."
            ),
            color=discord.Colour.blurple(),
        )
        embed.set_footer(text="PAG • TSBCC Line Management")
        return embed

    async def send_application_review(self, guild: discord.Guild, player: dict[str, Any]) -> None:
        channel = await self.get_log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title="⚔️ NEW LINE APPLICATION",
            description=(
                f"**Discord:** <@{player['discord_id']}>\n"
                f"**Roblox:** `{player['roblox_username']}`\n"
                f"**Verify:** ✅ Verified"
            ),
            color=discord.Colour.gold(),
        )
        row = await self.bot.database.fetchone(
            "SELECT id FROM line_applications WHERE guild_id = ? AND discord_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (guild.id, player["discord_id"]),
        )
        if row is not None:
            await channel.send(embed=embed, view=ApplicationReviewView(self, int(row["id"])))

    async def send_public_application_notice(self, guild: discord.Guild, member: discord.Member, player: dict[str, Any]) -> None:
        key = (guild.id, member.id)
        now = discord.utils.utcnow().timestamp()
        previous = self._last_public_application_notice.get(key, 0.0)
        if now - previous < LineConfig.APPLICATION_PUBLIC_COOLDOWN:
            return
        self._last_public_application_notice[key] = now
        settings = await self.service.get_settings(guild.id)
        channel_id = settings.get("panel_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                f"⚔️ **Yeni line başvurusu!** {member.mention} TSBCC kadrosuna katılmak için başvurdu. **Roblox:** `{player['roblox_username']}`"
            )

    async def send_line_log(
        self,
        guild: discord.Guild,
        actor: discord.abc.User,
        action: str,
        details: str = "",
    ) -> None:
        channel = await self.get_log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(title=f"📋 LINE LOG • {action}", color=discord.Colour.dark_grey())
        embed.add_field(name="Actor", value=f"<@{actor.id}>", inline=True)
        embed.add_field(name="Action", value=f"`{action}`", inline=True)
        if details:
            embed.add_field(name="Details", value=details[:1000], inline=False)
        embed.set_footer(text="PAG • TSBCC Line Audit")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            self.logger.warning("Failed to send line log embed: %s", exc)

    async def get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        settings = await self.service.get_settings(guild.id)
        channel_id = settings.get("log_channel_id")
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if isinstance(channel, discord.TextChannel):
                return channel
        log_channel = discord.utils.find(
            lambda c: isinstance(c, discord.TextChannel) and c.name == LineConfig.LOG_CHANNEL_NAME,
            guild.channels,
        )
        if isinstance(log_channel, discord.TextChannel):
            return log_channel
        panel_channel_id = settings.get("panel_channel_id")
        panel_channel = guild.get_channel(int(panel_channel_id)) if panel_channel_id else None
        return panel_channel if isinstance(panel_channel, discord.TextChannel) else None

    def info_embed(self, title: str, description: str) -> discord.Embed:
        return discord.Embed(title=f"ℹ️ {title}", description=description, color=discord.Colour.blurple())

    def build_panel_embed(
        self,
        guild: discord.Guild,
        main: list[dict[str, Any]],
        cw: list[dict[str, Any]],
        settings: dict[str, Any],
        match: dict[str, Any],
    ) -> discord.Embed:
        status = str(match.get("status") or "IDLE").upper()
        color = discord.Colour.green() if status == "LIVE" else discord.Colour.blurple()
        if status == "ENDED":
            color = discord.Colour.red()
        embed = discord.Embed(title="⚔️ PAG • TSBCC LINE MANAGEMENT", color=color)
        embed.description = (
            "`LIVE` • TSBCC CLAN WAR CONTROL PANEL\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"**Match:** `{status}`\n"
            f"**Type:** `{match.get('match_type') or '—'}`\n"
            f"**Opponent:** `{match.get('opponent') or '—'}`\n"
            f"**Line:** {'🔒 LOCKED' if settings.get('locked') else '🔓 UNLOCKED'}\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        main_text = "\n".join(
            f"**{row['slot']}.** `{row['roblox_username']}`  • <@{row['discord_id']}>"
            for row in main
        ) or "`Empty`"
        cw_text = "\n".join(
            f"**{row['slot']}.** `{row['roblox_username']}`  • <@{row['discord_id']}>"
            for row in cw
        ) or "`No active CW line`"
        embed.add_field(name="👥 Main Line", value=main_text, inline=False)
        embed.add_field(name="⚔️ Current CW Line", value=cw_text, inline=False)
        watchers = len(self._watchers.get(guild.id, set()))
        embed.add_field(name="👀 Watching", value=str(watchers), inline=True)
        embed.add_field(name="🔗 Verify", value=f"`{LineConfig.VERIFY_CHANNEL_NAME}`", inline=True)
        embed.add_field(name="🕒 Updated", value=discord.utils.utcnow().strftime("%d.%m.%Y %H:%M UTC"), inline=True)
        embed.set_footer(text="PAG • TSBCC official clan war panel")
        return embed

    async def refresh_panel(self, guild: discord.Guild, *, message: discord.Message | None = None) -> None:
        lock = self._panel_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            settings = await self.service.get_settings(guild.id)
            channel_id = settings.get("panel_channel_id")
            message_id = settings.get("panel_message_id")
            if channel_id is None or message_id is None:
                return
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                return
            target = message
            if target is None:
                try:
                    target = await channel.fetch_message(int(message_id))
                except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                    return
            main = await self.service.get_line(guild.id, "main_line")
            cw = await self.service.get_line(guild.id, "cw_line")
            match = await self.service.get_match(guild.id)
            embed = self.build_panel_embed(guild, main, cw, settings, match)
            try:
                await target.edit(embed=embed, view=LinePanelView(self))
            except discord.HTTPException as exc:
                self.logger.warning("Failed to refresh line panel: %s", exc)

    @app_commands.command(name="line", description="Aktif PAG TSBCC Main Line ve Current CW Line durumunu gösterir.")
    @app_commands.guild_only()
    async def line_status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        main = await self.service.get_line(interaction.guild.id, "main_line")
        cw = await self.service.get_line(interaction.guild.id, "cw_line")
        settings = await self.service.get_settings(interaction.guild.id)
        match = await self.service.get_match(interaction.guild.id)
        embed = self.build_panel_embed(interaction.guild, main, cw, settings, match)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="line-watch", description="Canlı TSBCC Line panelini izlemeye başlar veya izlemeyi bırakır.")
    @app_commands.guild_only()
    async def line_watch(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        watchers = self._watchers.setdefault(interaction.guild.id, set())
        if interaction.user.id in watchers:
            watchers.remove(interaction.user.id)
            state = "izlemeyi bıraktın"
        else:
            watchers.add(interaction.user.id)
            state = "canlı line'ı izlemeye başladın"
        await self.refresh_panel(interaction.guild)
        await interaction.response.send_message(f"👀 Artık {state}.", ephemeral=True)

    @app_commands.command(name="line-apply", description="TSBCC Line'a katılım başvuru ekranını açar.")
    @app_commands.guild_only()
    async def line_apply(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=self.application_embed(),
            view=ApplicationView(self),
            ephemeral=True,
        )

    @commands.command(name="line", aliases=("linestatus",))
    @commands.guild_only()
    async def line_status_prefix(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        main = await self.service.get_line(ctx.guild.id, "main_line")
        cw = await self.service.get_line(ctx.guild.id, "cw_line")
        settings = await self.service.get_settings(ctx.guild.id)
        match = await self.service.get_match(ctx.guild.id)
        embed = self.build_panel_embed(ctx.guild, main, cw, settings, match)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="line-watch", aliases=("linewatch",))
    @commands.guild_only()
    async def line_watch_prefix(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        watchers = self._watchers.setdefault(ctx.guild.id, set())
        if ctx.author.id in watchers:
            watchers.remove(ctx.author.id)
            state = "izlemeyi bıraktın"
        else:
            watchers.add(ctx.author.id)
            state = "canlı line'ı izlemeye başladın"
        await self.refresh_panel(ctx.guild)
        await ctx.send(f"👀 {ctx.author.mention}, artık {state}.", allowed_mentions=discord.AllowedMentions(users=True))

    @commands.command(name="line-apply", aliases=("lineapply",))
    @commands.guild_only()
    async def line_apply_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=self.application_embed(), view=ApplicationView(self))

    @app_commands.command(name="line-panel", description="TSBCC Main Line / Current CW / Live Match panelini oluşturur veya yeniler.")
    @app_commands.guild_only()
    async def line_panel(self, interaction: discord.Interaction) -> None:
        if not await self.guard_staff(interaction):
            return
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)
        await self.service.ensure_schema()
        settings = await self.service.get_settings(interaction.guild.id)
        target = interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.followup.send("❌ Panel yalnızca text channel içinde oluşturulabilir.", ephemeral=True)
            return
        main = await self.service.get_line(interaction.guild.id, "main_line")
        cw = await self.service.get_line(interaction.guild.id, "cw_line")
        match = await self.service.get_match(interaction.guild.id)
        embed = self.build_panel_embed(interaction.guild, main, cw, settings, match)
        view = LinePanelView(self)
        panel_message: discord.Message | None = None
        old_channel_id = settings.get("panel_channel_id")
        old_message_id = settings.get("panel_message_id")
        if old_channel_id == target.id and old_message_id:
            try:
                panel_message = await target.fetch_message(int(old_message_id))
                await panel_message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                panel_message = None
        if panel_message is None:
            if LineConfig.GIF_PATH.exists():
                file = discord.File(LineConfig.GIF_PATH, filename="pag.gif")
                embed.set_image(url="attachment://pag.gif")
                panel_message = await target.send(embed=embed, file=file, view=view)
            else:
                panel_message = await target.send(embed=embed, view=view)
        log_channel = discord.utils.find(
            lambda c: isinstance(c, discord.TextChannel) and c.name == LineConfig.LOG_CHANNEL_NAME,
            interaction.guild.channels,
        )
        await self.service.upsert_settings(
            interaction.guild.id,
            panel_channel_id=target.id,
            panel_message_id=panel_message.id,
            log_channel_id=(log_channel.id if isinstance(log_channel, discord.TextChannel) else target.id),
        )
        await self.service.log(interaction.guild.id, interaction.user.id, "PANEL_CREATED", str(panel_message.id))
        await self.send_line_log(interaction.guild, interaction.user, "PANEL_CREATED", str(panel_message.id))
        await interaction.followup.send(f"✅ TSBCC Line Panel hazır: {panel_message.jump_url}", ephemeral=True)

    @commands.command(name="line-panel", aliases=("linepanel",))
    @commands.guild_only()
    async def line_panel_prefix(self, ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        allowed = ctx.guild.owner_id == ctx.author.id or bool(
            self.role_names(ctx.author) & LineConfig.STAFF_ROLES
        )
        if not allowed:
            await ctx.send("❌ Bu paneli yönetme yetkin yok.", delete_after=6)
            return
        target = ctx.channel
        if not isinstance(target, discord.TextChannel):
            await ctx.send("❌ Panel yalnızca text channel içinde oluşturulabilir.", delete_after=6)
            return
        settings = await self.service.get_settings(ctx.guild.id)
        main = await self.service.get_line(ctx.guild.id, "main_line")
        cw = await self.service.get_line(ctx.guild.id, "cw_line")
        match = await self.service.get_match(ctx.guild.id)
        embed = self.build_panel_embed(ctx.guild, main, cw, settings, match)
        view = LinePanelView(self)
        panel_message = None
        old_channel_id = settings.get("panel_channel_id")
        old_message_id = settings.get("panel_message_id")
        if old_channel_id == target.id and old_message_id:
            try:
                panel_message = await target.fetch_message(int(old_message_id))
                await panel_message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                panel_message = None
        if panel_message is None:
            if LineConfig.GIF_PATH.exists():
                file = discord.File(LineConfig.GIF_PATH, filename="pag.gif")
                embed.set_image(url="attachment://pag.gif")
                panel_message = await target.send(embed=embed, file=file, view=view)
            else:
                panel_message = await target.send(embed=embed, view=view)
        log_channel = discord.utils.find(
            lambda c: isinstance(c, discord.TextChannel) and c.name == LineConfig.LOG_CHANNEL_NAME,
            ctx.guild.channels,
        )
        await self.service.upsert_settings(
            ctx.guild.id,
            panel_channel_id=target.id,
            panel_message_id=panel_message.id,
            log_channel_id=(log_channel.id if isinstance(log_channel, discord.TextChannel) else target.id),
        )
        await self.service.log(ctx.guild.id, ctx.author.id, "PANEL_CREATED", str(panel_message.id))
        await self.send_line_log(ctx.guild, ctx.author, "PANEL_CREATED", str(panel_message.id))
        await ctx.send(f"✅ TSBCC Line Panel hazır: {panel_message.jump_url}", delete_after=8)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Line(bot))
