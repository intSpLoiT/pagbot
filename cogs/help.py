
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

    def best_matches(self, query: str, *, limit: int = 5) -> list[str]:
        normalized = _normalize(query)
        if not normalized:
            return []

        names: list[str] = []
        seen: set[str] = set()

        for category in self.categories:
            for candidate in {category.key, category.title}:
                key = _normalize(candidate)
                if key not in seen:
                    seen.add(key)
                    names.append(candidate)
            for entry in category.entries:
                for candidate in {entry.qualified_name, entry.display_name(), *entry.aliases}:
                    key = _normalize(candidate)
                    if key not in seen:
                        seen.add(key)
                        names.append(candidate)

        return get_close_matches(query, names, n=limit, cutoff=0.25)

    def list_stats(self) -> tuple[int, int, int]:
        total = sum(len(category.entries) for category in self.categories)
        prefix_only = sum(1 for category in self.categories for entry in category.entries if entry.has_prefix() and not entry.has_slash())
        slash_only = sum(1 for category in self.categories for entry in category.entries if entry.has_slash() and not entry.has_prefix())
        both = sum(1 for category in self.categories for entry in category.entries if entry.has_prefix() and entry.has_slash())
        return total, prefix_only, slash_only, both


class HelpSelect(discord.ui.Select):
    def __init__(self, view: "HelpView") -> None:
        self.view_ref = view
        options = [
            discord.SelectOption(
                label=category.title,
                value=category.key,
                emoji=category.emoji,
                description=_truncate(category.description, 100),
            )
            for category in view.registry.categories
            if category.command_count > 0
        ]

        super().__init__(
            placeholder="Bir kategori seç",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.view_ref.ensure_author(interaction):
            return
        self.view_ref.set_category(self.values[0])
        await self.view_ref.refresh(interaction)


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int, registry: HelpRegistry) -> None:
        super().__init__(timeout=TIMEOUT_SECONDS)
        self.bot = bot
        self.author_id = author_id
        self.registry = registry
        self.state: str = "home"
        self.active_category_key: str | None = None
        self.active_entry: CommandEntry | None = None
        self.page_index: int = 0
        self.message: discord.Message | None = None

        self.select = HelpSelect(self)
        self.add_item(self.select)

    async def ensure_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message("Bu yardım menüsü sana ait değil.", ephemeral=True)
        return False

    def set_home(self) -> None:
        self.state = "home"
        self.active_category_key = None
        self.active_entry = None
        self.page_index = 0

    def set_category(self, category_key: str) -> None:
        self.state = "category"
        self.active_category_key = category_key
        self.active_entry = None
        self.page_index = 0

    def set_entry(self, entry: CommandEntry) -> None:
        self.state = "detail"
        self.active_category_key = entry.category_key
        self.active_entry = entry
        self.page_index = 0

    def current_category(self) -> HelpCategory | None:
        if not self.active_category_key:
            return None
        return self.registry.category(self.active_category_key)

    def current_entries(self) -> list[CommandEntry]:
        category = self.current_category()
        if not category:
            return []
        start = self.page_index * PAGE_SIZE
        end = start + PAGE_SIZE
        return category.entries[start:end]

    def _author_thumbnail(self) -> str | None:
        user = getattr(self.bot, "user", None)
        if user is None:
            return None
        return user.display_avatar.url

    def _base_embed(self, *, title: str, description: str, key: str) -> discord.Embed:
        embed = PAGEmbeds.custom(
            title=title,
            description=description,
            color=CATEGORY_COLORS.get(key, discord.Colour.blurple()),
            thumbnail_url=self._author_thumbnail(),
            image_url=BANNER_URLS.get(key, BANNER_URLS["detail"]),
        )
        embed.timestamp = discord.utils.utcnow()
        return embed

    def _home_embed(self) -> discord.Embed:
        total, prefix_only, slash_only, both = self.registry.list_stats()
        categories_with_commands = [category for category in self.registry.categories if category.command_count > 0]

        description = (
            "Bu panel yalnızca projede gerçekten kayıtlı komutları gösterir.\n"
            f"Prefix: `{self.registry.prefix}`\n"
            "Bir kategori seçebilir veya `!help komut` şeklinde detay sayfası açabilirsin."
        )

        embed = self._base_embed(title="⚔️ PAG Command Center", description=description, key="home")
        embed.clear_fields()

        summary_lines = [
            f"• {category.emoji} **{category.title}** — `{category.command_count}` komut • örnek: {category.example_invocation(self.registry.prefix)}"
            for category in categories_with_commands
        ]
        if summary_lines:
            embed.add_field(
                name="Kategoriler",
                value="\n".join(summary_lines)[:1024],
                inline=False,
            )

        embed.add_field(
            name="Komut Özeti",
            value=(
                f"Toplam: `{total}`\n"
                f"Prefix-only: `{prefix_only}`\n"
                f"Slash-only: `{slash_only}`\n"
                f"Hybrid: `{both}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Kullanım",
            value=(
                f"`{self.registry.prefix}help`\n"
                f"`{self.registry.prefix}help moderation`\n"
                f"`{self.registry.prefix}help warn`"
            ),
            inline=True,
        )

        embed.set_footer(text="Gerçek komutlar • Gerçek açıklamalar • Fake yok")
        return embed

    def _category_embed(self, category: HelpCategory) -> discord.Embed:
        start = self.page_index * PAGE_SIZE
        end = start + PAGE_SIZE
        entries = category.entries[start:end]
        description = (
            f"{category.description}\n"
            f"Prefix: `{self.registry.prefix}`\n"
            f"Sayfa: `{self.page_index + 1}/{category.page_count}`"
        )

        embed = self._base_embed(title=f"{category.emoji} {category.title}", description=description, key=category.key)
        embed.clear_fields()

        if not entries:
            embed.add_field(
                name="Komutlar",
                value="Bu kategoride görünür komut yok.",
                inline=False,
            )
        else:
            for entry in entries:
                forms = entry.forms_text(self.registry.prefix)
                value_lines = [
                    entry.short_description(),
                    f"**Komut:** {forms}",
                ]
                if entry.aliases:
                    value_lines.append(f"**Alias:** {entry.alias_text()}")
                if entry.guild_only:
                    value_lines.append("**Sunucu:** Sadece sunucuda kullanılabilir.")
                embed.add_field(
                    name=entry.display_name(),
                    value="\n".join(value_lines)[:1024],
                    inline=False,
                )

        embed.set_footer(
            text=f"Sayfa {self.page_index + 1}/{category.page_count} • {category.command_count} komut",
        )
        return embed

    def _entry_embed(self, entry: CommandEntry) -> discord.Embed:
        description = entry.short_description()
        embed = self._base_embed(title=f"🔎 {entry.display_name()}", description=description, key=entry.category_key)
        embed.clear_fields()

        embed.add_field(
            name="Komut Formları",
            value="\n".join(entry.forms(self.registry.prefix)),
            inline=False,
        )

        prefix_usage = entry.prefix_usage(self.registry.prefix)
        slash_usage = entry.slash_usage()

        if prefix_usage or slash_usage:
            usage_value = "\n".join(
                item for item in [prefix_usage, slash_usage] if item
            )
            embed.add_field(
                name="Kullanım",
                value=usage_value,
                inline=False,
            )

        embed.add_field(
            name="Kategori",
            value=f"{CATEGORY_META.get(entry.category_key, {'title': entry.category_key}).get('title', entry.category_key)}",
            inline=True,
        )

        embed.add_field(
            name="Kaynak",
            value=entry.source_text(),
            inline=True,
        )

        embed.add_field(
            name="Sunucu İzni",
            value=_humanize_bool(entry.guild_only),
            inline=True,
        )

        embed.add_field(
            name="Aliaslar",
            value=entry.alias_text(),
            inline=False,
        )

        if entry.module:
            embed.add_field(
                name="Modül",
                value=f"`{entry.module}`",
                inline=False,
            )

        embed.set_footer(
            text=f"Prefix: {self.registry.prefix} • Gerçek komut detayı",
        )
        return embed

    def render(self) -> discord.Embed:
        if self.state == "detail" and self.active_entry is not None:
            return self._entry_embed(self.active_entry)
        if self.state == "category":
            category = self.current_category()
            if category is not None:
                return self._category_embed(category)
        return self._home_embed()

    def _update_button_states(self) -> None:
        category = self.current_category()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "help_home":
                    child.disabled = self.state == "home"
                elif child.custom_id == "help_prev":
                    child.disabled = self.state != "category" or category is None or self.page_index <= 0
                elif child.custom_id == "help_next":
                    child.disabled = self.state != "category" or category is None or self.page_index >= category.page_count - 1
                elif child.custom_id == "help_close":
                    child.disabled = False

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._update_button_states()
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def go_home(self, interaction: discord.Interaction) -> None:
        self.set_home()
        await self.refresh(interaction)

    async def go_prev(self, interaction: discord.Interaction) -> None:
        if self.state != "category":
            return await interaction.response.send_message("Bu menüde sayfa yok.", ephemeral=True)
        if self.page_index <= 0:
            return
        self.page_index -= 1
        await self.refresh(interaction)

    async def go_next(self, interaction: discord.Interaction) -> None:
        category = self.current_category()
        if self.state != "category" or category is None:
            return await interaction.response.send_message("Bu menüde sayfa yok.", ephemeral=True)
        if self.page_index >= category.page_count - 1:
            return
        self.page_index += 1
        await self.refresh(interaction)

    async def close(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Item):
                item.disabled = True
        await interaction.response.edit_message(embed=self.render(), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Item):
                item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


class HelpHomeButton(discord.ui.Button):
    def __init__(self, view: HelpView) -> None:
        super().__init__(
            label="Ana Sayfa",
            style=discord.ButtonStyle.primary,
            emoji="🏠",
            custom_id="help_home",
            row=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.view_ref.ensure_author(interaction):
            return
        await self.view_ref.go_home(interaction)


class HelpPrevButton(discord.ui.Button):
    def __init__(self, view: HelpView) -> None:
        super().__init__(
            label="Önceki",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️",
            custom_id="help_prev",
            row=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.view_ref.ensure_author(interaction):
            return
        await self.view_ref.go_prev(interaction)


class HelpNextButton(discord.ui.Button):
    def __init__(self, view: HelpView) -> None:
        super().__init__(
            label="Sonraki",
            style=discord.ButtonStyle.secondary,
            emoji="➡️",
            custom_id="help_next",
            row=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.view_ref.ensure_author(interaction):
            return
        await self.view_ref.go_next(interaction)


class HelpCloseButton(discord.ui.Button):
    def __init__(self, view: HelpView) -> None:
        super().__init__(
            label="Kapat",
            style=discord.ButtonStyle.danger,
            emoji="✖️",
            custom_id="help_close",
            row=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.view_ref.ensure_author(interaction):
            return
        await self.view_ref.close(interaction)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = getattr(bot, "logger", logging.getLogger("PAG.Help"))

    def build_registry(self) -> HelpRegistry:
        return HelpRegistry(self.bot)

    async def _send_panel(self, destination: Any, author_id: int, registry: HelpRegistry, *, entry: CommandEntry | None = None, category: HelpCategory | None = None) -> None:
        view = HelpView(self.bot, author_id, registry)
        view.add_item(HelpHomeButton(view))
        view.add_item(HelpPrevButton(view))
        view.add_item(HelpNextButton(view))
        view.add_item(HelpCloseButton(view))

        if entry is not None:
            view.set_entry(entry)
        elif category is not None:
            view.set_category(category.key)
        else:
            view.set_home()

        view._update_button_states()
        embed = view.render()

        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=embed, view=view)
            message = await destination.original_response()
            view.message = message
            return

        message = await destination.send(embed=embed, view=view)
        view.message = message

    async def _send_query_result(self, destination: Any, query: str) -> None:
        registry = self.build_registry()
        normalized = query.strip()

        entry = registry.entry(normalized)
        if entry is not None:
            await self._send_panel(destination, getattr(destination, "user", getattr(destination, "author", None)).id, registry, entry=entry)
            return

        category = registry.category_for_query(normalized)
        if category is not None:
            await self._send_panel(destination, getattr(destination, "user", getattr(destination, "author", None)).id, registry, category=category)
            return

        suggestions = registry.best_matches(normalized)

        embed = PAGEmbeds.warning(
            "Komut Bulunamadı",
            (
                f"`{normalized}` için eşleşen gerçek komut bulunamadı.\n"
                f"Prefix: `{registry.prefix}`"
            ),
        )
        embed.set_thumbnail(url=self._author_thumbnail())
        embed.set_image(url=BANNER_URLS["detail"])
        if suggestions:
            embed.add_field(
                name="Öneriler",
                value="\n".join(f"`{item}`" for item in suggestions[:5]),
                inline=False,
            )
        embed.set_footer(text="Gerçek komutları görmek için kategori seçebilir veya doğru komut adını yazabilirsin.")

        if isinstance(destination, discord.Interaction):
            await destination.response.send_message(embed=embed, ephemeral=True)
        else:
            await destination.reply(embed=embed, mention_author=False)

    def _author_thumbnail(self) -> str | None:
        user = getattr(self.bot, "user", None)
        if user is None:
            return None
        return user.display_avatar.url

    @commands.command(name="help", aliases=("h", "commands"))
    async def help_prefix(self, ctx: commands.Context, *, query: str | None = None) -> None:
        registry = self.build_registry()

        if not query:
            await self._send_panel(ctx, ctx.author.id, registry)
            return

        normalized = query.strip()
        entry = registry.entry(normalized)
        if entry is not None:
            await self._send_panel(ctx, ctx.author.id, registry, entry=entry)
            return

        category = registry.category_for_query(normalized)
        if category is not None:
            await self._send_panel(ctx, ctx.author.id, registry, category=category)
            return

        suggestions = registry.best_matches(normalized)

        embed = PAGEmbeds.warning(
            "Komut Bulunamadı",
            (
                f"`{normalized}` için eşleşen gerçek komut bulunamadı.\n"
                f"Prefix: `{registry.prefix}`"
            ),
        )
        embed.set_thumbnail(url=self._author_thumbnail())
        embed.set_image(url=BANNER_URLS["detail"])

        if suggestions:
            embed.add_field(
                name="Öneriler",
                value="\n".join(f"`{item}`" for item in suggestions[:5]),
                inline=False,
            )

        embed.set_footer(text="Gerçek komutları görmek için kategori seçebilir veya doğru komut adını yazabilirsin.")
        await ctx.reply(embed=embed, mention_author=False)

    @app_commands.command(name="help", description="PAG Bot yardım panelini açar.")
    @app_commands.describe(query="Komut veya kategori adı.")
    async def help_slash(self, interaction: discord.Interaction, query: str | None = None) -> None:
        registry = self.build_registry()

        if not query:
            await self._send_panel(interaction, interaction.user.id, registry)
            return

        normalized = query.strip()
        entry = registry.entry(normalized)
        if entry is not None:
            await self._send_panel(interaction, interaction.user.id, registry, entry=entry)
            return

        category = registry.category_for_query(normalized)
        if category is not None:
            await self._send_panel(interaction, interaction.user.id, registry, category=category)
            return

        suggestions = registry.best_matches(normalized)

        embed = PAGEmbeds.warning(
            "Komut Bulunamadı",
            (
                f"`{normalized}` için eşleşen gerçek komut bulunamadı.\n"
                f"Prefix: `{registry.prefix}`"
            ),
        )
        embed.set_thumbnail(url=self._author_thumbnail())
        embed.set_image(url=BANNER_URLS["detail"])

        if suggestions:
            embed.add_field(
                name="Öneriler",
                value="\n".join(f"`{item}`" for item in suggestions[:5]),
                inline=False,
            )

        embed.set_footer(text="Gerçek komutları görmek için kategori seçebilir veya doğru komut adını yazabilirsin.")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
