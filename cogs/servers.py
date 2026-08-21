# cogs/servers.py

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands


log = logging.getLogger("pag_bot.servers")


# ============================================================
# CONFIGURATION
# ============================================================

AUTHORIZED_USERNAME = "velgrath_"


# ============================================================
# PROTECTED GUILD LOADER
# ============================================================

def load_protected_guild_ids() -> set[int]:
    """
    .env / environment variables içerisinden korunan guild ID'lerini
    toplar.

    Desteklenen örnekler:

        GUILD_ID=123456789

        GUILD_IDS=123456789,987654321

        GUILD_ID=123456789
        GUILD_IDS=987654321,555555555

    Değişken isimleri case-insensitive kontrol edilir.
    """

    protected: set[int] = set()

    for key, value in os.environ.items():

        normalized_key = key.strip().upper()

        if normalized_key not in {
            "GUILD_ID",
            "GUILD_IDS",
        }:
            continue

        if not value:
            continue

        # Virgül
        # Noktalı virgül
        # Boşluk
        # Yeni satır
        #
        # gibi ayraçları destekle.

        raw_values = (
            value
            .replace(";", ",")
            .replace("\n", ",")
            .split(",")
        )

        for raw_id in raw_values:

            raw_id = raw_id.strip()

            if not raw_id:
                continue

            try:
                guild_id = int(raw_id)

            except ValueError:
                log.warning(
                    "Geçersiz guild ID bulundu: %r (%s)",
                    raw_id,
                    key,
                )
                continue

            protected.add(guild_id)

    return protected


# ============================================================
# PAGINATION VIEW
# ============================================================

class ServerListView(discord.ui.View):

    def __init__(
        self,
        author_id: int,
        pages: list[discord.Embed],
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)

        self.author_id = author_id
        self.pages = pages
        self.current_page = 0

        self._update_buttons()

    # --------------------------------------------------------
    # BUTTON STATE
    # --------------------------------------------------------

    def _update_buttons(self) -> None:

        self.previous_button.disabled = (
            self.current_page <= 0
        )

        self.next_button.disabled = (
            self.current_page >= len(self.pages) - 1
        )

    # --------------------------------------------------------
    # AUTHORIZATION
    # --------------------------------------------------------

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu paneli yalnızca komutu kullanan kişi "
                "kontrol edebilir.",
                ephemeral=True,
            )

            return False

        return True

    # --------------------------------------------------------
    # PREVIOUS
    # --------------------------------------------------------

    @discord.ui.button(
        label="◀",
        style=discord.ButtonStyle.secondary,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if self.current_page > 0:
            self.current_page -= 1

        self._update_buttons()

        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self,
        )

    # --------------------------------------------------------
    # NEXT
    # --------------------------------------------------------

    @discord.ui.button(
        label="▶",
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if self.current_page < len(self.pages) - 1:
            self.current_page += 1

        self._update_buttons()

        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self,
        )

    # --------------------------------------------------------
    # PAGE INDICATOR
    # --------------------------------------------------------

    @discord.ui.button(
        label="Page",
        style=discord.ButtonStyle.primary,
        disabled=True,
    )
    async def page_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        pass

    # --------------------------------------------------------
    # TIMEOUT
    # --------------------------------------------------------

    async def on_timeout(self) -> None:

        for child in self.children:

            if isinstance(child, discord.ui.Button):
                child.disabled = True


# ============================================================
# SERVERS COG
# ============================================================

