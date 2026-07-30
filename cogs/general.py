from __future__ import annotations

import logging
import random
from typing import Any

import discord
from discord.ext import commands

from services.event_service import EventService
from utils.embeds import PAGEmbeds


class General(commands.Cog):
    """
    PAG genel kullanıcı ve sunucu komutları.

    Prefix komutları:
        !profile
        !events
        !userinfo
        !stats
        !random
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        event_service: EventService,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.event_service = event_service
        self.logger = logger

    # ========================================================
    # HELPERS
    # ========================================================

    def _format_roles(
        self,
        member: discord.Member,
        *,
        limit: int = 15,
    ) -> str:
        roles = [
            role.mention
            for role in member.roles
            if role != member.guild.default_role
        ]

        if not roles:
            return "Rol yok"

        if len(roles) > limit:
            return " ".join(roles[:limit]) + f" ... (+{len(roles) - limit})"

        return " ".join(roles)

    def _build_profile_embed(
        self,
        member: discord.Member,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"👤 {member.display_name}'s Profile",
            description="PAG member profile",
            timestamp=discord.utils.utcnow(),
        )

        embed.set_author(
            name=member.display_name,
            icon_url=member.display_avatar.url,
        )

        embed.add_field(
            name="Discord",
            value=f"{member.mention}\n`{member.id}`",
            inline=True,
        )

        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(
                member.created_at,
                style="R",
            ),
            inline=True,
        )

        embed.add_field(
            name="Roles",
            value=f"`{len(member.roles) - 1}`",
            inline=True,
        )

        embed.set_thumbnail(
            url=member.display_avatar.url,
        )

        return embed

    def _build_events_embed(
        self,
        events: list[Any],
    ) -> discord.Embed:
        embed = discord.Embed(
            title="📅 PAG Active Events",
            description="Şu anda aktif olan eventler:",
            timestamp=discord.utils.utcnow(),
        )

        for event in events[:10]:
            event_name = getattr(
                event,
                "name",
                "Unknown Event",
            )

            event_description = getattr(
                event,
                "description",
                "Açıklama bulunmuyor.",
            )

            event_id = getattr(
                event,
                "id",
                0,
            )

            embed.add_field(
                name=f"📌 {event_name}",
                value=(
                    f"{str(event_description)[:500]}\n"
                    f"ID: `{event_id}`"
                ),
                inline=False,
            )

        return embed

    def _build_userinfo_embed(
        self,
        member: discord.Member,
    ) -> discord.Embed:
        roles_text = self._format_roles(member)

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            timestamp=discord.utils.utcnow(),
        )

        embed.set_thumbnail(
            url=member.display_avatar.url,
        )

        embed.add_field(
            name="User ID",
            value=f"`{member.id}`",
            inline=True,
        )

        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(
                member.created_at,
                style="R",
            ),
            inline=True,
        )

        embed.add_field(
            name="Joined Server",
            value=(
                discord.utils.format_dt(
                    member.joined_at,
                    style="R",
                )
                if member.joined_at
                else "Unknown"
            ),
            inline=True,
        )

        embed.add_field(
            name="Roles",
            value=roles_text[:1024],
            inline=False,
        )

        return embed

    def _build_stats_embed(
        self,
        guild: discord.Guild,
        *,
        active_events: int,
        total_events: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="📊 PAG Statistics",
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="👥 Members",
            value=f"`{guild.member_count or 0}`",
            inline=True,
        )

        embed.add_field(
            name="📅 Active Events",
            value=f"`{active_events}`",
            inline=True,
        )

        embed.add_field(
            name="🏆 Total Events",
            value=f"`{total_events}`",
            inline=True,
        )

        if guild.icon:
            embed.set_thumbnail(
                url=guild.icon.url,
            )

        return embed

    def _build_random_embed(
        self,
        selected: discord.Member,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 PAG Random Selection",
            description=(
                "🎉 Seçilen üye:\n\n"
                f"## {selected.mention}"
            ),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_thumbnail(
            url=selected.display_avatar.url,
        )

        return embed

    async def _safe_send(
        self,
        ctx: commands.Context,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> None:
        try:
            await ctx.send(
                content=content,
                embed=embed,
            )
        except discord.Forbidden:
            self.logger.exception(
                "Missing permission to send message in guild=%s channel=%s",
                ctx.guild.id if ctx.guild else None,
                ctx.channel.id if ctx.channel else None,
            )
        except discord.HTTPException:
            self.logger.exception(
                "Failed to send message.",
            )

    async def _load_active_events(
        self,
    ) -> list[Any]:
        events = await self.event_service.list_events(
            status="active",
        )
        return list(events)

    async def _load_all_events(
        self,
    ) -> list[Any]:
        events = await self.event_service.list_events()
        return list(events)

    # ========================================================
    # PROFILE
    # ========================================================

    @commands.command(
        name="profile",
        help="Kendi Discord profilini gösterir.",
    )
    @commands.guild_only()
    async def profile(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        Kullanıcının Discord profilini gösterir.
        """

        member = ctx.author

        if not isinstance(member, discord.Member):
            await self._safe_send(
                ctx,
                content="❌ Üye bilgisi alınamadı.",
            )
            return

        await self._safe_send(
            ctx,
            embed=self._build_profile_embed(member),
        )

    # ========================================================
    # EVENTS
    # ========================================================

    @commands.command(
        name="events",
        help="Aktif PAG eventlerini gösterir.",
    )
    @commands.guild_only()
    async def events(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        Aktif eventleri listeler.
        """

        try:
            events = await self._load_active_events()
        except Exception:
            self.logger.exception(
                "Failed to load active events.",
            )
            await self._safe_send(
                ctx,
                embed=PAGEmbeds.error(
                    "Eventler yüklenirken bir hata oluştu.",
                ),
            )
            return

        if not events:
            await self._safe_send(
                ctx,
                embed=PAGEmbeds.info(
                    "Şu anda aktif bir event bulunmuyor.",
                ),
            )
            return

        await self._safe_send(
            ctx,
            embed=self._build_events_embed(events),
        )

    # ========================================================
    # USERINFO
    # ========================================================

    @commands.command(
        name="userinfo",
        help="Bir üyenin bilgilerini gösterir.",
    )
    @commands.guild_only()
    async def userinfo(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        """
        Discord üye bilgilerini gösterir.
        """

        if member is None:
            member = ctx.author if isinstance(ctx.author, discord.Member) else None

        if member is None:
            await self._safe_send(
                ctx,
                content="❌ Üye bilgisi alınamadı.",
            )
            return

        await self._safe_send(
            ctx,
            embed=self._build_userinfo_embed(member),
        )

    # ========================================================
    # STATS
    # ========================================================

    @commands.command(
        name="stats",
        help="PAG sunucu istatistiklerini gösterir.",
    )
    @commands.guild_only()
    async def stats(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        Sunucu istatistiklerini gösterir.
        """

        guild = ctx.guild

        if guild is None:
            await self._safe_send(
                ctx,
                embed=PAGEmbeds.error(
                    "Bu komut sadece sunucuda kullanılabilir.",
                ),
            )
            return

        active_events = 0
        total_events = 0

        try:
            active_events_data = await self._load_active_events()
            active_events = len(active_events_data)
        except Exception:
            self.logger.exception(
                "Failed to load active event stats.",
            )

        try:
            all_events = await self._load_all_events()
            total_events = len(all_events)
        except Exception:
            self.logger.exception(
                "Failed to load total event stats.",
            )

        await self._safe_send(
            ctx,
            embed=self._build_stats_embed(
                guild,
                active_events=active_events,
                total_events=total_events,
            ),
        )

    # ========================================================
    # RANDOM
    # ========================================================

    @commands.command(
        name="random",
        help="Sunucudan rastgele bir üye seçer.",
    )
    @commands.guild_only()
    async def random_member(
        self,
        ctx: commands.Context,
    ) -> None:
        """
        Sunucudan rastgele bir üye seçer.
        """

        guild = ctx.guild

        if guild is None:
            await self._safe_send(
                ctx,
                embed=PAGEmbeds.error(
                    "Bu komut sadece sunucuda kullanılabilir.",
                ),
            )
            return

        members = [
            member
            for member in guild.members
            if not member.bot
        ]

        if not members:
            await self._safe_send(
                ctx,
                embed=PAGEmbeds.error(
                    "Seçilebilecek üye bulunamadı.",
                ),
            )
            return

        selected = random.choice(members)

        await self._safe_send(
            ctx,
            embed=self._build_random_embed(selected),
        )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """
        Genel prefix command hata yöneticisi.
        """

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.CheckFailure):
            await self._safe_send(
                ctx,
                content="❌ Bu komutu yalnızca sunucuda kullanabilirsin.",
            )
            return

        self.logger.error(
            "General command error: %s",
            error,
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )

        await self._safe_send(
            ctx,
            content="❌ İşlem sırasında beklenmeyen bir hata oluştu.",
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        General(
            bot,
            event_service=bot.event_service,
            logger=bot.logger,
        ),
    )