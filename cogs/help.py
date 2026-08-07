
from __future__ import annotations

import inspect
import logging
import math
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Iterable

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import PAGEmbeds


PREFIX_FALLBACK = "!"
PAGE_SIZE = 6
TIMEOUT_SECONDS = 300

BANNER_URLS: dict[str, str] = {
    "home": "https://cdn.discordapp.com/attachments/1529328363074883606/1535306616981692426/gear-house-icon-minimalist-logo-01KWS3H9DBGAJ9QGRTDHV0WTBD-thumbnail.png?ex=6a774936&is=6a75f7b6&hm=8c016d5c4375b6b6f52dca31ec8a5dc2863e3ab7a9e3693072f85895a8ced253&",
    "general": "https://cdn.discordapp.com/attachments/1529328363074883606/1535302989550592082/cropped_circle_image.png?ex=6a7745d5&is=6a75f455&hm=e2662a316fcc3399b7e90dba5abdd0b186a43e9692319898fc495e9a8e3b3a73&",
    "roblox": "https://cdn.discordapp.com/attachments/1529328363074883606/1535305999630602360/Screenshot_2026-08-03-17-02-20-510_com.roblox.client.jpg?ex=6a7748a2&is=6a75f722&hm=838c450300d6d609253ca7afa7aebeb15192f2b7ac03ea753a6d3a9d1a797e4c&",
    "verify": "https://cdn.discordapp.com/attachments/1529328363074883606/1535302685941829713/verified-badge-profile-icon-png_1.png?ex=6a77458c&is=6a75f40c&hm=3e1279cf809a5bc26bcf8a83a379e75f90f69cbb43f3e887e7e45e4d7d2ca2e6&",
    "profile": "https://cdn.discordapp.com/attachments/1529328363074883606/1535307205127962814/images_14.jpg?ex=6a7749c2&is=6a75f842&hm=f0d0a12de11defea2634c807c67be6f17e4b55eaf46282f29fbcb39e1856cc01&",
    "role-info": "https://cdn.discordapp.com/attachments/1529328363074883606/1535307205127962814/images_14.jpg?ex=6a7749c2&is=6a75f842&hm=f0d0a12de11defea2634c807c67be6f17e4b55eaf46282f29fbcb39e1856cc01&",
    "team-tools": "https://cdn.discordapp.com/attachments/1529328363074883606/1535303119578206218/images_11.jpg?ex=6a7745f4&is=6a75f474&hm=980883fe4d4688dbebe82f55859b8bfcff63f816fdbc81adeba367a97330e6fc&",
    "tryout-system": "https://cdn.discordapp.com/attachments/1529328363074883606/1535304029729591317/Screenshot_2026-08-07-18-08-55-587_com.discord-edit.jpg?ex=6a7746cd&is=6a75f54d&hm=dbd9914f7d3ce53bc1b00952b48bf118350131a854a53f8d49a0546428994744&",
    "moderation": "https://cdn.discordapp.com/attachments/1529328363074883606/1535304735597396140/images_1.png?ex=6a774775&is=6a75f5f5&hm=cb23770d3a9d21692f2bc62b472012255eba65d60c6ca38f230ef2a75f541ddb&",
    "blacklist": "https://cdn.discordapp.com/attachments/1529328363074883606/1535308937602273360/images_16.jpg?ex=6a774b5f&is=6a75f9df&hm=4dfb53ebfd03507b4bb1bd57ddf552418257358c5237a9be76c04c18e3da7bc3&",
    "announcements": "https://cdn.discordapp.com/attachments/1529328363074883606/1535305079379464252/images_13.jpg?ex=6a7747c7&is=6a75f647&hm=b91a612c3e5cd3fea4e6f508d62fd4cef63a405aaded23ddeb2b98796d99a43a&",
    "top-10": "https://cdn.discordapp.com/attachments/1529328363074883606/1535305100472352797/images_12.jpg?ex=6a7747cc&is=6a75f64c&hm=c2e315aeebd200f84ed5595fedfd7137d7aeb36bfc9f1a348978a97e940b7e43&",
    "system": "https://cdn.discordapp.com/attachments/1529328363074883606/1535305854478188644/Icon121-5.jpg?ex=6a774880&is=6a75f700&hm=9bce69555c195938ff8c4642d6e8b7396de61cd6d42a3df5323e1ba8bf1557d5&",
    "detail": "https://cdn.discordapp.com/attachments/1529328363074883606/1535309594358980638/images_17.jpg?ex=6a774bfb&is=6a75fa7b&hm=da39480ac3d5196f9d4de5209e325ee44a885017759868e0db0b94e465411fa3&",
}

