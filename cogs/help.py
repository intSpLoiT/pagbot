from __future__ import annotations

import logging
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONSTANTS
# ============================================================

PAG_COLOR: Final[int] = 0x5865F2

PAG_RED: Final[int] = 0xED4245

PAG_GREEN: Final[int] = 0x57F287

PAG_GOLD: Final[int] = 0xFEE75C

PAG_DARK: Final[int] = 0x2B2D31


# ============================================================
# HELP COG
# ============================================================

class Help(commands.Cog):
    """
    PAG Bot interaktif yardım sistemi.

    Özellikler:

        /help
            ↓
        Ana yardım paneli
            ↓
        Kategori seçimi
            ↓
        Komut listesi
            ↓
        Geri dönüş
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.logger: logging.Logger = (
            getattr(
                bot,
                "logger",
                logging.getLogger("PAG"),
            )
        )

    # ========================================================
    # HELP COMMAND
    # ========================================================

    @app_commands.command(
        name="help",
        description="PAG Bot yardım panelini açar.",
    )
    async def help_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Ana yardım panelini gösterir.
        """

        embed = self._create_main_embed(
            interaction,
        )

        view = HelpView(
            bot=self.bot,
            author_id=interaction.user.id,
        )

        await interaction.response.send_message(
            embed=embed,
            view=view,
        )

        self.logger.info(
            "Help panel opened by %s (%s).",
            interaction.user,
            interaction.user.id,
        )

    # ========================================================
    # MAIN EMBED
    # ========================================================

    def _create_main_embed(
        self,
        interaction: discord.Interaction,
    ) -> discord.Embed:
        """
        Ana yardım embed'ini oluşturur.
        """

        guild_name = (
            interaction.guild.name
            if interaction.guild
            else "Direct Messages"
        )

        embed = discord.Embed(
            title="⚔️ PAG Bot • Help Center",
            description=(
                "PAG Bot'un tüm sistemlerine "
                "buradan ulaşabilirsiniz.\n\n"

                "Aşağıdaki menüden bir kategori seçerek "
                "kullanılabilir komutları görüntüleyin."
            ),
            color=PAG_COLOR,
        )

        embed.add_field(
            name="🧩 Sistem",
            value=(
                "PAG Bot aktif durumda.\n"
                "Komut kategorisini aşağıdaki menüden seçin."
            ),
            inline=False,
        )

        embed.add_field(
            name="📚 Kategoriler",
            value=(
                "👤 Profil & Kullanıcı\n"
                "🎮 Roblox & Verification\n"
                "🏆 Top 10 & Ranking\n"
                "🎉 Events\n"
                "🛡️ Moderation\n"
                "⚙️ System\n"
                "📢 Announcement"
            ),
            inline=True,
        )

        embed.add_field(
            name="🌐 Sunucu",
            value=(
                f"`{guild_name}`\n"
                f"👥 {len(interaction.guild.members) if interaction.guild else 0} members"
            ),
            inline=True,
        )

        embed.set_footer(
            text=(
                "PAG Bot • Select a category below"
            ),
        )

        return embed


# ============================================================
# HELP VIEW
# ============================================================

class HelpView(
    discord.ui.View,
):
    """
    Ana yardım paneli View'ı.
    """

    def __init__(
        self,
        bot: commands.Bot,
        author_id: int,
    ) -> None:

        super().__init__(
            timeout=300,
        )

        self.bot = bot

        self.author_id = author_id

        self.add_item(
            HelpSelect(
                bot=bot,
                author_id=author_id,
            )
        )

    # ========================================================
    # BACK BUTTON
    # ========================================================

    @discord.ui.button(
        label="Ana Menü",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def home_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu yardım panelini yalnızca paneli açan kişi kullanabilir.",
                ephemeral=True,
            )

            return

        cog = self.bot.get_cog(
            "Help",
        )

        if cog is None:

            await interaction.response.send_message(
                "❌ Help sistemi kullanılamıyor.",
                ephemeral=True,
            )

            return

        embed = cog._create_main_embed(
            interaction,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )


# ============================================================
# SELECT MENU
# ============================================================

