from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import discord
from discord.ext import commands

from services.discord_service import DiscordService
from services.moderation_service import (
    DEFAULT_GIF_KEY,
    ModerationGIFRecord,
    ModerationNotFoundError,
    ModerationService,
    ModerationServiceError,
    ModerationValidationError,
)
from utils.embeds import PAGEmbeds
from utils.errors import PAGPermissionError, ValidationError
from utils.permissions import PAGPermissions


PAGE_SIZE = 5
HISTORY_PAGE_SIZE = 6
MAX_PURGE_LIMIT = 200
MAX_TIMEOUT_SECONDS = 60 * 60 * 24 * 28
DURATION_TOKEN_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

ACTION_LABELS = {
    "warn": "Warn",
    "note": "Note",
    "timeout": "Timeout",
    "untimeout": "Untimeout",
    "kick": "Kick",
    "ban": "Ban",
    "unban": "Unban",
    "purge": "Purge",
    "lock": "Lock",
    "unlock": "Unlock",
    "slowmode": "Slowmode",
    "nickname": "Nickname",
    DEFAULT_GIF_KEY: "Default",
}

ACTION_COLORS = {
    "warn": discord.Colour.orange(),
    "note": discord.Colour.blurple(),
    "timeout": discord.Colour.dark_orange(),
    "untimeout": discord.Colour.green(),
    "kick": discord.Colour.gold(),
    "ban": discord.Colour.red(),
    "unban": discord.Colour.green(),
    "purge": discord.Colour.teal(),
    "lock": discord.Colour.red(),
    "unlock": discord.Colour.green(),
    "slowmode": discord.Colour.blue(),
    "nickname": discord.Colour.blurple(),
    DEFAULT_GIF_KEY: discord.Colour.blurple(),
}


@dataclass(slots=True)
class ParsedDuration:
    seconds: int
    text: str


@dataclass(slots=True)
class UserProxy:
    id: int
    mention: str
    avatar_url: str | None = None


class ModerationRestrictedView(discord.ui.View):
    def __init__(self, *, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                embed=PAGEmbeds.error("Hata", "Bu panel yalnızca sunucuda kullanılabilir."),
                ephemeral=True,
            )
            return False

        if not PAGPermissions.is_administrator(user):
            await interaction.response.send_message(
                embed=PAGEmbeds.error("Yetkisiz", "Bu paneli yalnızca administrator kullanabilir."),
                ephemeral=True,
            )
            return False

        return True