CATEGORY_ORDER: tuple[str, ...] = (
    "general",
    "roblox",
    "verify",
    "profile",
    "role-info",
    "team-tools",
    "tryout-system",
    "moderation",
    "blacklist",
    "announcements",
    "top-10",
    "system",
)

CATEGORY_META: dict[str, dict[str, str]] = {
    "general": {
        "title": "General",
        "emoji": "👤",
        "description": "Kullanıcı profili, sunucu bilgisi ve temel genel komutlar.",
    },
    "roblox": {
        "title": "Roblox",
        "emoji": "🎮",
        "description": "Roblox kullanıcı, avatar ve toplu sorgu araçları.",
    },
    "verify": {
        "title": "Verify",
        "emoji": "🔗",
        "description": "Roblox hesabı bağlama ve doğrulama akışları.",
    },
    "profile": {
        "title": "Profile",
        "emoji": "🪪",
        "description": "PAG profil görüntüleme ve önizleme komutları.",
    },
    "role-info": {
        "title": "Role Info",
        "emoji": "🏷️",
        "description": "Rol detayları, üyeler ve istatistik inceleme araçları.",
    },
    "team-tools": {
        "title": "Team Tools",
        "emoji": "🧩",
        "description": "Takım paneli, spar, train ve takım organizasyon araçları.",
    },
    "tryout-system": {
        "title": "Tryout System",
        "emoji": "🏆",
        "description": "Tryout setup, announcement, attendance ve stage sonuç sistemi.",
    },
    "moderation": {
        "title": "Moderation",
        "emoji": "🛡️",
        "description": "Warn, mute, ban, purge, lock ve gelişmiş moderasyon komutları.",
    },
    "blacklist": {
        "title": "Blacklist",
        "emoji": "⛔",
        "description": "Blacklist yönetimi ve kayıt temizleme araçları.",
    },
    "announcements": {
        "title": "Announcements",
        "emoji": "📣",
        "description": "Duyuru, yazı paneli ve mesaj oluşturma komutları.",
    },
    "top-10": {
        "title": "Top 10",
        "emoji": "🏅",
        "description": "Top 10 listeleme ve yönetim komutları.",
    },
    "system": {
        "title": "System",
        "emoji": "⚙️",
        "description": "Ping, status, uptime ve yardım sistemi komutları.",
    },
}

MODULE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tryout-system", ("cogs.tryout_system",)),
    ("team-tools", ("cogs.team_tools",)),
    ("verify", ("cogs.verify",)),
    ("roblox", ("cogs.roblox",)),
    ("profile", ("cogs.profile",)),
    ("role-info", ("cogs.role_info",)),
    ("top-10", ("cogs.top_10",)),
    ("announcements", ("cogs.announcement", "cogs.say", "cogs.write")),
    ("blacklist", ("cogs.blacklist",)),
    ("moderation", ("cogs.moderation",)),
    ("general", ("cogs.general",)),
    ("system", ("cogs.system", "cogs.help")),
)

