# cogs/invite.py

from __future__ import annotations

import logging

import discord
from discord.ext import commands

log = logging.getLogger("pag_bot.invite")

AUTHORIZED_USERNAME = "velgrath_"


class Invite(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================================================
    # AUTHORIZATION
    # =========================================================

    @staticmethod
    def is_authorized(user: discord.abc.User) -> bool:
        return (
            getattr(user, "name", "").lower()
            == AUTHORIZED_USERNAME.lower()
        )

    # =========================================================
    # FIND CHANNEL
    # =========================================================

    @staticmethod
    def find_channel(
        guild: discord.Guild,
    ) -> discord.TextChannel | None:

        me = guild.me

        if me is None:
            return None

        # Önce sistem kanalını dene.
        if guild.system_channel is not None:

            channel = guild.system_channel
            permissions = channel.permissions_for(me)

            if (
                permissions.view_channel
                and permissions.create_instant_invite
            ):
                return channel

        # Sonra diğer text kanallarını kontrol et.
        for channel in guild.text_channels:

            permissions = channel.permissions_for(me)

            if (
                permissions.view_channel
                and permissions.create_instant_invite
            ):
                return channel

        return None

    # =========================================================
    # !INVITE
    # =========================================================

    @commands.command(
        name="invite",
        aliases=(
            "serverinvite",
            "guildinvite",
        ),
    )
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user,
    )
    async def invite(
        self,
        ctx: commands.Context,
        guild_id: int | None = None,
    ):
        # -----------------------------------------------------
        # OWNER CHECK
        # -----------------------------------------------------

        if not self.is_authorized(ctx.author):
            await ctx.reply(
                "❌ Bu komutu kullanma yetkiniz yok.",
                mention_author=False,
            )
            return

        # -----------------------------------------------------
        # GUILD ID
        # -----------------------------------------------------

        if guild_id is None:
            await ctx.reply(
                "❌ Kullanım:\n"
                "`!invite <guild_id>`",
                mention_author=False,
            )
            return

        # -----------------------------------------------------
        # GET GUILD
        # -----------------------------------------------------

        guild = self.bot.get_guild(guild_id)

        if guild is None:
            await ctx.reply(
                "❌ Bot bu sunucuda bulunmuyor.",
                mention_author=False,
            )
            return

        # -----------------------------------------------------
        # FIND CHANNEL
        # -----------------------------------------------------

        channel = self.find_channel(guild)

        if channel is None:
            await ctx.reply(
                "❌ Bu sunucuda davet oluşturabileceğim "
                "uygun bir kanal bulunamadı.",
                mention_author=False,
            )
            return

        # -----------------------------------------------------
        # CREATE INVITE
        # -----------------------------------------------------

        try:
            invite = await channel.create_invite(
                max_age=86400,       # 24 saat
                max_uses=0,          # Sınırsız kullanım
                unique=True,
                reason=(
                    f"PAG Bot invite request | "
                    f"{ctx.author} ({ctx.author.id})"
                ),
            )

        except discord.Forbidden:
            await ctx.reply(
                "❌ Discord davet oluşturma işlemini reddetti.\n"
                f"📌 Kanal: {channel.mention}",
                mention_author=False,
            )
            return

        except discord.HTTPException as exc:
            log.error(
                "Invite oluşturulamadı | "
                "guild=%s | channel=%s | error=%s",
                guild.id,
                channel.id,
                exc,
            )

            await ctx.reply(
                "❌ Discord API davet oluştururken hata verdi.",
                mention_author=False,
            )
            return

        # -----------------------------------------------------
        # RESULT
        # -----------------------------------------------------

        embed = discord.Embed(
            title="🔗 SERVER INVITE",
            description=(
                f"**{guild.name}** için davet oluşturuldu."
            ),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🔗 Invite",
            value=f"`{invite.url}`",
            inline=False,
        )

        embed.add_field(
            name="🆔 Guild ID",
            value=f"`{guild.id}`",
            inline=True,
        )

        embed.add_field(
            name="📌 Channel",
            value=channel.mention,
            inline=True,
        )

        embed.add_field(
            name="⏳ Validity",
            value="24 saat",
            inline=True,
        )

        if guild.icon:
            embed.set_thumbnail(
                url=guild.icon.url
            )

        embed.set_footer(
            text="PAG Bot • Invite System"
        )

        await ctx.reply(
            embed=embed,
            mention_author=False,
        )

    # =========================================================
    # ERROR HANDLER
    # =========================================================

    @invite.error
    async def invite_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        if isinstance(
            error,
            commands.BadArgument,
        ):
            await ctx.reply(
                "❌ Geçersiz Guild ID.\n"
                "Örnek:\n"
                "`!invite 123456789012345678`",
                mention_author=False,
            )
            return

        if isinstance(
            error,
            commands.CommandOnCooldown,
        ):
            await ctx.reply(
                f"⏳ Çok hızlı kullanıyorsunuz. "
                f"`{error.retry_after:.1f}s` bekleyin.",
                mention_author=False,
            )
            return

        log.exception(
            "Invite command error",
            exc_info=error,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Invite(bot)
    )