class ModerationPaginatorView(ModerationRestrictedView):
    def __init__(self, embeds: list[discord.Embed], *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.index = 0
        self.previous_button.disabled = True
        if len(self.embeds) <= 1:
            self.next_button.disabled = True

    async def _update(self, interaction: discord.Interaction) -> None:
        self.previous_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index > 0:
            self.index -= 1
        await self._update(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index < len(self.embeds) - 1:
            self.index += 1
        await self._update(interaction)

    @discord.ui.button(label="Kapat", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()


class ModerationGIFModal(discord.ui.Modal):
    def __init__(self, cog: "ModerationCog", action_key: str, current_url: str | None = None) -> None:
        self.cog = cog
        self.action_key = action_key
        title = f"{ACTION_LABELS.get(action_key, action_key.title())} GIF"
        super().__init__(title=title)

        self.url_input = discord.ui.TextInput(
            label="GIF URL",
            placeholder="https://...",
            default=current_url or "",
            required=True,
            max_length=1000,
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                embed=PAGEmbeds.error("Hata", "Bu panel yalnızca sunucuda kullanılabilir."),
                ephemeral=True,
            )
            return

        if not PAGPermissions.is_administrator(user):
            await interaction.response.send_message(
                embed=PAGEmbeds.error("Yetkisiz", "Bu paneli yalnızca administrator kullanabilir."),
                ephemeral=True,
            )
            return

        try:
            await self.cog.service.set_gif(guild.id, self.action_key, str(self.url_input.value), updated_by=user.id)
        except ModerationValidationError as error:
            await interaction.response.send_message(
                embed=PAGEmbeds.error("Geçersiz GIF", str(error)),
                ephemeral=True,
            )
            return
        except Exception as error:
            self.cog.logger.exception("Failed to save moderation GIF.")
            await interaction.response.send_message(
                embed=PAGEmbeds.error("GIF Kaydedilemedi", f"Beklenmeyen hata: {error}"),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=PAGEmbeds.success(
                "GIF Kaydedildi",
                f"`{ACTION_LABELS.get(self.action_key, self.action_key.title())}` GIF'i güncellendi.",
            ),
            ephemeral=True,
        )


class ModerationGIFView(ModerationRestrictedView):
    def __init__(self, cog: "ModerationCog", *, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog

    async def _current_url(self, action_key: str, guild: discord.Guild | None) -> str | None:
        if guild is None:
            return None
        record = await self.cog.service.get_gif(guild.id, action_key)
        return record.url if record else None

    async def _open(self, interaction: discord.Interaction, action_key: str) -> None:
        current_url = await self._current_url(action_key, interaction.guild)
        await interaction.response.send_modal(ModerationGIFModal(self.cog, action_key, current_url=current_url))

    @discord.ui.button(label="Warn", style=discord.ButtonStyle.secondary)
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "warn")

    @discord.ui.button(label="Note", style=discord.ButtonStyle.secondary)
    async def note_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "note")

    @discord.ui.button(label="Timeout", style=discord.ButtonStyle.secondary)
    async def timeout_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "timeout")

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary)
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "kick")

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.secondary)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "ban")

    @discord.ui.button(label="Unban", style=discord.ButtonStyle.secondary)
    async def unban_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "unban")

    @discord.ui.button(label="Purge", style=discord.ButtonStyle.secondary)
    async def purge_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "purge")

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.secondary)
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "lock")

    @discord.ui.button(label="Unlock", style=discord.ButtonStyle.secondary)
    async def unlock_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "unlock")

    @discord.ui.button(label="Slowmode", style=discord.ButtonStyle.secondary)
    async def slowmode_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, "slowmode")

    @discord.ui.button(label="Default", style=discord.ButtonStyle.primary)
    async def default_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, DEFAULT_GIF_KEY)

    @discord.ui.button(label="Geri", style=discord.ButtonStyle.danger, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_panel(interaction, mode="main")


class ModerationPanelView(ModerationRestrictedView):
    def __init__(self, cog: "ModerationCog", *, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="GIF Ayarları", style=discord.ButtonStyle.primary)
    async def gif_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_panel(interaction, mode="gif")

    @discord.ui.button(label="İstatistik", style=discord.ButtonStyle.secondary)
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_panel(interaction, mode="stats")

    @discord.ui.button(label="Son Kayıtlar", style=discord.ButtonStyle.secondary)
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_panel(interaction, mode="history")

    @discord.ui.button(label="Komutlar", style=discord.ButtonStyle.secondary)
    async def commands_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_panel(interaction, mode="help")


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = getattr(bot, "logger", logging.getLogger(__name__))
        self.service: ModerationService = getattr(
            bot,
            "moderation_service",
            ModerationService(getattr(bot, "database"), logger=self.logger),
        )
        self.discord_service: DiscordService | None = getattr(bot, "discord_service", None)

    async def cog_load(self) -> None:
        await self.service.initialize()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not isinstance(ctx.author, discord.Member):
            raise PAGPermissionError("Sunucu üyesi doğrulanamadı.")
        if not PAGPermissions.is_administrator(ctx.author):
            raise PAGPermissionError("Bu komutlar yalnızca administrator içindir.")
        return True

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, commands.NoPrivateMessage):
            return
        if isinstance(original, (PAGPermissionError, ModerationValidationError, ModerationServiceError, ValidationError)):
            await ctx.send(embed=PAGEmbeds.error("İşlem Başarısız", str(original)))
            return
        if isinstance(original, commands.BadArgument):
            await ctx.send(embed=PAGEmbeds.error("Geçersiz Parametre", str(original)))
            return
        self.logger.exception("Moderation command error.", exc_info=error)
        await ctx.send(embed=PAGEmbeds.error("Beklenmeyen Hata", "Moderasyon komutu işlenemedi."))

    # ----------------------------- helpers -----------------------------

    def _bot_member(self, guild: discord.Guild) -> discord.Member | None:
        if self.bot.user is None:
            return None
        return guild.get_member(self.bot.user.id)

    def _target_proxy(self, obj: Any) -> UserProxy:
        obj_id = int(getattr(obj, "id"))
        mention = getattr(obj, "mention", None) or f"<@{obj_id}>"
        avatar_url = None
        display_avatar = getattr(obj, "display_avatar", None)
        if display_avatar is not None:
            avatar_url = str(getattr(display_avatar, "url", "") or "") or None
        return UserProxy(id=obj_id, mention=str(mention), avatar_url=avatar_url)

    def _is_owner(self, guild: discord.Guild, member: discord.Member) -> bool:
        return guild.owner_id == member.id

    def _require_target_guard(self, ctx: commands.Context, target: discord.Member) -> None:
        if target.id == ctx.author.id:
            raise PAGPermissionError("Kendine işlem uygulayamazsın.")
        if self.bot.user is not None and target.id == self.bot.user.id:
            raise PAGPermissionError("Bota işlem uygulanamaz.")
        if self._is_owner(ctx.guild, target):
            raise PAGPermissionError("Sunucu sahibine işlem uygulanamaz.")

        author = ctx.author
        assert isinstance(author, discord.Member)
        if author.id != ctx.guild.owner_id and author.top_role <= target.top_role:
            raise PAGPermissionError("Bu kullanıcı senin rolünden yüksek veya eşit.")

        bot_member = self._bot_member(ctx.guild)
        if bot_member is not None and bot_member.top_role <= target.top_role:
            raise PAGPermissionError("Botun rolü hedef kullanıcıdan yüksek olmalı.")

    def _require_admin_member(self, member: discord.Member) -> None:
        if not PAGPermissions.is_administrator(member):
            raise PAGPermissionError("Bu işlem yalnızca administrator içindir.")

    def _parse_duration(self, duration_text: str) -> ParsedDuration:
        text = duration_text.strip().lower()
        if not text:
            raise ModerationValidationError("Duration cannot be empty.")
        if text.isdigit():
            seconds = int(text)
            if seconds <= 0:
                raise ModerationValidationError("Duration must be greater than zero.")
            return ParsedDuration(seconds=seconds, text=f"{seconds}s")
        if text in {"perm", "permanent", "forever"}:
            raise ModerationValidationError("Timeout cannot be permanent. Use ban instead.")

        total_seconds = 0
        matched = False
        for amount_text, unit in DURATION_TOKEN_RE.findall(text):
            matched = True
            amount = int(amount_text)
            if amount <= 0:
                raise ModerationValidationError("Duration segments must be greater than zero.")
            unit = unit.lower()
            if unit == "s":
                total_seconds += amount
            elif unit == "m":
                total_seconds += amount * 60
            elif unit == "h":
                total_seconds += amount * 3600
            elif unit == "d":
                total_seconds += amount * 86400
            elif unit == "w":
                total_seconds += amount * 604800

        if not matched or total_seconds <= 0:
            raise ModerationValidationError("Duration format must look like 10m, 1h30m, 2d, or 3600.")
        if total_seconds > MAX_TIMEOUT_SECONDS:
            raise ModerationValidationError("Timeout duration cannot exceed 28 days.")

        return ParsedDuration(seconds=total_seconds, text=text)

    def _format_duration(self, seconds: int) -> str:
        if seconds <= 0:
            return "0s"
        parts: list[str] = []
        weeks, remainder = divmod(seconds, 604800)
        days, remainder = divmod(remainder, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if weeks:
            parts.append(f"{weeks}w")
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds:
            parts.append(f"{seconds}s")
        return " ".join(parts) if parts else "0s"

    def _format_timestamp(self, iso_value: str | None) -> str:
        if not iso_value:
            return "-"
        try:
            dt = datetime.fromisoformat(iso_value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return discord.utils.format_dt(dt, style="F")
        except Exception:
            return iso_value

    def _build_action_embed(
        self,
        *,
        title: str,
        action_key: str,
        target: Any,
        moderator: Any,
        reason: str | None,
        case_id: int | None = None,
        extra_fields: list[tuple[str, str, bool]] | None = None,
        gif_url: str | None = None,
    ) -> discord.Embed:
        target_p = self._target_proxy(target)
        moderator_p = self._target_proxy(moderator)

        embed = PAGEmbeds.custom(
            title=title,
            description=None,
            color=ACTION_COLORS.get(action_key, discord.Colour.blurple()),
            fields=[],
            thumbnail_url=target_p.avatar_url,
            image_url=gif_url,
        )
        embed.add_field(name="Hedef", value=f"{target_p.mention} (`{target_p.id}`)", inline=False)
        embed.add_field(name="Moderatör", value=f"{moderator_p.mention} (`{moderator_p.id}`)", inline=False)
        if case_id is not None:
            embed.add_field(name="Case", value=f"#{case_id}", inline=True)
        embed.add_field(name="Sebep", value=reason or "Belirtilmedi", inline=False)
        if extra_fields:
            for field_name, field_value, inline in extra_fields:
                embed.add_field(name=field_name, value=field_value, inline=inline)
        embed.set_footer(text="PAG Moderation")
        return embed

    async def _send_action(
        self,
        ctx: commands.Context,
        *,
        action_key: str,
        title: str,
        target: Any,
        moderator: Any,
        reason: str | None,
        case_id: int | None = None,
        extra_fields: list[tuple[str, str, bool]] | None = None,
    ) -> None:
        gif = await self.service.get_gif(ctx.guild.id, action_key)
        embed = self._build_action_embed(
            title=title,
            action_key=action_key,
            target=target,
            moderator=moderator,
            reason=reason,
            case_id=case_id,
            extra_fields=extra_fields,
            gif_url=gif.url if gif else None,
        )
        await ctx.send(embed=embed)

    async def _send_pages(self, ctx: commands.Context, embeds: list[discord.Embed]) -> None:
        if not embeds:
            await ctx.send(embed=PAGEmbeds.info("Kayıt Yok", "Gösterilecek veri bulunamadı."))
            return
        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
            return
        await ctx.send(embed=embeds[0], view=ModerationPaginatorView(embeds))

    async def _maybe_defer(self, ctx: commands.Context) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None and not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except Exception:
                pass

    async def _apply_timeout(self, member: discord.Member, until: datetime | None, reason: str | None) -> None:
        timeout_method = getattr(member, "timeout", None)
        if callable(timeout_method):
            await timeout_method(until, reason=reason)
            return
        await member.edit(timed_out_until=until, reason=reason)

    async def _send_panel(self, interaction: discord.Interaction, *, mode: str) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(embed=PAGEmbeds.error("Hata", "Bu panel yalnızca sunucuda kullanılabilir."), ephemeral=True)
            return

        if mode == "gif":
            gifs = await self.service.list_gifs(guild.id)
            description = "Her moderasyon türü için ayrı GIF atayabilirsin. Bir butona bas ve URL gir."
            if gifs:
                lines = []
                for gif in gifs:
                    label = ACTION_LABELS.get(gif.action_key, gif.action_key.title())
                    lines.append(f"• **{label}** → {gif.url}")
                description += "\n\n**Mevcut GIF'ler**\n" + "\n".join(lines)
            embed = PAGEmbeds.custom(
                title="PAG Moderation GIF Paneli",
                description=description,
                color=discord.Colour.blurple(),
                thumbnail_url=str(guild.icon.url) if guild.icon else None,
            )
            await interaction.response.edit_message(embed=embed, view=ModerationGIFView(self))
            return

        if mode == "stats":
            stats = await self.service.get_statistics(guild.id)
            embed = PAGEmbeds.custom(title="PAG Moderation İstatistikleri", description="Sunucu genel moderasyon özeti.", color=discord.Colour.blue())
            for label, key in [
                ("Toplam Case", "total_cases"),
                ("Warn", "warn_cases"),
                ("Note", "note_cases"),
                ("Kick", "kick_cases"),
                ("Ban", "ban_cases"),
                ("Timeout", "timeout_cases"),
                ("Purge", "purge_cases"),
                ("Aktif Warn", "active_warnings"),
                ("Aktif Note", "active_notes"),
            ]:
                embed.add_field(name=label, value=str(stats[key]), inline=True)
            await interaction.response.edit_message(embed=embed, view=ModerationPanelView(self))
            return

        if mode == "history":
            cases = await self.service.list_cases(guild.id, limit=10)
            if not cases:
                await interaction.response.edit_message(embed=PAGEmbeds.info("Kayıt Yok", "Henüz moderasyon kaydı bulunmuyor."), view=ModerationPanelView(self))
                return
            lines = [f"**#{case.id}** • `{case.action_type}` • <@{case.user_id}> • {self._format_timestamp(case.created_at)}" for case in cases]
            embed = PAGEmbeds.custom(title="Son Moderasyon Kayıtları", description="\n".join(lines), color=discord.Colour.blurple())
            await interaction.response.edit_message(embed=embed, view=ModerationPanelView(self))
            return

        embed = PAGEmbeds.custom(
            title="PAG Moderation Komutları",
            description=(
                "**Çekirdek**\n"
                "`/warn` `/warnings` `/unwarn` `/clearwarnings`\n"
                "`/note` `/notes` `/removenote` `/clearnotes`\n\n"
                "**Üye İşlemleri**\n"
                "`/timeout` `/untimeout` `/kick` `/ban` `/unban` `/nickname`\n\n"
                "**Mesaj / Kanal**\n"
                "`/purge` `/lock` `/unlock` `/slowmode`\n\n"
                "**Yönetim**\n"
                "`/modpanel` `/modgif` `/history` `/stats` `/searchuser` `/caseinfo` `/editreason`"
            ),
            color=discord.Colour.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=ModerationPanelView(self))

    async def _resolve_member_safe(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        if self.discord_service is not None:
            try:
                return await self.discord_service.get_member(guild, user_id)
            except Exception:
                return None
        try:
            return await guild.fetch_member(user_id)
        except Exception:
            return None

    # ----------------------------- panel commands -----------------------------

    @commands.hybrid_command(name="modpanel", description="Open the main moderation panel.")
    async def modpanel(self, ctx: commands.Context) -> None:
        await self._maybe_defer(ctx)
        assert isinstance(ctx.author, discord.Member)
        self._require_admin_member(ctx.author)
        embed = PAGEmbeds.custom(
            title="PAG Moderation Panel",
            description=(
                "Merkezi moderasyon paneli.\n"
                "Buradan GIF ayarlarını yönetebilir, istatistikleri görebilir ve son kayıtları inceleyebilirsin."
            ),
            color=discord.Colour.blurple(),
        )
        await ctx.send(embed=embed, view=ModerationPanelView(self))

    @commands.hybrid_command(name="modgif", description="Open the GIF settings panel.")
    async def modgif(self, ctx: commands.Context) -> None:
        await self._maybe_defer(ctx)
        assert isinstance(ctx.author, discord.Member)
        self._require_admin_member(ctx.author)
        gifs = await self.service.list_gifs(ctx.guild.id)
        description = "Moderasyon GIF'lerini buradan ayarlayabilirsin. Bir butona bas, URL'yi yapıştır ve kaydet."
        if gifs:
            lines = []
            for gif in gifs:
                lines.append(f"• **{ACTION_LABELS.get(gif.action_key, gif.action_key.title())}** → {gif.url}")
            description += "\n\n**Mevcut GIF'ler**\n" + "\n".join(lines)
        embed = PAGEmbeds.custom(
            title="PAG Moderation GIF Paneli",
            description=description,
            color=discord.Colour.blurple(),
            thumbnail_url=str(ctx.guild.icon.url) if ctx.guild.icon else None,
        )
        await ctx.send(embed=embed, view=ModerationGIFView(self))

    # ----------------------------- warnings / notes -----------------------------

    @commands.hybrid_command(name="warn", description="Warn a member.")
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        result = await self.service.create_warning(ctx.guild.id, member.id, ctx.author.id, reason, details={"source": "command"})
        active_count = len(await self.service.list_warnings(ctx.guild.id, user_id=member.id, active_only=True))
        await self._send_action(
            ctx,
            action_key="warn",
            title="Üye Uyarıldı",
            target=member,
            moderator=ctx.author,
            reason=reason,
            case_id=result.case.id if result.case else None,
            extra_fields=[("Aktif Warn", str(active_count), True)],
        )

    @commands.hybrid_command(name="warnings", description="Show a member's warnings.")
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._maybe_defer(ctx)
        warnings = await self.service.list_warnings(ctx.guild.id, user_id=member.id)
        if not warnings:
            await ctx.send(embed=PAGEmbeds.info("Uyarı Yok", f"{member.mention} için kayıtlı uyarı yok."))
            return

        pages: list[discord.Embed] = []
        for chunk_index, start in enumerate(range(0, len(warnings), PAGE_SIZE), start=1):
            chunk = warnings[start:start + PAGE_SIZE]
            embed = PAGEmbeds.custom(
                title=f"{member.display_name} • Warnings",
                description=f"Toplam kayıt: **{len(warnings)}**",
                color=discord.Colour.orange(),
                thumbnail_url=str(member.display_avatar.url),
            )
            for warning in chunk:
                value = [
                    f"**ID:** #{warning.id}",
                    f"**Case:** #{warning.case_id}",
                    f"**Sebep:** {warning.reason}",
                    f"**Moderatör:** <@{warning.moderator_id}>",
                    f"**Tarih:** {self._format_timestamp(warning.created_at)}",
                    f"**Durum:** {'Active' if warning.active else 'Inactive'}",
                ]
                if warning.expires_at:
                    value.append(f"**Bitiş:** {self._format_timestamp(warning.expires_at)}")
                embed.add_field(name=f"Warning #{warning.id}", value="\n".join(value), inline=False)
            embed.set_footer(text=f"Sayfa {chunk_index}/{((len(warnings) - 1) // PAGE_SIZE) + 1}")
            pages.append(embed)
        await self._send_pages(ctx, pages)

    @commands.hybrid_command(name="unwarn", description="Remove a warning by warning ID.")
    async def unwarn(self, ctx: commands.Context, warning_id: int, *, reason: str | None = None) -> None:
        warning = await self.service.get_warning(ctx.guild.id, warning_id)
        if warning is None:
            raise ModerationNotFoundError(f"Warning not found: {warning_id}")
        result = await self.service.remove_warning(ctx.guild.id, warning_id, ctx.author.id, reason=reason)
        target = await self._resolve_member_safe(ctx.guild, warning.user_id) or UserProxy(warning.user_id, f"<@{warning.user_id}>")
        await self._send_action(
            ctx,
            action_key="untimeout",
            title="Warning Kaldırıldı",
            target=target,
            moderator=ctx.author,
            reason=reason or f"Removed warning #{warning_id}",
            case_id=result.case.id if result.case else warning.case_id,
            extra_fields=[("Warning ID", f"#{warning_id}", True)],
        )

    @commands.hybrid_command(name="clearwarnings", description="Clear all active warnings from a member.")
    async def clearwarnings(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        self._require_target_guard(ctx, member)
        result = await self.service.clear_warnings(ctx.guild.id, member.id, ctx.author.id, reason=reason)
        await self._send_action(
            ctx,
            action_key="warn",
            title="Uyarılar Temizlendi",
            target=member,
            moderator=ctx.author,
            reason=reason or "All warnings cleared.",
            case_id=result.case.id if result.case else None,
            extra_fields=[("Silinen", str(result.data.get("cleared", 0) if result.data else 0), True)],
        )

    @commands.hybrid_command(name="note", description="Add a private moderation note.")
    async def note(self, ctx: commands.Context, member: discord.Member, *, note: str) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        result = await self.service.add_note(ctx.guild.id, member.id, ctx.author.id, note, details={"source": "command"})
        await self._send_action(
            ctx,
            action_key="note",
            title="Not Eklendi",
            target=member,
            moderator=ctx.author,
            reason=note,
            case_id=result.case.id if result.case else None,
            extra_fields=[("Note ID", f"#{result.note.id if result.note else '?'}", True)],
        )

    @commands.hybrid_command(name="notes", description="Show a member's moderation notes.")
    async def notes(self, ctx: commands.Context, member: discord.Member) -> None:
        await self._maybe_defer(ctx)
        notes = await self.service.list_notes(ctx.guild.id, user_id=member.id)
        if not notes:
            await ctx.send(embed=PAGEmbeds.info("Not Yok", f"{member.mention} için kayıtlı not yok."))
            return

        pages: list[discord.Embed] = []
        for chunk_index, start in enumerate(range(0, len(notes), PAGE_SIZE), start=1):
            chunk = notes[start:start + PAGE_SIZE]
            embed = PAGEmbeds.custom(
                title=f"{member.display_name} • Notes",
                description=f"Toplam kayıt: **{len(notes)}**",
                color=discord.Colour.blurple(),
                thumbnail_url=str(member.display_avatar.url),
            )
            for note in chunk:
                value = [
                    f"**ID:** #{note.id}",
                    f"**Case:** #{note.case_id}",
                    f"**Not:** {note.note}",
                    f"**Moderatör:** <@{note.moderator_id}>",
                    f"**Tarih:** {self._format_timestamp(note.created_at)}",
                    f"**Durum:** {'Active' if note.active else 'Inactive'}",
                ]
                embed.add_field(name=f"Note #{note.id}", value="\n".join(value), inline=False)
            embed.set_footer(text=f"Sayfa {chunk_index}/{((len(notes) - 1) // PAGE_SIZE) + 1}")
            pages.append(embed)
        await self._send_pages(ctx, pages)

    @commands.hybrid_command(name="removenote", description="Remove a note by note ID.")
    async def removenote(self, ctx: commands.Context, note_id: int, *, reason: str | None = None) -> None:
        note = await self.service.get_note(ctx.guild.id, note_id)
        if note is None:
            raise ModerationNotFoundError(f"Note not found: {note_id}")
        result = await self.service.remove_note(ctx.guild.id, note_id, ctx.author.id, reason=reason)
        target = await self._resolve_member_safe(ctx.guild, note.user_id) or UserProxy(note.user_id, f"<@{note.user_id}>")
        await self._send_action(
            ctx,
            action_key="note",
            title="Not Kaldırıldı",
            target=target,
            moderator=ctx.author,
            reason=reason or f"Removed note #{note_id}",
            case_id=result.case.id if result.case else note.case_id,
            extra_fields=[("Note ID", f"#{note_id}", True)],
        )

    @commands.hybrid_command(name="clearnotes", description="Clear all active notes from a member.")
    async def clearnotes(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        self._require_target_guard(ctx, member)
        result = await self.service.clear_notes(ctx.guild.id, member.id, ctx.author.id, reason=reason)
        await self._send_action(
            ctx,
            action_key="note",
            title="Notlar Temizlendi",
            target=member,
            moderator=ctx.author,
            reason=reason or "All notes cleared.",
            case_id=result.case.id if result.case else None,
            extra_fields=[("Silinen", str(result.data.get("cleared", 0) if result.data else 0), True)],
        )

    # ----------------------------- user actions -----------------------------

    @commands.hybrid_command(name="timeout", description="Timeout a member.")
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration: str, *, reason: str) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        parsed = self._parse_duration(duration)
        until = discord.utils.utcnow() + timedelta(seconds=parsed.seconds)
        await self._apply_timeout(member, until, reason)
        case = await self.service.record_case(
            ctx.guild.id,
            member.id,
            ctx.author.id,
            "timeout",
            reason=reason,
            details={"duration": parsed.text, "until": until.isoformat()},
        )
        await self._send_action(
            ctx,
            action_key="timeout",
            title="Üye Timeout Aldı",
            target=member,
            moderator=ctx.author,
            reason=reason,
            case_id=case.id,
            extra_fields=[("Süre", self._format_duration(parsed.seconds), True), ("Bitiş", self._format_timestamp(until.isoformat()), True)],
        )

    @commands.hybrid_command(name="untimeout", description="Remove timeout from a member.")
    async def untimeout(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        await self._apply_timeout(member, None, reason)
        case = await self.service.record_case(
            ctx.guild.id,
            member.id,
            ctx.author.id,
            "untimeout",
            reason=reason or "Timeout removed.",
            details={"timeout_removed": True},
        )
        await self._send_action(
            ctx,
            action_key="untimeout",
            title="Timeout Kaldırıldı",
            target=member,
            moderator=ctx.author,
            reason=reason or "Timeout removed.",
            case_id=case.id,
        )

    @commands.hybrid_command(name="kick", description="Kick a member.")
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        await member.kick(reason=reason)
        case = await self.service.record_case(ctx.guild.id, member.id, ctx.author.id, "kick", reason=reason, details={"source": "command"})
        await self._send_action(ctx, action_key="kick", title="Üye Atıldı", target=member, moderator=ctx.author, reason=reason, case_id=case.id)

    @commands.hybrid_command(name="ban", description="Ban a member.")
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        await ctx.guild.ban(member, reason=reason)
        case = await self.service.record_case(ctx.guild.id, member.id, ctx.author.id, "ban", reason=reason, details={"source": "command"})
        await self._send_action(ctx, action_key="ban", title="Üye Banlandı", target=member, moderator=ctx.author, reason=reason, case_id=case.id)

    @commands.hybrid_command(name="unban", description="Unban a user by Discord user converter.")
    async def unban(self, ctx: commands.Context, user: discord.User, *, reason: str | None = None) -> None:
        await self._maybe_defer(ctx)
        await ctx.guild.unban(user, reason=reason)
        case = await self.service.record_case(ctx.guild.id, user.id, ctx.author.id, "unban", reason=reason or "User unbanned.", details={"source": "command"})
        await self._send_action(ctx, action_key="unban", title="Ban Kaldırıldı", target=user, moderator=ctx.author, reason=reason or "User unbanned.", case_id=case.id)

    @commands.hybrid_command(name="nickname", description="Change or clear a member nickname.")
    async def nickname(self, ctx: commands.Context, member: discord.Member, *, nickname: str | None = None) -> None:
        await self._maybe_defer(ctx)
        self._require_target_guard(ctx, member)
        old_nick = member.nick
        new_nick = None if nickname is None or nickname.strip().lower() in {"clear", "none", "-"} else nickname.strip()
        await member.edit(nick=new_nick, reason=f"Nickname change by {ctx.author}")
        case = await self.service.record_case(ctx.guild.id, member.id, ctx.author.id, "nickname", reason=new_nick or "Nickname cleared.", details={"old": old_nick, "new": new_nick})
        await self._send_action(
            ctx,
            action_key="nickname",
            title="Nickname Güncellendi",
            target=member,
            moderator=ctx.author,
            reason=new_nick or "Nickname cleared.",
            case_id=case.id,
            extra_fields=[("Eski", old_nick or "Yok", True), ("Yeni", new_nick or "Temizlendi", True)],
        )

    # ----------------------------- message / channel -----------------------------

    @commands.hybrid_command(name="purge", description="Delete recent messages with optional filters.")
    async def purge(
        self,
        ctx: commands.Context,
        limit: int = 50,
        member: discord.Member | None = None,
        contains: str | None = None,
        bots: bool = False,
        attachments: bool = False,
        links: bool = False,
        webhooks: bool = False,
    ) -> None:
        await self._maybe_defer(ctx)
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            raise ModerationValidationError("Purge can only be used in text channels or threads.")
        if limit <= 0:
            raise ModerationValidationError("Limit must be greater than zero.")
        limit = min(limit, MAX_PURGE_LIMIT)

        filters: list[str] = []
        if member is not None:
            self._require_target_guard(ctx, member)
            filters.append(f"user={member.id}")
        if contains:
            filters.append(f"contains={contains}")
        if bots:
            filters.append("bots")
        if attachments:
            filters.append("attachments")
        if links:
            filters.append("links")
        if webhooks:
            filters.append("webhooks")

        lowered_contains = contains.lower() if contains else None

        def predicate(message: discord.Message) -> bool:
            if member is not None and message.author.id != member.id:
                return False
            if lowered_contains is not None and lowered_contains not in message.content.lower():
                return False
            if bots and not message.author.bot:
                return False
            if attachments and not message.attachments:
                return False
            if links and "http://" not in message.content and "https://" not in message.content:
                return False
            if webhooks and message.webhook_id is None:
                return False
            return True

        deleted = await ctx.channel.purge(
            limit=limit,
            check=predicate,
            bulk=True,
            reason=f"Purge by {ctx.author} ({ctx.author.id})",
        )
        case = await self.service.record_case(
            ctx.guild.id,
            ctx.author.id,
            ctx.author.id,
            "purge",
            reason=f"Purged {len(deleted)} messages.",
            details={"channel_id": ctx.channel.id, "deleted": len(deleted), "limit": limit, "filters": filters},
        )
        await self._send_action(
            ctx,
            action_key="purge",
            title="Mesajlar Temizlendi",
            target=ctx.author,
            moderator=ctx.author,
            reason=f"Purged {len(deleted)} messages.",
            case_id=case.id,
            extra_fields=[("Silinen Mesaj", str(len(deleted)), True), ("Filtre", ", ".join(filters) if filters else "recent", True)],
        )

    @commands.hybrid_command(name="lock", description="Lock a text channel.")
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, reason: str | None = None) -> None:
        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            raise ModerationValidationError("Lock can only be used on text channels.")

        overwrite = target_channel.overwrites_for(target_channel.guild.default_role)
        overwrite.send_messages = False
        await target_channel.set_permissions(target_channel.guild.default_role, overwrite=overwrite, reason=reason)

        case = await self.service.record_case(ctx.guild.id, ctx.author.id, ctx.author.id, "lock", reason=reason or f"Locked {target_channel.name}", details={"channel_id": target_channel.id})
        await self._send_action(
            ctx,
            action_key="lock",
            title="Kanal Kilitlendi",
            target=target_channel,
            moderator=ctx.author,
            reason=reason or "Channel locked.",
            case_id=case.id,
            extra_fields=[("Kanal", target_channel.mention, False)],
        )

    @commands.hybrid_command(name="unlock", description="Unlock a text channel.")
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, reason: str | None = None) -> None:
        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            raise ModerationValidationError("Unlock can only be used on text channels.")

        overwrite = target_channel.overwrites_for(target_channel.guild.default_role)
        overwrite.send_messages = None
        await target_channel.set_permissions(target_channel.guild.default_role, overwrite=overwrite, reason=reason)

        case = await self.service.record_case(ctx.guild.id, ctx.author.id, ctx.author.id, "unlock", reason=reason or f"Unlocked {target_channel.name}", details={"channel_id": target_channel.id})
        await self._send_action(
            ctx,
            action_key="unlock",
            title="Kanal Açıldı",
            target=target_channel,
            moderator=ctx.author,
            reason=reason or "Channel unlocked.",
            case_id=case.id,
            extra_fields=[("Kanal", target_channel.mention, False)],
        )

    @commands.hybrid_command(name="slowmode", description="Set slowmode for a text channel.")
    async def slowmode(self, ctx: commands.Context, seconds: int, channel: discord.TextChannel | None = None, *, reason: str | None = None) -> None:
        target_channel = channel or ctx.channel
        if not isinstance(target_channel, discord.TextChannel):
            raise ModerationValidationError("Slowmode can only be used on text channels.")
        if seconds < 0:
            raise ModerationValidationError("Slowmode cannot be negative.")
        if seconds > 21600:
            raise ModerationValidationError("Slowmode cannot exceed 6 hours.")

        await target_channel.edit(slowmode_delay=seconds, reason=reason)
        case = await self.service.record_case(ctx.guild.id, ctx.author.id, ctx.author.id, "slowmode", reason=reason or f"Set slowmode to {seconds}s", details={"channel_id": target_channel.id, "seconds": seconds})
        await self._send_action(
            ctx,
            action_key="slowmode",
            title="Slowmode Ayarlandı",
            target=target_channel,
            moderator=ctx.author,
            reason=reason or "Slowmode updated.",
            case_id=case.id,
            extra_fields=[("Kanal", target_channel.mention, False), ("Süre", self._format_duration(seconds), True)],
        )

    # ----------------------------- stats / history / search -----------------------------

    @commands.hybrid_command(name="history", description="Show moderation history for a member or the guild.")
    async def history(self, ctx: commands.Context, member: discord.Member | None = None, limit: int = 15) -> None:
        await self._maybe_defer(ctx)
        if limit <= 0:
            raise ModerationValidationError("Limit must be greater than zero.")
        limit = min(limit, 50)
        cases = await self.service.list_cases(ctx.guild.id, user_id=member.id if member else None, limit=limit)
        if not cases:
            target = member.mention if member else "sunucu"
            await ctx.send(embed=PAGEmbeds.info("Kayıt Yok", f"{target} için moderasyon kaydı bulunamadı."))
            return

        pages: list[discord.Embed] = []
        for page_index, start in enumerate(range(0, len(cases), HISTORY_PAGE_SIZE), start=1):
            chunk = cases[start:start + HISTORY_PAGE_SIZE]
            description = f"**Hedef:** {member.mention if member else 'Sunucu geneli'}\n**Kayıt:** {len(cases)}"
            embed = PAGEmbeds.custom(
                title="Moderasyon Geçmişi",
                description=description,
                color=discord.Colour.blurple(),
                thumbnail_url=str(member.display_avatar.url) if member else (str(ctx.guild.icon.url) if ctx.guild.icon else None),
            )
            for case in chunk:
                value = [
                    f"**Case:** #{case.id}",
                    f"**İşlem:** `{case.action_type}`",
                    f"**Sebep:** {case.reason or 'Belirtilmedi'}",
                    f"**Moderatör:** <@{case.moderator_id}>",
                    f"**Tarih:** {self._format_timestamp(case.created_at)}",
                ]
                if case.details:
                    value.append(f"**Detay:** `{case.details}`")
                embed.add_field(name=f"#{case.id}", value="\n".join(value), inline=False)
            embed.set_footer(text=f"Sayfa {page_index}/{((len(cases) - 1) // HISTORY_PAGE_SIZE) + 1}")
            pages.append(embed)
        await self._send_pages(ctx, pages)

    @commands.hybrid_command(name="stats", description="Show moderation statistics.")
    async def stats(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._maybe_defer(ctx)
        stats = await self.service.get_statistics(ctx.guild.id, user_id=member.id if member else None)
        embed = PAGEmbeds.custom(
            title="Moderasyon İstatistikleri",
            description=member.mention if member else "Sunucu geneli özet.",
            color=discord.Colour.blurple(),
            thumbnail_url=str(member.display_avatar.url) if member else (str(ctx.guild.icon.url) if ctx.guild.icon else None),
        )
        for label, key in [
            ("Toplam Case", "total_cases"),
            ("Warn", "warn_cases"),
            ("Note", "note_cases"),
            ("Kick", "kick_cases"),
            ("Ban", "ban_cases"),
            ("Timeout", "timeout_cases"),
            ("Purge", "purge_cases"),
            ("Aktif Warn", "active_warnings"),
            ("Aktif Note", "active_notes"),
        ]:
            embed.add_field(name=label, value=str(stats[key]), inline=True)
        embed.set_footer(text="PAG Moderation")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="searchuser", description="Search users in moderation records.")
    async def searchuser(self, ctx: commands.Context, *, query: str) -> None:
        await self._maybe_defer(ctx)
        results = await self.service.search_users(ctx.guild.id, query, limit=10)
        if not results:
            await ctx.send(embed=PAGEmbeds.info("Sonuç Yok", "Aranan kullanıcı bulunamadı."))
            return

        pages: list[discord.Embed] = []
        for page_index, start in enumerate(range(0, len(results), PAGE_SIZE), start=1):
            chunk = results[start:start + PAGE_SIZE]
            embed = PAGEmbeds.custom(title="Kullanıcı Arama Sonuçları", description=f"Arama: `{query}`", color=discord.Colour.blurple())
            for item in chunk:
                member = ctx.guild.get_member(item.user_id)
                label = member.mention if member else f"`{item.user_id}`"
                value = [
                    f"**Case:** {item.case_count}",
                    f"**Warn:** {item.warning_count}",
                    f"**Note:** {item.note_count}",
                    f"**Son İşlem:** {self._format_timestamp(item.last_action_at)}",
                ]
                embed.add_field(name=label, value="\n".join(value), inline=False)
            embed.set_footer(text=f"Sayfa {page_index}/{((len(results) - 1) // PAGE_SIZE) + 1}")
            pages.append(embed)
        await self._send_pages(ctx, pages)

    @commands.hybrid_command(name="caseinfo", description="Show a specific moderation case.")
    async def caseinfo(self, ctx: commands.Context, case_id: int) -> None:
        await self._maybe_defer(ctx)
        case = await self.service.get_case(case_id)
        if case is None or case.guild_id != ctx.guild.id:
            raise ModerationNotFoundError(f"Case not found: {case_id}")
        gif = await self.service.get_gif(ctx.guild.id, case.action_type)
        target = ctx.guild.get_member(case.user_id) or UserProxy(case.user_id, f"<@{case.user_id}>")
        moderator = ctx.guild.get_member(case.moderator_id) or UserProxy(case.moderator_id, f"<@{case.moderator_id}>")
        embed = self._build_action_embed(
            title=f"Case #{case.id}",
            action_key=case.action_type,
            target=target,
            moderator=moderator,
            reason=case.reason,
            case_id=case.id,
            gif_url=gif.url if gif else None,
            extra_fields=[
                ("İşlem", case.action_type, True),
                ("Aktif", "Evet" if case.active else "Hayır", True),
                ("Tarih", self._format_timestamp(case.created_at), False),
            ],
        )
        if case.details:
            embed.add_field(name="Detay", value=f"`{case.details}`", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="editreason", description="Edit the reason of a case.")
    async def editreason(self, ctx: commands.Context, case_id: int, *, reason: str) -> None:
        await self._maybe_defer(ctx)
        case = await self.service.get_case(case_id)
        if case is None or case.guild_id != ctx.guild.id:
            raise ModerationNotFoundError(f"Case not found: {case_id}")
        updated = await self.service.edit_case_reason(case_id, reason)
        await self._send_action(
            ctx,
            action_key=updated.action_type,
            title="Case Sebebi Güncellendi",
            target=ctx.guild.get_member(updated.user_id) or UserProxy(updated.user_id, f"<@{updated.user_id}>"),
            moderator=ctx.author,
            reason=reason,
            case_id=updated.id,
            extra_fields=[("Eski İşlem", updated.action_type, True)],
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