CATEGORY_COLORS: dict[str, discord.Colour] = {
    "home": discord.Colour.blurple(),
    "general": discord.Colour.from_rgb(92, 107, 192),
    "roblox": discord.Colour.from_rgb(0, 162, 255),
    "verify": discord.Colour.from_rgb(46, 204, 113),
    "profile": discord.Colour.from_rgb(155, 89, 182),
    "role-info": discord.Colour.from_rgb(230, 126, 34),
    "team-tools": discord.Colour.from_rgb(52, 152, 219),
    "tryout-system": discord.Colour.from_rgb(241, 196, 15),
    "moderation": discord.Colour.from_rgb(231, 76, 60),
    "blacklist": discord.Colour.from_rgb(149, 165, 166),
    "announcements": discord.Colour.from_rgb(243, 156, 18),
    "top-10": discord.Colour.from_rgb(255, 215, 0),
    "system": discord.Colour.from_rgb(127, 140, 141),
    "detail": discord.Colour.blurple(),
}


def _safe_first_line(text: str | None) -> str:
    if not text:
        return ""
    return str(text).strip().splitlines()[0].strip()


def _clean_description(text: str | None) -> str:
    value = _safe_first_line(text)
    return value or "Açıklama yok."


def _normalize(value: str) -> str:
    return " ".join(
        value.lower()
        .strip()
        .replace("_", "-")
        .split()
    )


def _humanize_bool(value: bool) -> str:
    return "Evet" if value else "Hayır"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _inspect_signature(command: Any) -> str:
    callback = getattr(command, "callback", None)
    if callback is None:
        return ""

    try:
        sig = inspect.signature(callback)
    except (TypeError, ValueError):
        return ""

    tokens: list[str] = []
    for index, param in enumerate(sig.parameters.values()):
        if index == 0 and param.name == "self":
            continue
        if index <= 1 and param.name in {"ctx", "interaction"}:
            continue
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if param.default is inspect._empty:
            tokens.append(f"<{param.name}>")
        else:
            tokens.append(f"[{param.name}]")
    return " ".join(tokens).strip()


@dataclass(slots=True)
class CommandEntry:
    qualified_name: str
    description: str
    category_key: str
    module: str = ""
    cog_name: str = ""
    aliases: tuple[str, ...] = ()
    prefix_name: str | None = None
    slash_name: str | None = None
    guild_only: bool = False
    hidden: bool = False
    prefix_command: Any | None = None
    app_command: Any | None = None

    def key(self, source: str) -> str:
        return f"{source}:{_normalize(self.qualified_name)}"

    def display_name(self) -> str:
        return self.prefix_name or self.slash_name or self.qualified_name

    def has_prefix(self) -> bool:
        return self.prefix_name is not None

    def has_slash(self) -> bool:
        return self.slash_name is not None

    def short_description(self) -> str:
        return self.description or "Açıklama yok."

    def alias_text(self) -> str:
        if not self.aliases:
            return "Yok"
        return ", ".join(f"`{alias}`" for alias in self.aliases)

    def forms(self, prefix: str) -> list[str]:
        items: list[str] = []
        if self.has_prefix():
            items.append(f"`{prefix}{self.prefix_name}`")
        if self.has_slash():
            slash = f"`/{self.slash_name}`"
            if slash not in items:
                items.append(slash)
        if not items:
            items.append(f"`{prefix}{self.qualified_name}`")
        return items

    def forms_text(self, prefix: str) -> str:
        return " · ".join(self.forms(prefix))

    def prefix_usage(self, prefix: str) -> str | None:
        if not self.has_prefix():
            return None
        signature = _inspect_signature(self.prefix_command)
        if signature:
            return f"`{prefix}{self.prefix_name} {signature}`"
        return f"`{prefix}{self.prefix_name}`"

    def slash_usage(self) -> str | None:
        if not self.has_slash():
            return None
        signature = _inspect_signature(self.app_command)
        if signature:
            return f"`/{self.slash_name} {signature}`"
        return f"`/{self.slash_name}`"

    def source_text(self) -> str:
        if self.has_prefix() and self.has_slash():
            return "Prefix + Slash"
        if self.has_prefix():
            return "Prefix"
        if self.has_slash():
            return "Slash"
        return "Bilinmiyor"


