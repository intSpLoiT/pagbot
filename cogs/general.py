from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from services.event_service import EventService
from utils.embeds import PAGEmbeds


class General(commands.Cog):
    """
    PAG genel kullanıcı ve sunucu komutları.

    Komutlar:
        /profile
        /events
        /userinfo
        /stats
        /random
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
    # PROFILE
    # ========================================================

    @app_commands.command(
        name="profile",
        description="PAG profilini görüntüler.",
    )
    @app_commands.guild_only()
    async def profile(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Kullanıcının Discord profilini gösterir.
        """

        await interaction.response.defer()

        member = interaction.user

        embed = discord.Embed(
            title=(
                f"👤 {member.display_name}'s Profile"
            ),
            description="PAG member profile",
            timestamp=discord.utils.utcnow(),
        )

        embed.set_author(
            name=member.display_name,
            icon_url=member.display_avatar.url,
        )

        embed.add_field(
            name="Discord",
            value=(
                f"{member.mention}\n"
                f"`{member.id}`"
            ),
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

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # EVENTS
    # ========================================================

    @app_commands.command(
        name="events",
        description="Aktif PAG eventlerini gösterir.",
    )
    @app_commands.guild_only()
    async def events(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Aktif eventleri listeler.
        """

        await interaction.response.defer()

        try:
            events = await self.event_service.list_events(
                status="active",
            )

        except Exception:
            self.logger.exception(
                "Failed to load active events.",
            )

            await interaction.followup.send(
                embed=PAGEmbeds.error(
                    "Eventler yüklenirken bir hata oluştu.",
                ),
            )

            return

        if not events:
            await interaction.followup.send(
                embed=PAGEmbeds.info(
                    "Şu anda aktif bir event bulunmuyor.",
                ),
            )

            return

        embed = discord.Embed(
            title="📅 PAG Active Events",
            description=(
                "Şu anda aktif olan eventler:"
            ),
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
                    f"{event_description[:500]}\n"
                    f"ID: `{event_id}`"
                ),
                inline=False,
            )

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # USERINFO
    # ========================================================

    @app_commands.command(
        name="userinfo",
        description="Bir üyenin bilgilerini gösterir.",
    )
    @app_commands.describe(
        member="Bilgileri görüntülenecek üye.",
    )
    @app_commands.guild_only()
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """
        Discord üye bilgilerini gösterir.
        """

        await interaction.response.defer()

        roles = [
            role.mention
            for role in member.roles
            if role != interaction.guild.default_role
        ]

        if roles:
            roles_text = " ".join(roles[:15])

        else:
            roles_text = "Rol yok"

        embed = discord.Embed(
            title=(
                f"👤 {member.display_name}"
            ),
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

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # STATS
    # ========================================================

    @app_commands.command(
        name="stats",
        description="PAG sunucu istatistiklerini gösterir.",
    )
    @app_commands.guild_only()
    async def stats(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Sunucu istatistiklerini gösterir.
        """

        await interaction.response.defer()

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
                embed=PAGEmbeds.error(
                    "Bu komut sadece sunucuda kullanılabilir.",
                ),
            )

            return

        active_events = 0
        total_events = 0

        try:
            active_events_data = (
                await self.event_service.list_events(
                    status="active",
                )
            )

            active_events = len(
                active_events_data,
            )

        except Exception:
            self.logger.exception(
                "Failed to load active event stats.",
            )

        try:
            all_events = (
                await self.event_service.list_events()
            )

            total_events = len(
                all_events,
            )

        except Exception:
            self.logger.exception(
                "Failed to load total event stats.",
            )

        embed = discord.Embed(
            title="📊 PAG Statistics",
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="👥 Members",
            value=(
                f"`{guild.member_count or 0}`"
            ),
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

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # RANDOM
    # ========================================================

    @app_commands.command(
        name="random",
        description="Sunucudan rastgele bir üye seçer.",
    )
    @app_commands.guild_only()
    async def random_member(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Sunucudan rastgele bir üye seçer.
        """

        await interaction.response.defer()

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
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
            await interaction.followup.send(
                embed=PAGEmbeds.error(
                    "Seçilebilecek üye bulunamadı.",
                ),
            )

            return

        selected = random.choice(
            members,
        )

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

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Genel slash command hata yöneticisi.
        """

        self.logger.error(
            "General command error: %s",
            error,
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )

        message = (
            "❌ İşlem sırasında beklenmeyen "
            "bir hata oluştu."
        )

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
        General(
            bot,
            event_service=bot.event_service,
            logger=bot.logger,
        )
    )