class Servers(commands.Cog):

    def __init__(self, bot: commands.Bot):

        self.bot = bot

        self.protected_guild_ids = (
            load_protected_guild_ids()
        )

        log.info(
            "Servers cog yüklendi. Protected guild count=%d",
            len(self.protected_guild_ids),
        )

    # ========================================================
    # AUTHORIZATION
    # ========================================================

    def is_authorized(
        self,
        member: discord.abc.User,
    ) -> bool:
        """
        velgrath_ username'i VEYA Administrator yetkisi.
        """

        username = getattr(member, "name", "")

        if username.lower() == AUTHORIZED_USERNAME.lower():
            return True

        guild_permissions = getattr(
            member,
            "guild_permissions",
            None,
        )

        if guild_permissions is not None:

            if guild_permissions.administrator:
                return True

        return False

    # ========================================================
    # COMMAND CHECK
    # ========================================================

    async def check_access(
        self,
        ctx: commands.Context,
    ) -> bool:

        if self.is_authorized(ctx.author):
            return True

        try:

            await ctx.reply(
                "❌ Bu komutu kullanma yetkiniz yok.",
                mention_author=False,
            )

        except discord.HTTPException:
            pass

        return False

    # ========================================================
    # PROTECTED CHECK
    # ========================================================

    def is_protected(
        self,
        guild_id: int,
    ) -> bool:

        return guild_id in self.protected_guild_ids

    # ========================================================
    # MEMBER COUNTS
    # ========================================================

    def get_member_statistics(
        self,
        guild: discord.Guild,
    ) -> tuple[int, int, int]:

        members = guild.members

        total = guild.member_count or len(members)

        bots = sum(
            1
            for member in members
            if member.bot
        )

        humans = max(
            0,
            total - bots,
        )

        return total, humans, bots

    # ========================================================
    # CHANNEL COUNTS
    # ========================================================

    def get_channel_statistics(
        self,
        guild: discord.Guild,
    ) -> tuple[int, int, int, int]:

        channels = guild.channels

        text = sum(
            1
            for channel in channels
            if isinstance(
                channel,
                discord.TextChannel,
            )
        )

        voice = sum(
            1
            for channel in channels
            if isinstance(
                channel,
                discord.VoiceChannel,
            )
        )

        categories = sum(
            1
            for channel in channels
            if isinstance(
                channel,
                discord.CategoryChannel,
            )
        )

        total = len(channels)

        return total, text, voice, categories

    # ========================================================
    # DATE FORMAT
    # ========================================================

    @staticmethod
    def format_date(
        value: Optional[datetime],
    ) -> str:

        if value is None:
            return "Bilinmiyor"

        return discord.utils.format_dt(
            value,
            style="F",
        )

    # ========================================================
    # OWNER
    # ========================================================

    async def get_owner_name(
        self,
        guild: discord.Guild,
    ) -> str:

        try:

            owner = guild.owner

            if owner is not None:
                return f"{owner} (`{owner.id}`)"

        except Exception:
            pass

        try:

            owner = await self.bot.fetch_user(
                guild.owner_id
            )

            return f"{owner} (`{owner.id}`)"

        except Exception:
            return f"Bilinmiyor (`{guild.owner_id}`)"

    # ========================================================
    # CREATE SERVER EMBED
    # ========================================================

    async def build_server_embed(
        self,
        guild: discord.Guild,
    ) -> discord.Embed:

        total, humans, bots = (
            self.get_member_statistics(guild)
        )

        channels, text, voice, categories = (
            self.get_channel_statistics(guild)
        )

        owner = await self.get_owner_name(guild)

        embed = discord.Embed(
            title=f"🏰 {guild.name}",
            description=(
                f"**Guild ID:** `{guild.id}`"
            ),
            timestamp=datetime.now(),
        )

        # ----------------------------------------------------
        # MEMBERS
        # ----------------------------------------------------

        embed.add_field(
            name="👥 Members",
            value=(
                f"**Total:** `{total:,}`\n"
                f"**Humans:** `{humans:,}`\n"
                f"**Bots:** `{bots:,}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # CHANNELS
        # ----------------------------------------------------

        embed.add_field(
            name="💬 Channels",
            value=(
                f"**Total:** `{channels}`\n"
                f"**Text:** `{text}`\n"
                f"**Voice:** `{voice}`\n"
                f"**Categories:** `{categories}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # SERVER
        # ----------------------------------------------------

        embed.add_field(
            name="🏰 Server",
            value=(
                f"**Owner:** {owner}\n"
                f"**Roles:** `{len(guild.roles)}`\n"
                f"**Boosts:** `{guild.premium_subscription_count or 0}`\n"
                f"**Boost Level:** `{guild.premium_tier}`"
            ),
            inline=False,
        )

        # ----------------------------------------------------
        # DATES
        # ----------------------------------------------------

        created = self.format_date(
            guild.created_at
        )

        embed.add_field(
            name="📅 Dates",
            value=(
                f"**Created:** {created}"
            ),
            inline=False,
        )

        # ----------------------------------------------------
        # VERIFICATION
        # ----------------------------------------------------

        verification = str(
            guild.verification_level
        ).replace("_", " ").title()

        embed.add_field(
            name="🔐 Verification",
            value=f"`{verification}`",
            inline=True,
        )

        # ----------------------------------------------------
        # FEATURES
        # ----------------------------------------------------

        features = len(guild.features)

        embed.add_field(
            name="⚙️ Features",
            value=f"`{features}` enabled",
            inline=True,
        )

        # ----------------------------------------------------
        # BOT STATUS
        # ----------------------------------------------------

        embed.add_field(
            name="🤖 Bot Status",
            value="🟢 Connected",
            inline=True,
        )

        # ----------------------------------------------------
        # ICON
        # ----------------------------------------------------

        if guild.icon:

            embed.set_thumbnail(
                url=guild.icon.url
            )

        embed.set_footer(
            text="PAG Bot • Server Information"
        )

        return embed

    # ========================================================
    # !SERVERS
    # ========================================================

    @commands.command(
        name="servers",
        aliases=[
            "guilds",
            "serverlist",
        ],
    )
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user,
    )
    async def servers_command(
        self,
        ctx: commands.Context,
    ):

        if not await self.check_access(ctx):
            return

        # ----------------------------------------------------
        # REFRESH PROTECTED GUILDS
        # ----------------------------------------------------

        self.protected_guild_ids = (
            load_protected_guild_ids()
        )

        # ----------------------------------------------------
        # FILTER
        # ----------------------------------------------------

        visible_guilds = [
            guild
            for guild in self.bot.guilds
            if guild.id not in self.protected_guild_ids
        ]

        visible_guilds.sort(
            key=lambda guild: (
                guild.member_count or 0
            ),
            reverse=True,
        )

        # ----------------------------------------------------
        # NO SERVERS
        # ----------------------------------------------------

        if not visible_guilds:

            embed = discord.Embed(
                title="🏰 PAG BOT — SERVERS",
                description=(
                    "Gösterilecek korunmasız guild bulunamadı."
                ),
            )

            embed.add_field(
                name="🔒 Protected",
                value=(
                    f"`{len(self.protected_guild_ids)}` guild"
                ),
            )

            await ctx.reply(
                embed=embed,
                mention_author=False,
            )

            return

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        total_members = sum(
            guild.member_count or 0
            for guild in visible_guilds
        )

        total_guilds = len(
            visible_guilds
        )

        # ----------------------------------------------------
        # BUILD PAGES
        # ----------------------------------------------------

        pages: list[discord.Embed] = []

        # Her sayfada 5 guild.
        chunk_size = 5

        for index in range(
            0,
            len(visible_guilds),
            chunk_size,
        ):

            chunk = visible_guilds[
                index:index + chunk_size
            ]

            page_number = (
                index // chunk_size
            ) + 1

            total_pages = (
                (len(visible_guilds) - 1)
                // chunk_size
            ) + 1

            embed = discord.Embed(
                title="🏰 PAG BOT — SERVER LIST",
                description=(
                    f"📊 **Visible Servers:** `{total_guilds}`\n"
                    f"👥 **Visible Members:** `{total_members:,}`\n"
                    f"🔒 **Protected Servers:** "
                    f"`{len(self.protected_guild_ids)}`"
                ),
                timestamp=datetime.now(),
            )

            for guild in chunk:

                total, humans, bots = (
                    self.get_member_statistics(guild)
                )

                channels, text, voice, categories = (
                    self.get_channel_statistics(guild)
                )

                embed.add_field(
                    name=(
                        f"🏰 {guild.name}"
                    ),
                    value=(
                        f"🆔 `{guild.id}`\n"
                        f"👥 `{total:,}` "
                        f"(`{humans:,}` humans / "
                        f"`{bots:,}` bots)\n"
                        f"💬 `{channels}` channels "
                        f"(`{text}` text / "
                        f"`{voice}` voice)\n"
                        f"🎭 `{len(guild.roles)}` roles\n"
                        f"🚀 Boost: `{guild.premium_tier}` "
                        f"(`{guild.premium_subscription_count or 0}`)"
                    ),
                    inline=False,
                )

            embed.set_footer(
                text=(
                    f"Page {page_number}/{total_pages} "
                    f"• Protected guilds are hidden"
                )
            )

            pages.append(embed)

        # ----------------------------------------------------
        # VIEW
        # ----------------------------------------------------

        view = ServerListView(
            author_id=ctx.author.id,
            pages=pages,
        )

        await ctx.reply(
            embed=pages[0],
            view=view,
            mention_author=False,
        )

    # ========================================================
    # !SERVERINFO
    # ========================================================

    @commands.command(
        name="serverinfo",
        aliases=[
            "guildinfo",
            "sinfo",
        ],
    )
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user,
    )
    async def serverinfo_command(
        self,
        ctx: commands.Context,
        guild_id: Optional[int] = None,
    ):

        if not await self.check_access(ctx):
            return

        if guild_id is None:

            await ctx.reply(
                "❌ Kullanım: `!serverinfo <guild_id>`",
                mention_author=False,
            )

            return

        guild = self.bot.get_guild(
            guild_id
        )

        if guild is None:

            await ctx.reply(
                "❌ Bot bu guild'de bulunmuyor.",
                mention_author=False,
            )

            return

        # Protected guild'leri info ile de göstermiyoruz.
        if self.is_protected(guild.id):

            await ctx.reply(
                "🔒 Bu guild korumalı olduğu için "
                "bilgileri gösterilmiyor.",
                mention_author=False,
            )

            return

        embed = await self.build_server_embed(
            guild
        )

        await ctx.reply(
            embed=embed,
            mention_author=False,
        )

    # ========================================================
    # !LEAVE
    # ========================================================

    @commands.command(
        name="leave",
        aliases=[
            "leaveguild",
        ],
    )
    @commands.cooldown(
        1,
        10,
        commands.BucketType.user,
    )
    async def leave_command(
        self,
        ctx: commands.Context,
        guild_id: Optional[int] = None,
    ):

        if not await self.check_access(ctx):
            return

        if guild_id is None:

            await ctx.reply(
                "❌ Kullanım: `!leave <guild_id>`",
                mention_author=False,
            )

            return

        # ----------------------------------------------------
        # PROTECTED CHECK
        # ----------------------------------------------------

        if self.is_protected(guild_id):

            await ctx.reply(
                "🛡️ **İşlem engellendi.**\n"
                "Bu guild `.env` içerisinde korunuyor "
                "ve bot buradan ayrılamaz.",
                mention_author=False,
            )

            return

        # ----------------------------------------------------
        # GET GUILD
        # ----------------------------------------------------

        guild = self.bot.get_guild(
            guild_id
        )

        if guild is None:

            await ctx.reply(
                "❌ Bot bu guild'de bulunmuyor.",
                mention_author=False,
            )

            return

        # ----------------------------------------------------
        # LEAVE
        # ----------------------------------------------------

        guild_name = guild.name

        try:

            await guild.leave()

        except discord.Forbidden:

            await ctx.reply(
                "❌ Guild'den ayrılmak için Discord API "
                "tarafından işlem reddedildi.",
                mention_author=False,
            )

            return

        except discord.HTTPException as exc:

            log.exception(
                "Guild leave başarısız: %s (%s)",
                guild.id,
                exc,
            )

            await ctx.reply(
                "❌ Guild'den ayrılırken Discord API hatası oluştu.",
                mention_author=False,
            )

            return

        await ctx.reply(
            f"✅ `{guild_name}` (`{guild_id}`) "
            "guild'inden ayrıldım.",
            mention_author=False,
        )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    @servers_command.error
    async def servers_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):

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
            "servers command error",
            exc_info=error,
        )

    @serverinfo_command.error
    async def serverinfo_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):

        if isinstance(
            error,
            commands.BadArgument,
        ):

            await ctx.reply(
                "❌ Guild ID sayı olmalıdır.\n"
                "Örnek: `!serverinfo 123456789012345678`",
                mention_author=False,
            )

            return

        if isinstance(
            error,
            commands.CommandOnCooldown,
        ):

            await ctx.reply(
                f"⏳ `{error.retry_after:.1f}s` bekleyin.",
                mention_author=False,
            )

            return

        log.exception(
            "serverinfo command error",
            exc_info=error,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Servers(bot)
    )