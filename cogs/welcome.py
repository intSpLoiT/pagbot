from __future__ import annotations

"""
PAG BOT
Welcome / Leave System

Prefix:
    !welcomepanel

Features:
    - Welcome message
    - Leave message
    - Welcome channel selection
    - Leave channel selection
    - Custom welcome title
    - Custom welcome message
    - Custom leave title
    - Custom leave message
    - GIF attachment support
    - Persistent SQLite configuration
    - Interactive configuration panel
    - Enable / disable welcome system
    - Enable / disable leave system
    - Placeholder system
    - Permission protection
    - Safe error handling

Placeholders:
    {user}
    {mention}
    {username}
    {display_name}
    {server}
    {member_count}
    {id}
    {joined_at}
    {created_at}
"""


from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands


# ============================================================
# GIF CONFIGURATION
# ============================================================

# ÜSTÂD VELGRATH 🔱:
# Buraya kendi GIF yollarını vereceksin.

WELCOME_GIF_PATH = "gifs/welcome.gif"
LEAVE_GIF_PATH = "gifs/welcome.gif"


# ============================================================
# DEFAULT CONFIGURATION
# ============================================================

DEFAULT_WELCOME_TITLE = "🎉 PAG'a Hoş Geldin!"

DEFAULT_WELCOME_MESSAGE = (
    "Hoş geldin {mention}! 👋\n\n"
    "**{server}** ailesine katıldığın için mutluyuz.\n"
    "Şu anda sunucumuzda **{member_count}** üye bulunuyor."
)

DEFAULT_LEAVE_TITLE = "👋 Bir Üyemiz Ayrıldı"

DEFAULT_LEAVE_MESSAGE = (
    "**{username}** sunucudan ayrıldı.\n\n"
    "PAG ailesindeki yerin her zaman hatırlanacak."
)
file = self._make_file(
    gif_path,
)

embed = self._build_welcome_embed(
    member,
    config,
    gif_filename=(
        file.filename
        if file
        else None
    ),
)

await channel.send(
    embed=embed,
    file=file,
)

# ============================================================
# COLORS
# ============================================================

WELCOME_COLOR = discord.Color.green()
LEAVE_COLOR = discord.Color.red()


# ============================================================
# DATABASE TABLE
# ============================================================

CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS welcome_settings (

    guild_id INTEGER PRIMARY KEY,

    welcome_channel_id INTEGER,
    leave_channel_id INTEGER,

    welcome_enabled INTEGER NOT NULL DEFAULT 1,
    leave_enabled INTEGER NOT NULL DEFAULT 1,

    welcome_title TEXT NOT NULL,
    welcome_message TEXT NOT NULL,

    leave_title TEXT NOT NULL,
    leave_message TEXT NOT NULL,

    updated_at TEXT NOT NULL
)
"""


# ============================================================
# DATA MODEL
# ============================================================


@dataclass(slots=True)
class WelcomeConfig:
    guild_id: int

    welcome_channel_id: Optional[int]

    leave_channel_id: Optional[int]

    welcome_enabled: bool

    leave_enabled: bool

    welcome_title: str

    welcome_message: str

    leave_title: str

    leave_message: str


# ============================================================
# WELCOME COG
# ============================================================


class Welcome(commands.Cog):
    """
    PAG giriş / çıkış sistemi.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.logger = getattr(
            bot,
            "logger",
            None,
        )

        self._database_ready = False

    # ========================================================
    # LOGGER
    # ========================================================

    def _log(
        self,
        level: str,
        message: str,
        *args,
    ) -> None:

        logger = self.logger

        if logger is None:
            return

        log_method = getattr(
            logger,
            level,
            None,
        )

        if log_method is not None:
            log_method(
                message,
                *args,
            )

    # ========================================================
    # DATABASE
    # ========================================================

    @property
    def database(self):
        """
        PAGBot database nesnesini döndürür.
        """

        database = getattr(
            self.bot,
            "database",
            None,
        )

        if database is None:
            raise RuntimeError(
                "PAGBot database service is unavailable."
            )

        return database

    async def _ensure_database(
        self,
    ) -> None:

        if self._database_ready:
            return

        await self.database.execute(
            CREATE_TABLE_QUERY,
        )

        self._database_ready = True

        self._log(
            "info",
            "Welcome system database initialized.",
        )

    # ========================================================
    # DEFAULT CONFIG
    # ========================================================

    def _default_config(
        self,
        guild_id: int,
    ) -> WelcomeConfig:

        return WelcomeConfig(
            guild_id=guild_id,

            welcome_channel_id=None,
            leave_channel_id=None,

            welcome_enabled=True,
            leave_enabled=True,

            welcome_title=DEFAULT_WELCOME_TITLE,
            welcome_message=DEFAULT_WELCOME_MESSAGE,

            leave_title=DEFAULT_LEAVE_TITLE,
            leave_message=DEFAULT_LEAVE_MESSAGE,
        )

    # ========================================================
    # GET CONFIG
    # ========================================================

    async def _get_config(
        self,
        guild_id: int,
    ) -> WelcomeConfig:

        await self._ensure_database()

        row = await self.database.fetchone(
            """
            SELECT
                guild_id,
                welcome_channel_id,
                leave_channel_id,
                welcome_enabled,
                leave_enabled,
                welcome_title,
                welcome_message,
                leave_title,
                leave_message
            FROM welcome_settings
            WHERE guild_id = ?
            LIMIT 1
            """,
            (
                guild_id,
            ),
        )

        if row is None:

            config = self._default_config(
                guild_id,
            )

            await self._save_config(
                config,
            )

            return config

        return WelcomeConfig(
            guild_id=int(
                row["guild_id"]
            ),

            welcome_channel_id=(
                int(row["welcome_channel_id"])
                if row["welcome_channel_id"] is not None
                else None
            ),

            leave_channel_id=(
                int(row["leave_channel_id"])
                if row["leave_channel_id"] is not None
                else None
            ),

            welcome_enabled=bool(
                row["welcome_enabled"]
            ),

            leave_enabled=bool(
                row["leave_enabled"]
            ),

            welcome_title=(
                row["welcome_title"]
                or DEFAULT_WELCOME_TITLE
            ),

            welcome_message=(
                row["welcome_message"]
                or DEFAULT_WELCOME_MESSAGE
            ),

            leave_title=(
                row["leave_title"]
                or DEFAULT_LEAVE_TITLE
            ),

            leave_message=(
                row["leave_message"]
                or DEFAULT_LEAVE_MESSAGE
            ),
        )

    # ========================================================
    # SAVE CONFIG
    # ========================================================

    async def _save_config(
        self,
        config: WelcomeConfig,
    ) -> None:

        await self._ensure_database()

        await self.database.execute(
            """
            INSERT INTO welcome_settings (
                guild_id,
                welcome_channel_id,
                leave_channel_id,
                welcome_enabled,
                leave_enabled,
                welcome_title,
                welcome_message,
                leave_title,
                leave_message,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(guild_id)
            DO UPDATE SET
                welcome_channel_id =
                    excluded.welcome_channel_id,

                leave_channel_id =
                    excluded.leave_channel_id,

                welcome_enabled =
                    excluded.welcome_enabled,

                leave_enabled =
                    excluded.leave_enabled,

                welcome_title =
                    excluded.welcome_title,

                welcome_message =
                    excluded.welcome_message,

                leave_title =
                    excluded.leave_title,

                leave_message =
                    excluded.leave_message,

                updated_at =
                    excluded.updated_at
            """,
            (
                config.guild_id,

                config.welcome_channel_id,
                config.leave_channel_id,

                int(config.welcome_enabled),
                int(config.leave_enabled),

                config.welcome_title,
                config.welcome_message,

                config.leave_title,
                config.leave_message,

                discord.utils.utcnow().isoformat(),
            ),
        )

    # ========================================================
    # PERMISSION
    # ========================================================

    @staticmethod
    def _is_manager(
        member: discord.Member,
    ) -> bool:

        permissions = member.guild_permissions

        return (
            permissions.administrator
            or permissions.manage_guild
        )

    # ========================================================
    # PLACEHOLDERS
    # ========================================================

    def _replace_placeholders(
        self,
        text: str,
        member: discord.Member,
    ) -> str:

        guild = member.guild

        joined_at = (
            discord.utils.format_dt(
                member.joined_at,
                style="R",
            )
            if member.joined_at
            else "Bilinmiyor"
        )

        created_at = discord.utils.format_dt(
            member.created_at,
            style="R",
        )

        replacements = {
            "{user}": member.display_name,
            "{mention}": member.mention,
            "{username}": member.name,
            "{display_name}": member.display_name,
            "{server}": guild.name,
            "{member_count}": str(
                guild.member_count or 0
            ),
            "{id}": str(member.id),
            "{joined_at}": joined_at,
            "{created_at}": created_at,
        }

        for key, value in replacements.items():
            text = text.replace(
                key,
                value,
            )

        return text

    # ========================================================
    # CHANNEL
    # ========================================================

    def _get_text_channel(
        self,
        guild: discord.Guild,
        channel_id: Optional[int],
    ) -> Optional[discord.TextChannel]:

        if channel_id is None:
            return None

        channel = guild.get_channel(
            channel_id,
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return None

        return channel

    # ========================================================
    # GIF
    # ========================================================

    @staticmethod
    def _get_gif_path(
        path: str,
    ) -> Optional[Path]:

        if not path:
            return None

        if path.startswith(
            "BURAYA_"
        ):
            return None

        file_path = Path(path)

        if not file_path.exists():
            return None

        if not file_path.is_file():
            return None

        return file_path

    # ========================================================
    # EMBED
    # ========================================================

    def _build_welcome_embed(
        self,
        member: discord.Member,
        config: WelcomeConfig,
        *,
        gif_filename: Optional[str],
    ) -> discord.Embed:

        title = self._replace_placeholders(
            config.welcome_title,
            member,
        )

        description = self._replace_placeholders(
            config.welcome_message,
            member,
        )

        embed = discord.Embed(
            title=title,
            description=description,
            color=WELCOME_COLOR,
            timestamp=discord.utils.utcnow(),
        )

        embed.set_author(
            name=member.display_name,
            icon_url=member.display_avatar.url,
        )

        embed.set_thumbnail(
            url=member.display_avatar.url,
        )

        if gif_filename:
            embed.set_image(
                url=f"attachment://{gif_filename}",
            )

        embed.set_footer(
            text=(
                f"{member.guild.name} • "
                "Welcome System"
            ),
        )

        return embed

    # ========================================================

    def _build_leave_embed(
        self,
        member: discord.Member,
        config: WelcomeConfig,
        *,
        gif_filename: Optional[str],
    ) -> discord.Embed:

        title = self._replace_placeholders(
            config.leave_title,
            member,
        )

        description = self._replace_placeholders(
            config.leave_message,
            member,
        )

        embed = discord.Embed(
            title=title,
            description=description,
            color=LEAVE_COLOR,
            timestamp=discord.utils.utcnow(),
        )

        embed.set_author(
            name=member.display_name,
            icon_url=member.display_avatar.url,
        )

        embed.set_thumbnail(
            url=member.display_avatar.url,
        )

        if gif_filename:
            embed.set_image(
                url=f"attachment://{gif_filename}",
            )

        embed.set_footer(
            text=(
                f"{member.guild.name} • "
                "Leave System"
            ),
        )

        return embed

    # ========================================================
    # FILE
    # ========================================================

    @staticmethod
    def _make_file(
        path: Optional[Path],
    ) -> Optional[discord.File]:

        if path is None:
            return None

        try:

            return discord.File(
                str(path),
                filename=path.name,
            )

        except (
            OSError,
            ValueError,
        ):

            return None

    # ========================================================
    # MEMBER JOIN
    # ========================================================

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member,
    ) -> None:

        try:

            config = await self._get_config(
                member.guild.id,
            )

            if not config.welcome_enabled:
                return

            channel = self._get_text_channel(
                member.guild,
                config.welcome_channel_id,
            )

            if channel is None:
                return

            gif_path = self._get_gif_path(
                WELCOME_GIF_PATH,
            )

            file = self._make_file(
                gif_path,
            )

            embed = self._build_welcome_embed(
                member,
                config,
                gif_filename=(
                    file.filename
                    if file
                    else None
                ),
            )

            await channel.send(
                embed=embed,
                file=file,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.Forbidden:

            self._log(
                "warning",
                (
                    "Welcome system lacks permission "
                    "in guild %s."
                ),
                member.guild.id,
            )

        except discord.HTTPException as error:

            self._log(
                "error",
                (
                    "Welcome message failed "
                    "for guild %s: %s"
                ),
                member.guild.id,
                error,
            )

        except Exception:

            self._log(
                "exception",
                (
                    "Unexpected error in "
                    "on_member_join."
                ),
            )

    # ========================================================
    # MEMBER LEAVE
    # ========================================================

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member,
    ) -> None:

        try:

            config = await self._get_config(
                member.guild.id,
            )

            if not config.leave_enabled:
                return

            channel = self._get_text_channel(
                member.guild,
                config.leave_channel_id,
            )

            if channel is None:
                return

            gif_path = self._get_gif_path(
                LEAVE_GIF_PATH,
            )

            file = self._make_file(
                gif_path,
            )

            embed = self._build_leave_embed(
                member,
                config,
                gif_filename=(
                    file.filename
                    if file
                    else None
                ),
            )

            await channel.send(
                embed=embed,
                file=file,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.Forbidden:

            self._log(
                "warning",
                (
                    "Leave system lacks permission "
                    "in guild %s."
                ),
                member.guild.id,
            )

        except discord.HTTPException as error:

            self._log(
                "error",
                (
                    "Leave message failed "
                    "for guild %s: %s"
                ),
                member.guild.id,
                error,
            )

        except Exception:

            self._log(
                "exception",
                (
                    "Unexpected error in "
                    "on_member_remove."
                ),
            )

    # ========================================================
    # PANEL COMMAND
    # ========================================================

    @commands.command(
        name="welcomepanel",
    )
    @commands.guild_only()
    async def welcome_panel(
        self,
        ctx: commands.Context,
    ) -> None:

        if not isinstance(
            ctx.author,
            discord.Member,
        ):
            return

        if not self._is_manager(
            ctx.author,
        ):
            await ctx.reply(
                "❌ Bu paneli kullanmak için "
                "`Administrator` veya `Manage Server` "
                "yetkisine sahip olmalısın.",
                mention_author=False,
            )
            return

        config = await self._get_config(
            ctx.guild.id,
        )

        embed = self._build_panel_embed(
            ctx.guild,
            config,
        )

        view = WelcomePanelView(
            cog=self,
            author_id=ctx.author.id,
        )

        await ctx.send(
            embed=embed,
            view=view,
        )

    # ========================================================
    # PANEL EMBED
    # ========================================================

    def _build_panel_embed(
        self,
        guild: discord.Guild,
        config: WelcomeConfig,
    ) -> discord.Embed:

        welcome_channel = (
            guild.get_channel(
                config.welcome_channel_id
            )
            if config.welcome_channel_id
            else None
        )

        leave_channel = (
            guild.get_channel(
                config.leave_channel_id
            )
            if config.leave_channel_id
            else None
        )

        welcome_channel_text = (
            welcome_channel.mention
            if welcome_channel
            else "❌ Ayarlanmadı"
        )

        leave_channel_text = (
            leave_channel.mention
            if leave_channel
            else "❌ Ayarlanmadı"
        )

        welcome_status = (
            "🟢 AKTİF"
            if config.welcome_enabled
            else "🔴 KAPALI"
        )

        leave_status = (
            "🟢 AKTİF"
            if config.leave_enabled
            else "🔴 KAPALI"
        )

        embed = discord.Embed(
            title="🎉 PAG Welcome / Leave Panel",
            description=(
                "Giriş ve çıkış sistemini buradan "
                "yönetebilirsin.\n\n"
                "**Mesajlarda kullanılabilir değişkenler:**\n"
                "`{user}` • `{mention}` • `{username}`\n"
                "`{display_name}` • `{server}`\n"
                "`{member_count}` • `{id}`\n"
                "`{joined_at}` • `{created_at}`"
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📥 Giriş Sistemi",
            value=(
                f"Durum: **{welcome_status}**\n"
                f"Kanal: {welcome_channel_text}\n"
                f"Başlık: `{config.welcome_title[:100]}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📤 Çıkış Sistemi",
            value=(
                f"Durum: **{leave_status}**\n"
                f"Kanal: {leave_channel_text}\n"
                f"Başlık: `{config.leave_title[:100]}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📝 Giriş Mesajı",
            value=(
                config.welcome_message[:800]
                if config.welcome_message
                else "Ayarlanmadı"
            ),
            inline=False,
        )

        embed.add_field(
            name="📝 Çıkış Mesajı",
            value=(
                config.leave_message[:800]
                if config.leave_message
                else "Ayarlanmadı"
            ),
            inline=False,
        )

        if guild.icon:
            embed.set_thumbnail(
                url=guild.icon.url,
            )

        embed.set_footer(
            text="PAG Welcome System",
        )

        return embed

    # ========================================================
    # PANEL REFRESH
    # ========================================================

    async def refresh_panel(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.message:
            return

        if not interaction.guild:
            return

        config = await self._get_config(
            interaction.guild.id,
        )

        embed = self._build_panel_embed(
            interaction.guild,
            config,
        )

        try:

            await interaction.message.edit(
                embed=embed,
            )

        except discord.HTTPException:
            pass


# ============================================================
# CHANNEL MODAL
# ============================================================


class ChannelModal(
    discord.ui.Modal,
):
    def __init__(
        self,
        cog: Welcome,
        author_id: int,
        channel_type: str,
    ) -> None:

        title = (
            "📥 Giriş Kanalı Ayarla"
            if channel_type == "welcome"
            else
            "📤 Çıkış Kanalı Ayarla"
        )

        super().__init__(
            title=title,
            timeout=180,
        )

        self.cog = cog
        self.author_id = author_id
        self.channel_type = channel_type

        self.channel_input = discord.ui.TextInput(
            label="Kanal",
            placeholder=(
                "Kanal ID veya #kanal"
            ),
            required=True,
            max_length=100,
        )

        self.add_item(
            self.channel_input,
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu işlem sana ait değil.",
                ephemeral=True,
            )
            return

        if not interaction.guild:
            return

        value = self.channel_input.value.strip()

        channel_id = self._parse_channel_id(
            value,
        )

        if channel_id is None:

            await interaction.response.send_message(
                "❌ Geçerli bir kanal ID'si veya "
                "kanal mention'ı gir.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(
            channel_id,
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):

            await interaction.response.send_message(
                "❌ Bu ID bir yazı kanalı değil "
                "veya kanal bulunamadı.",
                ephemeral=True,
            )
            return

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        if self.channel_type == "welcome":

            config.welcome_channel_id = channel.id

        else:

            config.leave_channel_id = channel.id

        await self.cog._save_config(
            config,
        )

        await interaction.response.send_message(
            (
                f"✅ {channel.mention} "
                f"{'giriş' if self.channel_type == 'welcome' else 'çıkış'} "
                "kanalı olarak ayarlandı."
            ),
            ephemeral=True,
        )

        await self.cog.refresh_panel(
            interaction,
        )

    @staticmethod
    def _parse_channel_id(
        value: str,
    ) -> Optional[int]:

        value = value.strip()

        if value.startswith("<#") and value.endswith(">"):

            value = value[2:-1]

        value = value.strip()

        if not value.isdigit():
            return None

        try:

            channel_id = int(value)

        except ValueError:

            return None

        if channel_id <= 0:
            return None

        return channel_id


# ============================================================
# MESSAGE MODAL
# ============================================================


class MessageModal(
    discord.ui.Modal,
):
    def __init__(
        self,
        cog: Welcome,
        author_id: int,
        message_type: str,
    ) -> None:

        title = (
            "📥 Giriş Mesajını Düzenle"
            if message_type == "welcome"
            else
            "📤 Çıkış Mesajını Düzenle"
        )

        super().__init__(
            title=title,
            timeout=300,
        )

        self.cog = cog
        self.author_id = author_id
        self.message_type = message_type

        self.title_input = discord.ui.TextInput(
            label="Başlık",
            placeholder="Örn: 🎉 PAG'a Hoş Geldin!",
            required=True,
            max_length=256,
        )

        self.message_input = discord.ui.TextInput(
            label="Mesaj",
            placeholder=(
                "Mesajını buraya yaz...\n"
                "{mention} gibi değişkenleri kullanabilirsin."
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
        )

        self.add_item(
            self.title_input,
        )

        self.add_item(
            self.message_input,
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Bu işlem sana ait değil.",
                ephemeral=True,
            )
            return

        if not interaction.guild:
            return

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        title = self.title_input.value.strip()
        message = self.message_input.value.strip()

        if not title:
            title = (
                DEFAULT_WELCOME_TITLE
                if self.message_type == "welcome"
                else DEFAULT_LEAVE_TITLE
            )

        if not message:
            message = (
                DEFAULT_WELCOME_MESSAGE
                if self.message_type == "welcome"
                else DEFAULT_LEAVE_MESSAGE
            )

        if self.message_type == "welcome":

            config.welcome_title = title
            config.welcome_message = message

        else:

            config.leave_title = title
            config.leave_message = message

        await self.cog._save_config(
            config,
        )

        await interaction.response.send_message(
            "✅ Mesaj ayarları başarıyla güncellendi.",
            ephemeral=True,
        )

        await self.cog.refresh_panel(
            interaction,
        )


# ============================================================
# CONFIRM RESET VIEW
# ============================================================


class ResetConfirmView(
    discord.ui.View,
):

    def __init__(
        self,
        cog: Welcome,
        author_id: int,
    ) -> None:

        super().__init__(
            timeout=60,
        )

        self.cog = cog
        self.author_id = author_id

    @discord.ui.button(
        label="Evet, Sıfırla",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu işlem sana ait değil.",
                ephemeral=True,
            )
            return

        if not interaction.guild:
            return

        config = self.cog._default_config(
            interaction.guild.id,
        )

        await self.cog._save_config(
            config,
        )

        await interaction.response.edit_message(
            content="✅ Welcome / Leave ayarları sıfırlandı.",
            embed=None,
            view=None,
        )

        for child in self.children:
            child.disabled = True

    @discord.ui.button(
        label="Vazgeç",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu işlem sana ait değil.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="İşlem iptal edildi.",
            view=None,
        )


# ============================================================
# PANEL VIEW
# ============================================================


class WelcomePanelView(
    discord.ui.View,
):

    def __init__(
        self,
        cog: Welcome,
        author_id: int,
    ) -> None:

        super().__init__(
            timeout=None,
        )

        self.cog = cog
        self.author_id = author_id

    # ========================================================
    # AUTHORIZATION
    # ========================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id == self.author_id:
            return True

        if isinstance(
            interaction.user,
            discord.Member,
        ) and Welcome._is_manager(
            interaction.user,
        ):
            return True

        await interaction.response.send_message(
            "❌ Bu paneli değiştirme yetkin yok.",
            ephemeral=True,
        )

        return False

    # ========================================================
    # WELCOME CHANNEL
    # ========================================================

    @discord.ui.button(
        label="Giriş Kanalı",
        emoji="📥",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def welcome_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.send_modal(
            ChannelModal(
                self.cog,
                interaction.user.id,
                "welcome",
            )
        )

    # ========================================================
    # LEAVE CHANNEL
    # ========================================================

    @discord.ui.button(
        label="Çıkış Kanalı",
        emoji="📤",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def leave_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.send_modal(
            ChannelModal(
                self.cog,
                interaction.user.id,
                "leave",
            )
        )

    # ========================================================
    # WELCOME MESSAGE
    # ========================================================

    @discord.ui.button(
        label="Giriş Mesajı",
        emoji="📝",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def welcome_message(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        modal = MessageModal(
            self.cog,
            interaction.user.id,
            "welcome",
        )

        modal.title_input.default = (
            config.welcome_title
        )

        modal.message_input.default = (
            config.welcome_message
        )

        await interaction.response.send_modal(
            modal,
        )

    # ========================================================
    # LEAVE MESSAGE
    # ========================================================

    @discord.ui.button(
        label="Çıkış Mesajı",
        emoji="📝",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def leave_message(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        modal = MessageModal(
            self.cog,
            interaction.user.id,
            "leave",
        )

        modal.title_input.default = (
            config.leave_title
        )

        modal.message_input.default = (
            config.leave_message
        )

        await interaction.response.send_modal(
            modal,
        )

    # ========================================================
    # WELCOME TOGGLE
    # ========================================================

    @discord.ui.button(
        label="Giriş Aç/Kapat",
        emoji="🟢",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def toggle_welcome(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        config.welcome_enabled = (
            not config.welcome_enabled
        )

        await self.cog._save_config(
            config,
        )

        await interaction.response.send_message(
            (
                "🟢 Giriş sistemi aktif edildi."
                if config.welcome_enabled
                else
                "🔴 Giriş sistemi kapatıldı."
            ),
            ephemeral=True,
        )

        await self.cog.refresh_panel(
            interaction,
        )

    # ========================================================
    # LEAVE TOGGLE
    # ========================================================

    @discord.ui.button(
        label="Çıkış Aç/Kapat",
        emoji="🔴",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def toggle_leave(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        config = await self.cog._get_config(
            interaction.guild.id,
        )

        config.leave_enabled = (
            not config.leave_enabled
        )

        await self.cog._save_config(
            config,
        )

        await interaction.response.send_message(
            (
                "🟢 Çıkış sistemi aktif edildi."
                if config.leave_enabled
                else
                "🔴 Çıkış sistemi kapatıldı."
            ),
            ephemeral=True,
        )

        await self.cog.refresh_panel(
            interaction,
        )

    # ========================================================
    # RESET
    # ========================================================

    @discord.ui.button(
        label="Sıfırla",
        emoji="♻️",
        style=discord.ButtonStyle.danger,
        row=3,
    )
    async def reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.send_message(
            (
                "⚠️ **Welcome / Leave ayarlarının tamamı "
                "sıfırlanacak.**\n\n"
                "Devam etmek istiyor musun?"
            ),
            ephemeral=True,
            view=ResetConfirmView(
                self.cog,
                interaction.user.id,
            ),
        )

    # ========================================================
    # REFRESH
    # ========================================================

    @discord.ui.button(
        label="Yenile",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
        )

        await self.cog.refresh_panel(
            interaction,
        )

        await interaction.followup.send(
            "✅ Panel yenilendi.",
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:

    cog = Welcome(
        bot,
    )

    await bot.add_cog(
        cog,
    )