@dataclass(slots=True)
class HelpCategory:
    key: str
    title: str
    emoji: str
    description: str
    banner_url: str
    entries: list[CommandEntry] = field(default_factory=list)

    @property
    def command_count(self) -> int:
        return len(self.entries)

    @property
    def page_count(self) -> int:
        if not self.entries:
            return 1
        return max(1, math.ceil(len(self.entries) / PAGE_SIZE))

    def example_invocation(self, prefix: str) -> str:
        if not self.entries:
            return "`-`"
        return self.entries[0].forms_text(prefix)


class HelpRegistry:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.prefix = self._resolve_prefix()
        self.categories: list[HelpCategory] = []
        self._category_by_key: dict[str, HelpCategory] = {}
        self._entry_index: dict[str, CommandEntry] = {}
        self._build()

    def _resolve_prefix(self) -> str:
        prefix = getattr(self.bot, "command_prefix", PREFIX_FALLBACK)

        if isinstance(prefix, str):
            return prefix

        if isinstance(prefix, (list, tuple)):
            for item in prefix:
                if isinstance(item, str) and item:
                    return item

        return PREFIX_FALLBACK

    def _iter_prefix_commands(self) -> Iterable[commands.Command[Any, Any, Any]]:
        return self.bot.walk_commands()

    def _iter_app_commands(self) -> Iterable[Any]:
        tree = getattr(self.bot, "tree", None)
        if tree is None:
            return ()

        walker = getattr(tree, "walk_commands", None)
        if callable(walker):
            return tuple(walker())

        getter = getattr(tree, "get_commands", None)
        if callable(getter):
            return tuple(getter())

        return ()

    def _resolve_category(self, module: str, command_name: str) -> str:
        module = module or ""
        normalized = _normalize(command_name)

        for category_key, modules in MODULE_CATEGORY_RULES:
            if any(pattern in module for pattern in modules):
                return category_key

        if normalized in {"help", "ping", "status", "uptime"}:
            return "system"
        if normalized.startswith("top10"):
            return "top-10"
        if normalized.startswith("role-"):
            return "role-info"
        if normalized in {"verify", "unverify"}:
            return "verify"
        if normalized in {"profile", "my-profile", "profile-2", "profile-preview"}:
            return "profile"
        if normalized in {"user", "id", "avatar", "search", "batch", "avatars"}:
            return "roblox"
        if normalized in {
            "warn", "warnings", "unwarn", "clearwarnings", "note", "notes",
            "removenote", "clearnotes", "timeout", "untimeout", "kick", "ban",
            "unban", "nickname", "purge", "lock", "unlock", "slowmode",
            "history", "stats", "searchuser", "caseinfo", "editreason", "modpanel", "modgif"
        }:
            return "moderation"
        if normalized in {"blacklist", "unblacklist", "blacklistpanel"}:
            return "blacklist"
        if normalized in {"announcement", "write", "say"}:
            return "announcements"
        if normalized in {"etkpanel", "teamer", "teamer-help", "teamer_kapat", "train-announcement", "tryout-announcement", "spar-istek", "spar-kabul", "spar-reddet", "spar-liste", "spar-iptal", "tryout-help"}:
            return "team-tools"
        return "general"

    def _build_prefix_entry(self, command: commands.Command[Any, Any, Any]) -> CommandEntry:
        module = getattr(getattr(command, "callback", None), "__module__", "")
        qualified_name = getattr(command, "qualified_name", command.name)
        description = _clean_description(getattr(command, "help", None) or getattr(command, "brief", None) or getattr(command, "short_doc", None) or getattr(command.callback, "__doc__", None))
        return CommandEntry(
            qualified_name=qualified_name,
            description=description,
            category_key=self._resolve_category(module, qualified_name),
            module=module,
            cog_name=getattr(command, "cog_name", "") or "",
            aliases=tuple(command.aliases or ()),
            prefix_name=qualified_name,
            guild_only=bool(getattr(command, "guild_only", False)),
            hidden=bool(getattr(command, "hidden", False)),
            prefix_command=command,
        )

    def _build_app_entry(self, command: Any) -> CommandEntry:
        module = getattr(getattr(command, "callback", None), "__module__", "")
        qualified_name = getattr(command, "qualified_name", getattr(command, "name", ""))
        description = _clean_description(getattr(command, "description", None) or getattr(command.callback, "__doc__", None))
        return CommandEntry(
            qualified_name=qualified_name,
            description=description,
            category_key=self._resolve_category(module, qualified_name),
            module=module,
            cog_name=getattr(getattr(command, "binding", None), "__class__", type("", (), {})).__name__ if getattr(command, "binding", None) else "",
            aliases=(),
            slash_name=qualified_name,
            guild_only=bool(getattr(command, "guild_only", False)),
            hidden=bool(getattr(command, "hidden", False)),
            app_command=command,
        )

    def _build(self) -> None:
        category_entries: dict[str, dict[str, CommandEntry]] = {key: {} for key in CATEGORY_ORDER}

        for command in self._iter_prefix_commands():
            if getattr(command, "hidden", False):
                continue
            entry = self._build_prefix_entry(command)
            self._merge_entry(category_entries, entry, source="prefix")

        for command in self._iter_app_commands():
            if getattr(command, "hidden", False):
                continue
            entry = self._build_app_entry(command)
            self._merge_entry(category_entries, entry, source="slash")

        categories: list[HelpCategory] = []
        for key in CATEGORY_ORDER:
            meta = CATEGORY_META[key]
            entries = list(category_entries[key].values())
            entries.sort(key=lambda item: item.display_name().lower())
            category = HelpCategory(
                key=key,
                title=meta["title"],
                emoji=meta["emoji"],
                description=meta["description"],
                banner_url=BANNER_URLS.get(key, BANNER_URLS["detail"]),
                entries=entries,
            )
            categories.append(category)
            self._category_by_key[key] = category
            for entry in entries:
                self._index_entry(entry)

        self.categories = categories

    def _index_entry(self, entry: CommandEntry) -> None:
        keys = {
            _normalize(entry.qualified_name),
            _normalize(entry.display_name()),
        }
        for alias in entry.aliases:
            keys.add(_normalize(alias))

        for key in keys:
            self._entry_index[key] = entry

    def _merge_entry(self, category_entries: dict[str, dict[str, CommandEntry]], entry: CommandEntry, *, source: str) -> None:
        category_map = category_entries.setdefault(entry.category_key, {})
        key = _normalize(entry.qualified_name)
        existing = category_map.get(key)

        if existing is None:
            category_map[key] = entry
            return

        if entry.description and len(entry.description) > len(existing.description):
            existing.description = entry.description
        if entry.prefix_name:
            existing.prefix_name = entry.prefix_name
            existing.prefix_command = entry.prefix_command
        if entry.slash_name:
            existing.slash_name = entry.slash_name
            existing.app_command = entry.app_command
        if entry.aliases:
            merged = dict.fromkeys(existing.aliases)
            for alias in entry.aliases:
                merged[_normalize(alias)] = alias
            existing.aliases = tuple(merged.values())
        existing.guild_only = existing.guild_only or entry.guild_only
        existing.hidden = existing.hidden and entry.hidden

    def category(self, key: str) -> HelpCategory | None:
        return self._category_by_key.get(key)

    def entry(self, query: str) -> CommandEntry | None:
        normalized = _normalize(query)
        if not normalized:
            return None
        return self._entry_index.get(normalized)

    def category_for_query(self, query: str) -> HelpCategory | None:
        normalized = _normalize(query)
        if not normalized:
            return None

        direct = self._category_by_key.get(normalized)
        if direct is not None:
            return direct

        for category in self.categories:
            if normalized == _normalize(category.title):
                return category
            if normalized == _normalize(category.key):
                return category
            if normalized in _normalize(category.title):
                return category

        return None

    def best_matches(self, query: str, *, limit: int = 5):
        """
        -            ↓
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