class HelpSelect(
    discord.ui.Select,
):
    """
    Yardım kategorisi seçim menüsü.
    """

    def __init__(
        self,
        bot: commands.Bot,
        author_id: int,
    ) -> None:

        self.bot = bot

        self.author_id = author_id

        options = [

            discord.SelectOption(
                label="Profil & Kullanıcı",
                value="profile",
                emoji="👤",
                description="Profil ve kullanıcı komutları",
            ),

            discord.SelectOption(
                label="Roblox & Verification",
                value="roblox",
                emoji="🎮",
                description="Roblox ve doğrulama sistemleri",
            ),

            discord.SelectOption(
                label="Top 10 & Ranking",
                value="ranking",
                emoji="🏆",
                description="Sıralama ve Top 10 komutları",
            ),

            discord.SelectOption(
                label="Events",
                value="events",
                emoji="🎉",
                description="Etkinlik sistemleri",
            ),

            discord.SelectOption(
                label="Moderation",
                value="moderation",
                emoji="🛡️",
                description="Blacklist ve moderasyon",
            ),

            discord.SelectOption(
                label="Server Tools",
                value="tools",
                emoji="🔧",
                description="Say, write ve rol araçları",
            ),

            discord.SelectOption(
                label="System",
                value="system",
                emoji="⚙️",
                description="Bot ve sistem komutları",
            ),

        ]

        super().__init__(
            placeholder="📚 Bir kategori seçin...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=(
                f"pag_help_select_{author_id}"
            ),
        )

    # ========================================================
    # CALLBACK
    # ========================================================

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu paneli yalnızca açan kişi kullanabilir.",
                ephemeral=True,
            )

            return

        category = self.values[0]

        embed = self._create_category_embed(
            category,
        )

        view = HelpCategoryView(
            bot=self.bot,
            author_id=self.author_id,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )

    # ========================================================
    # CATEGORY EMBED
    # ========================================================

    def _create_category_embed(
        self,
        category: str,
    ) -> discord.Embed:
        """
        Seçilen kategori için embed oluşturur.
        """

        embed = discord.Embed(
            color=PAG_COLOR,
        )

        if category == "profile":

            embed.title = "👤 Profile & User"

            embed.description = (
                "Kullanıcı profil sistemleri."
            )

            embed.add_field(
                name="/profile",
                value=(
                    "Kullanıcı profilini görüntüler."
                ),
                inline=False,
            )

            embed.add_field(
                name="📊 Profil Sistemi",
                value=(
                    "Kullanıcı istatistikleri, "
                    "bilgileri ve PAG verileri."
                ),
                inline=False,
            )

        elif category == "roblox":

            embed.title = "🎮 Roblox & Verification"

            embed.description = (
                "Roblox bağlantısı ve doğrulama sistemleri."
            )

            embed.add_field(
                name="/verify",
                value=(
                    "Discord hesabını Roblox hesabıyla doğrular."
                ),
                inline=False,
            )

            embed.add_field(
                name="🔗 Roblox Services",
                value=(
                    "Roblox API tabanlı sistemler."
                ),
                inline=False,
            )

        elif category == "ranking":

            embed.title = "🏆 Top 10 & Ranking"

            embed.description = (
                "PAG sıralama sistemleri."
            )

            embed.add_field(
                name="🏆 Top 10",
                value=(
                    "Sunucunun en iyi oyuncularını görüntüler."
                ),
                inline=False,
            )

            embed.add_field(
                name="📈 Ranking",
                value=(
                    "Oyuncu sıralaması ve istatistik sistemleri."
                ),
                inline=False,
            )

        elif category == "events":

            embed.title = "🎉 Events"

            embed.description = (
                "PAG etkinlik sistemleri."
            )

            embed.add_field(
                name="🎮 Event System",
                value=(
                    "Etkinlik oluşturma, katılım ve "
                    "katılımcı yönetimi."
                ),
                inline=False,
            )

        elif category == "moderation":

            embed.title = "🛡️ Moderation"

            embed.description = (
                "Sunucu güvenliği ve moderasyon araçları."
            )

            embed.add_field(
                name="🚫 Blacklist",
                value=(
                    "Kullanıcı blacklist sistemi."
                ),
                inline=False,
            )

        elif category == "tools":

            embed.title = "🔧 Server Tools"

            embed.description = (
                "Sunucu yönetimi için yardımcı araçlar."
            )

            embed.add_field(
                name="📢 Say",
                value=(
                    "Bot üzerinden mesaj gönderme araçları."
                ),
                inline=False,
            )

            embed.add_field(
                name="✍️ Write",
                value=(
                    "Mesaj ve yazı araçları."
                ),
                inline=False,
            )

            embed.add_field(
                name="🎭 Role Info",
                value=(
                    "Rol bilgilerini görüntüleme."
                ),
                inline=False,
            )

        elif category == "system":

            embed.title = "⚙️ System"

            embed.description = (
                "PAG Bot sistem bilgileri."
            )

            embed.add_field(
                name="🤖 Bot Status",
                value=(
                    "PAG Bot aktiflik ve sistem durumu."
                ),
                inline=False,
            )

        else:

            embed.title = "📚 PAG Bot Help"

            embed.description = (
                "Kategori bulunamadı."
            )

        embed.set_footer(
            text=(
                "PAG Bot • Help Center"
            ),
        )

        return embed


# ============================================================
# CATEGORY VIEW
# ============================================================

class HelpCategoryView(
    discord.ui.View,
):
    """
    Kategori sayfası View'ı.
    """

    def __init__(
        self,
        bot: commands.Bot,
        author_id: int,
    ) -> None:

        super().__init__(
            timeout=300,
        )

        self.bot = bot

        self.author_id = author_id

    # ========================================================
    # HOME
    # ========================================================

    @discord.ui.button(
        label="Ana Menü",
        emoji="🏠",
        style=discord.ButtonStyle.primary,
    )
    async def home_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        if interaction.user.id != self.author_id:

            await interaction.response.send_message(
                "❌ Bu paneli yalnızca açan kişi kullanabilir.",
                ephemeral=True,
            )

            return

        cog = self.bot.get_cog(
            "Help",
        )

        if cog is None:

            await interaction.response.send_message(
                "❌ Help sistemi kullanılamıyor.",
                ephemeral=True,
            )

            return

        embed = cog._create_main_embed(
            interaction,
        )

        view = HelpView(
            bot=self.bot,
            author_id=self.author_id,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:
    """
    Discord.py extension setup.
    """

    await bot.add_cog(
        Help(
            bot,
        )
    )