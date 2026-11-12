"""PAG Role Intelligence — production-oriented Discord.py Cog.

Drop-in replacement for ``cogs/role_info.py`` in intSpLoiT/pagbot.

Prefix commands
---------------
    !roleinfo [@role]      Open the official role directory.
    !rolemembers @role     Browse members of an official role.
    !rolestats             Show official role statistics.

Guild application commands
--------------------------
    /role-info [role]
    /role-members role
    /role-stats

Design guarantees
-----------------
* Only explicitly allowlisted PAG roles are exposed.
* Empty roles and Discord-managed roles are omitted.
* Decorative Unicode role names are normalized before matching.
* Member counts clearly disclose incomplete member caches.
* Member-cache refreshes are bounded and serialized per Cog instance.
* Every interactive control is restricted to the command invoker.
* Views have finite lifetimes, bounded pages and error handlers.
* Slash commands are registered in the PAG guild configured by
  ``DISCORD_GUILD_ID``; this matches PAGBot's guild-only sync strategy.
* The three category GIFs keep their original filenames and are uploaded as
  animated custom guild emojis on first use. Uploaded emojis are reused after
  restarts; failed uploads fall back to Unicode without breaking commands.
* No database, environment mutation or additional third-party package is
  required. discord.py and the Python standard library are sufficient.

Important
---------
The bot's Members intent must be enabled in both code and the Discord Developer
Portal. PAGBot already enables ``intents.members``. If Discord does not permit
member chunking, displayed counts are explicitly marked as cache-based.

For animated category emojis, grant the bot Manage Expressions (Manage Emojis)
and ensure the guild has an available animated emoji slot. Each source GIF is
128x128 and below Discord's 256 KiB per-emoji upload limit. If these conditions
are not met, the panel remains operational and displays Unicode fallbacks.

Role descriptions explain intended PAG responsibilities. They do not grant,
verify or imply Discord permissions; the server's actual role configuration
remains authoritative.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Sequence

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================================
# Configuration
# ============================================================================

LOGGER = logging.getLogger("PAG.RoleInfo")
ASSET_DIR: Final[Path] = Path(__file__).resolve().with_name("role_info_assets")

COLOR_PURPLE: Final[discord.Color] = discord.Color.from_rgb(104, 64, 172)
COLOR_GOLD: Final[discord.Color] = discord.Color.from_rgb(222, 181, 91)
COLOR_BLUE: Final[discord.Color] = discord.Color.from_rgb(76, 134, 205)

CHUNK_TIMEOUT_SECONDS: Final[float] = 10.0
MAX_AUTOMATIC_CHUNK_MEMBERS: Final[int] = 5_000
ROLE_VIEW_TIMEOUT_SECONDS: Final[float] = 300.0
MEMBER_VIEW_TIMEOUT_SECONDS: Final[float] = 180.0
MEMBERS_PER_PAGE: Final[int] = 20
ROLES_PER_CATEGORY_PREVIEW: Final[int] = 8

CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "leadership",
    "security",
    "community",
)

CATEGORY_META: Final[dict[str, tuple[str, str, str, discord.Color]]] = {
    "leadership": (
        "Leadership",
        "👑",
        "Authority • Direction • Continuity",
        COLOR_GOLD,
    ),
    "security": (
        "Security & Support",
        "🛡️",
        "Protection • Moderation • Member Support",
        COLOR_BLUE,
    ),
    "community": (
        "Community & Partners",
        "✦",
        "Recognition • Membership • Partnerships",
        COLOR_PURPLE,
    ),
}

# Source GIF filenames are intentionally stable. They are optimized 128x128
# animated emoji assets and are uploaded to the PAG guild on first use.
BANNER_FILES: Final[dict[str, str]] = {
    "leadership": "roleinfo_leadership.gif",
    "security": "roleinfo_security.gif",
    "community": "roleinfo_community.gif",
}

CATEGORY_EMOJI_NAMES: Final[dict[str, str]] = {
    "leadership": "pag_role_leadership",
    "security": "pag_role_security",
    "community": "pag_role_community",
}

MAX_DISCORD_EMOJI_BYTES: Final[int] = 256 * 1024


# ============================================================================
# Domain model and curated role definitions
# ============================================================================

@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """Curated public-facing metadata for one official PAG role."""

    category: str
    title: str
    description: str
    emoji: str


@dataclass(frozen=True, slots=True)
class RoleRecord:
    """A Discord role enriched with its PAG metadata and cached member count."""

    role: discord.Role
    definition: RoleDefinition
    member_count: int

    @property
    def position(self) -> int:
        return self.role.position


@dataclass(frozen=True, slots=True)
class RoleSnapshot:
    """Immutable result of one role-directory collection pass."""

    records: tuple[RoleRecord, ...]
    counts_authoritative: bool
    count_source: str
    member_cache_complete: bool
    cached_members: int
    expected_members: int | None

    @property
    def assignment_count(self) -> int:
        # This is intentionally called assignments, not unique members:
        # one member may hold multiple official roles.
        return sum(record.member_count for record in self.records)


ROLE_DEFINITIONS: Final[dict[str, RoleDefinition]] = {
    # Leadership and operational administration
    "emperor": RoleDefinition(
        "leadership", "Emperor",
        "The highest leadership tier in the PAG structure. It represents strategic direction, oversight and continuity across the community.",
        "👑",
    ),
    "temporary owner": RoleDefinition(
        "leadership", "Temporary Owner",
        "A delegated leadership role used for a defined period when operational continuity or founder coverage is required.",
        "⌛",
    ),
    "co owner": RoleDefinition(
        "leadership", "Co-Owner",
        "A senior leadership position that supports ownership decisions and coordinates important PAG operations.",
        "⚜️",
    ),
    "executive": RoleDefinition(
        "leadership", "Executive",
        "Coordinates high-level operations, staff alignment and the organized delivery of PAG decisions.",
        "◆",
    ),
    "left wing": RoleDefinition(
        "leadership", "Left Wing",
        "A leadership wing that coordinates its assigned responsibilities and supports operational continuity.",
        "◀",
    ),
    "right wing": RoleDefinition(
        "leadership", "Right Wing",
        "A leadership wing that coordinates its assigned responsibilities and supports operational continuity.",
        "▶",
    ),
    "head admin": RoleDefinition(
        "leadership", "Head Admin",
        "The senior administration tier responsible for coordinating administrative work and maintaining consistent staff standards.",
        "🏛️",
    ),
    "admin": RoleDefinition(
        "leadership", "Admin",
        "Trusted staff who help manage server operations and apply the community's established rules.",
        "🔰",
    ),
    "tester manager": RoleDefinition(
        "leadership", "Tester Manager",
        "Coordinates testing activity, organizes tester feedback and prepares system changes for review.",
        "🧪",
    ),
    "hoster": RoleDefinition(
        "leadership", "Hoster",
        "Supports the organization and hosting of PAG activities, sessions and community events.",
        "🎙️",
    ),
    "tryout hoster": RoleDefinition(
        "leadership", "Tryout Hoster",
        "Coordinates tryout sessions and helps keep the evaluation process organized and consistent.",
        "🏁",
    ),

    # Security, moderation and support
    "pag security": RoleDefinition(
        "security", "PAG Security",
        "The PAG security identity for designated protection and security-system operations. Actual access is determined only by Discord role permissions and channel overwrites.",
        "🛡️",
    ),
    "senior moderator": RoleDefinition(
        "security", "Senior Moderator",
        "A senior moderation tier that supports complex cases, staff guidance and consistent enforcement of community standards.",
        "⚖️",
    ),
    "moderator": RoleDefinition(
        "security", "Moderator",
        "Helps maintain a respectful server environment, reviews reported issues and handles moderation tasks within assigned permissions.",
        "🔨",
    ),
    "trial moderator": RoleDefinition(
        "security", "Trial Moderator",
        "A training and evaluation position for learning PAG procedures and demonstrating reliable moderation practice.",
        "🛡️",
    ),
    "ticketyetkilisi": RoleDefinition(
        "security", "Ticket Staff",
        "Supports the ticket workflow by reviewing member requests and directing them to the appropriate staff team.",
        "🎫",
    ),
    "sailor yetkilisi": RoleDefinition(
        "security", "Sailor Staff",
        "The designated staff contact for Sailor-related member questions and coordination.",
        "⚓",
    ),
    "rivals yetkilisi": RoleDefinition(
        "security", "Rivals Staff",
        "The designated staff contact for Rivals-related member questions and coordination.",
        "🎯",
    ),

    # Community, recognition and partner groups
    "ally owner": RoleDefinition(
        "community", "Ally Owner",
        "The designated contact for an allied community, supporting partner coordination and communication with PAG.",
        "🤝",
    ),
    "vip": RoleDefinition(
        "community", "VIP",
        "A PAG recognition role for members with VIP status. It does not imply permissions beyond those configured in Discord.",
        "👑",
    ),
    "prime tier 1": RoleDefinition(
        "community", "Prime Tier 1",
        "A Prime progression tier used by PAG to recognize community or competitive standing.",
        "✦",
    ),
    "prime tier 2": RoleDefinition(
        "community", "Prime Tier 2",
        "A Prime progression tier used by PAG to recognize community or competitive standing.",
        "✦",
    ),
    "prime tier 3": RoleDefinition(
        "community", "Prime Tier 3",
        "A Prime progression tier used by PAG to recognize community or competitive standing.",
        "✦",
    ),
    "prime tier 4": RoleDefinition(
        "community", "Prime Tier 4",
        "A Prime progression tier used by PAG to recognize community or competitive standing.",
        "✦",
    ),
    "prime tier 5": RoleDefinition(
        "community", "Prime Tier 5",
        "A Prime progression tier used by PAG to recognize community or competitive standing.",
        "✦",
    ),
    "tsb": RoleDefinition(
        "community", "TSB",
        "A community group label for members associated with TSB activities.",
        "⚔️",
    ),
    "sailor": RoleDefinition(
        "community", "Sailor",
        "A community group label for members associated with Sailor activities.",
        "⚓",
    ),
    "rivals": RoleDefinition(
        "community", "Rivals",
        "A community group label for members associated with Rivals activities.",
        "🎯",
    ),
    "brainrot games": RoleDefinition(
        "community", "Brainrot Games",
        "A community interest role for members who follow Brainrot Games activity.",
        "🎮",
    ),
    "fc": RoleDefinition(
        "community", "FC",
        "A community group label for members associated with FC activities.",
        "⚽",
    ),
    "blox fruits": RoleDefinition(
        "community", "Blox Fruits",
        "A community interest role for members who follow Blox Fruits activity.",
        "🍈",
    ),
}


def normalize_role_name(name: str) -> str:
    """Normalize decorated/stylized Unicode role names for exact matching.

    NFKD handles mathematical bold/italic/script alphabets used in PAG's role
    names. Punctuation, ornaments and decorative symbols are discarded while
    meaningful ASCII letters and digits are retained.
    """

    if not isinstance(name, str):
        return ""

    normalized = unicodedata.normalize("NFKD", name).casefold()
    normalized = normalized.replace("_", " ")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return " ".join(ascii_text.split())


# ============================================================================
# Role collection and cache handling
# ============================================================================

class RoleAnalyzer:
    """Collect allowlisted roles using Discord's role-count API when available."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._chunk_lock = asyncio.Lock()

    async def _refresh_member_cache(self, guild: discord.Guild) -> bool:
        """Attempt a bounded member chunk for commands that need member names."""

        expected = guild.member_count
        if guild.chunked:
            return True
        if expected is None or expected > MAX_AUTOMATIC_CHUNK_MEMBERS:
            return False

        try:
            async with self._chunk_lock:
                if not guild.chunked:
                    await asyncio.wait_for(
                        guild.chunk(cache=True),
                        timeout=CHUNK_TIMEOUT_SECONDS,
                    )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Role directory: member-cache refresh timed out for guild %s.",
                guild.id,
            )
        except (discord.Forbidden, discord.HTTPException, discord.ClientException) as error:
            self.logger.warning(
                "Role directory: member-cache refresh unavailable for guild %s: %s",
                guild.id,
                error,
            )
        except Exception:
            self.logger.exception(
                "Unexpected member-cache refresh error for guild %s.",
                guild.id,
            )

        expected = guild.member_count
        return bool(guild.chunked) and (
            expected is None or len(guild.members) >= expected
        )

    async def collect(
        self,
        guild: discord.Guild,
        *,
        load_member_cache: bool = False,
    ) -> RoleSnapshot:
        """Build a role snapshot with exact server-side counts when supported.

        discord.py 2.7+ exposes ``Guild.role_member_counts()``, which obtains
        counts directly from Discord and does not rely on the local Member
        cache. Older versions fall back to a bounded Guild.chunk() operation.
        Member names are only needed by ``!rolemembers`` and can be loaded
        separately so ordinary role panels stay lightweight.
        """

        role_counts: dict[int, int] = {}
        counts_authoritative = False
        count_source = "Member-cache counts"

        count_method = getattr(guild, "role_member_counts", None)
        bot_member = guild.me
        bot_permissions = (
            bot_member.guild_permissions if bot_member is not None else None
        )
        can_read_role_counts = bool(
            bot_permissions is not None
            and (bot_permissions.manage_roles or bot_permissions.administrator)
        )
        if callable(count_method) and can_read_role_counts:
            try:
                raw_counts = await asyncio.wait_for(
                    count_method(),
                    timeout=CHUNK_TIMEOUT_SECONDS,
                )
                for role_key, count in raw_counts.items():
                    role_id = getattr(role_key, "id", None)
                    if role_id is None:
                        continue
                    try:
                        role_counts[int(role_id)] = max(0, int(count))
                    except (TypeError, ValueError):
                        self.logger.warning(
                            "Ignoring invalid member count for role ID %s in guild %s.",
                            role_id, guild.id,
                        )
                counts_authoritative = True
                count_source = "Discord role-count API · authoritative counts"
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Discord role-count API timed out for guild %s; using cache fallback.",
                    guild.id,
                )
            except (discord.Forbidden, discord.HTTPException, discord.ClientException) as error:
                self.logger.warning(
                    "Discord role-count API unavailable for guild %s: %s",
                    guild.id, error,
                )
            except Exception:
                self.logger.exception(
                    "Unexpected role-count API error for guild %s.", guild.id
                )
        elif callable(count_method) and not can_read_role_counts:
            self.logger.debug(
                "Skipping Discord role-count API for guild %s: bot lacks Manage Roles; "
                "using member-cache fallback.",
                guild.id,
            )

        # Counts can be fetched without caching members on discord.py 2.7+.
        # For older versions, or when the endpoint fails, refresh the cache
        # before deriving fallback counts. Member-name browsing also requires
        # this cache refresh where the guild is reasonably sized.
        needs_cache = (not counts_authoritative) or load_member_cache
        member_cache_complete = bool(guild.chunked)
        if needs_cache and not member_cache_complete:
            member_cache_complete = await self._refresh_member_cache(guild)

        cached_members = len(guild.members)
        expected_members = guild.member_count
        member_cache_complete = member_cache_complete or (
            bool(guild.chunked)
            and (expected_members is None or cached_members >= expected_members)
        )

        if not counts_authoritative:
            role_counts = {role.id: len(role.members) for role in guild.roles}
            count_source = (
                "Complete member-cache counts"
                if member_cache_complete
                else "Partial member-cache counts"
            )

        records: list[RoleRecord] = []
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue

            definition = ROLE_DEFINITIONS.get(normalize_role_name(role.name))
            if definition is None:
                continue

            member_count = role_counts.get(role.id, 0)
            if member_count <= 0:
                continue

            records.append(
                RoleRecord(
                    role=role,
                    definition=definition,
                    member_count=member_count,
                )
            )

        category_rank = {name: index for index, name in enumerate(CATEGORY_ORDER)}
        records.sort(
            key=lambda item: (
                category_rank.get(item.definition.category, len(CATEGORY_ORDER)),
                -item.position,
                item.definition.title.casefold(),
                item.role.id,
            )
        )

        return RoleSnapshot(
            records=tuple(records),
            counts_authoritative=counts_authoritative,
            count_source=count_source,
            member_cache_complete=member_cache_complete,
            cached_members=cached_members,
            expected_members=expected_members,
        )


# ============================================================================
# Shared UI utilities
# ============================================================================

def _escape_role_name(role: discord.Role) -> str:
    return discord.utils.escape_markdown(role.name)


def _cache_status(snapshot: RoleSnapshot) -> str:
    if snapshot.counts_authoritative:
        return snapshot.count_source
    if snapshot.member_cache_complete:
        return "Counts from complete member cache"
    if snapshot.expected_members is None:
        return "Member-cache counts · completeness unknown"
    return (
        f"Partial member-cache counts · {snapshot.cached_members:,}/"
        f"{snapshot.expected_members:,} members cached"
    )


def _category_for(records: Iterable[RoleRecord], role_id: int) -> tuple[str | None, int]:
    for category in CATEGORY_ORDER:
        category_records = [
            record for record in records
            if record.definition.category == category
        ]
        for index, record in enumerate(category_records):
            if record.role.id == role_id:
                return category, index
    return None, 0


# ============================================================================
# Role directory view
# ============================================================================

class RoleCategorySelect(discord.ui.Select):
    """Select component for switching between official PAG divisions."""

    def __init__(self, view: "RoleInfoView") -> None:
        self.role_view = view
        options: list[discord.SelectOption] = []

        for category in CATEGORY_ORDER:
            items = view.roles_by_category.get(category, ())
            if not items:
                continue
            title, fallback_emoji, _, _ = CATEGORY_META[category]
            emoji = view.category_emojis.get(category) or fallback_emoji
            options.append(
                discord.SelectOption(
                    label=title,
                    value=category,
                    emoji=emoji,
                    description=f"Browse {len(items)} active role(s).",
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No active official roles",
                    value="none",
                    description="No active allowlisted roles were found.",
                )
            )

        super().__init__(
            placeholder="Choose a PAG division...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            disabled=not bool(view.snapshot.records),
            custom_id="pag_role_category",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        if selected == "none":
            await interaction.response.defer()
            return

        await self.role_view.change_category(interaction, selected)


class RoleInfoView(discord.ui.View):
    """Owner-scoped interactive browser for the official PAG role directory."""

    def __init__(
        self,
        *,
        owner_id: int,
        snapshot: RoleSnapshot,
        initial_role_id: int | None = None,
        category_emojis: dict[str, discord.Emoji] | None = None,
    ) -> None:
        super().__init__(timeout=ROLE_VIEW_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.snapshot = snapshot
        self.category_emojis = dict(category_emojis or {})
        self.roles_by_category: dict[str, list[RoleRecord]] = defaultdict(list)
        for record in snapshot.records:
            self.roles_by_category[record.definition.category].append(record)

        self.active_category: str | None = None
        self.page = 0
        self.message: discord.Message | discord.InteractionMessage | None = None
        self._state_lock = asyncio.Lock()

        if initial_role_id is not None:
            self.active_category, self.page = _category_for(
                snapshot.records,
                initial_role_id,
            )

        self.add_item(RoleCategorySelect(self))
        self.refresh_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This role directory belongs to the member who opened it.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return False
        return True

    @property
    def current_roles(self) -> list[RoleRecord]:
        if self.active_category is None:
            return []
        return self.roles_by_category.get(self.active_category, [])

    @property
    def current_record(self) -> RoleRecord | None:
        records = self.current_roles
        if not records:
            return None
        self.page = max(0, min(self.page, len(records) - 1))
        return records[self.page]

    def category_emoji(self, category: str) -> discord.Emoji | str:
        """Return the uploaded animated emoji, or the Unicode fallback."""
        custom_emoji = self.category_emojis.get(category)
        if custom_emoji is not None:
            return custom_emoji
        return CATEGORY_META[category][1]

    def category_emoji_text(self, category: str) -> str:
        """Return Discord's renderable custom-emoji token or Unicode fallback."""
        return str(self.category_emoji(category))

    def refresh_controls(self) -> None:
        records = self.current_roles
        last_page = max(0, len(records) - 1)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "pag_role_previous":
                    item.disabled = not records or self.page <= 0
                elif item.custom_id == "pag_role_next":
                    item.disabled = not records or self.page >= last_page
                elif item.custom_id == "pag_role_overview":
                    item.disabled = self.active_category is None

    def create_embed(self) -> discord.Embed:
        if self.active_category is None or self.current_record is None:
            return self._create_overview_embed()
        return self._create_role_embed(self.current_record)

    def _create_overview_embed(self) -> discord.Embed:
        snapshot = self.snapshot
        embed = discord.Embed(
            title=f"{self.category_emoji_text('leadership')}  PAG  •  ROLE INTELLIGENCE",
            description=(
                "**Official role directory**\n"
                "A curated overview of PAG leadership, security and community roles.\n\n"
                "Choose a division below to inspect its active roles."
            ),
            color=COLOR_PURPLE,
        )
        embed.add_field(
            name="ACTIVE OFFICIAL ROLES",
            value=f"`{len(snapshot.records):,}`",
            inline=True,
        )
        embed.add_field(
            name="ROLE ASSIGNMENTS",
            value=f"`{snapshot.assignment_count:,}`",
            inline=True,
        )
        embed.add_field(
            name="ACTIVE DIVISIONS",
            value=f"`{sum(bool(self.roles_by_category.get(key)) for key in CATEGORY_ORDER):,}`",
            inline=True,
        )

        for category in CATEGORY_ORDER:
            records = self.roles_by_category.get(category, [])
            if not records:
                continue
            title, _fallback_emoji, summary, _ = CATEGORY_META[category]
            emoji = self.category_emoji_text(category)
            lines = [
                f"{record.definition.emoji} **{_escape_role_name(record.role)}** · `{record.member_count:,}`"
                for record in records[:ROLES_PER_CATEGORY_PREVIEW]
            ]
            if len(records) > ROLES_PER_CATEGORY_PREVIEW:
                lines.append(
                    f"*Plus {len(records) - ROLES_PER_CATEGORY_PREVIEW} more role(s).*"
                )
            embed.add_field(
                name=f"{emoji}  {title}  ·  {len(records)} active",
                value="\n".join(lines) if lines else summary,
                inline=False,
            )

        if not snapshot.records:
            embed.add_field(
                name="No active official roles",
                value=(
                    "No recognized PAG staff, security or community roles currently "
                    "have cached members. Empty and unrelated roles are hidden."
                ),
                inline=False,
            )

        cache_note = _cache_status(snapshot)
        emoji_note = f"Animated division emojis: {len(self.category_emojis)}/3"
        embed.set_footer(text=f"PAG CORE  •  ROLE INTELLIGENCE  •  {cache_note}  •  {emoji_note}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    def _create_role_embed(self, record: RoleRecord) -> discord.Embed:
        role = record.role
        definition = record.definition
        category_title, _fallback_emoji, _, category_color = CATEGORY_META[definition.category]
        category_emoji = self.category_emoji_text(definition.category)
        embed_color = role.color if role.color.value else category_color

        embed = discord.Embed(
            title=f"{category_emoji}  {definition.emoji}  {definition.title}",
            description=(
                f"{role.mention}\n\n"
                f"{definition.description}\n\n"
                "*Role purpose is descriptive only. Actual permissions are controlled "
                "by Discord role settings and channel overwrites.*"
            ),
            color=embed_color,
        )
        embed.add_field(name="MEMBERS", value=f"`{record.member_count:,}`", inline=True)
        embed.add_field(name="HIERARCHY", value=f"`#{record.position:,}`", inline=True)
        embed.add_field(
            name="DIVISION",
            value=f"{category_emoji} `{category_title}`",
            inline=True,
        )
        embed.add_field(name="ROLE ID", value=f"`{role.id}`", inline=True)
        embed.add_field(
            name="ROLE COLOR",
            value=f"`#{role.color.value:06X}`" if role.color.value else "`Default`",
            inline=True,
        )
        embed.add_field(
            name="DIVISION POSITION",
            value=f"`{self.page + 1}/{len(self.current_roles)}`",
            inline=True,
        )
        embed.set_footer(
            text=(
                f"PAG CORE  •  {category_title.upper()}  •  "
                f"{self.page + 1} OF {len(self.current_roles)}  •  {_cache_status(self.snapshot)}  •  "
                f"Animated emojis: {len(self.category_emojis)}/3"
            )
        )
        embed.timestamp = discord.utils.utcnow()
        return embed

    async def _edit(self, interaction: discord.Interaction) -> None:
        self.refresh_controls()
        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def change_category(self, interaction: discord.Interaction, category: str) -> None:
        if category not in CATEGORY_ORDER or not self.roles_by_category.get(category):
            await interaction.response.send_message(
                "That division is not currently available.",
                ephemeral=True,
            )
            return
        async with self._state_lock:
            self.active_category = category
            self.page = 0
            await self._edit(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            self.logger_debug_timeout()

    @staticmethod
    def logger_debug_timeout() -> None:
        LOGGER.debug("Role directory message was no longer editable at timeout.")

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        LOGGER.exception(
            "Role directory UI callback failed (item=%s).",
            getattr(item, "custom_id", None),
            exc_info=(type(error), error, error.__traceback__),
        )
        message = "The role directory could not update. Please run `!roleinfo` again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            LOGGER.debug("Could not send role directory UI error response.")

    @discord.ui.button(
        label="Previous",
        emoji="◀",
        style=discord.ButtonStyle.secondary,
        custom_id="pag_role_previous",
        row=1,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async with self._state_lock:
            self.page = max(0, self.page - 1)
            await self._edit(interaction)

    @discord.ui.button(
        label="Next",
        emoji="▶",
        style=discord.ButtonStyle.secondary,
        custom_id="pag_role_next",
        row=1,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async with self._state_lock:
            self.page = min(max(0, len(self.current_roles) - 1), self.page + 1)
            await self._edit(interaction)

    @discord.ui.button(
        label="Overview",
        emoji="⌂",
        style=discord.ButtonStyle.primary,
        custom_id="pag_role_overview",
        row=1,
    )
    async def overview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async with self._state_lock:
            self.active_category = None
            self.page = 0
            await self._edit(interaction)

    @discord.ui.button(
        label="Close",
        emoji="✕",
        style=discord.ButtonStyle.danger,
        custom_id="pag_role_close",
        row=1,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()



# ============================================================================
# Role member pagination view
# ============================================================================

class RoleMembersView(discord.ui.View):
    """Paginated, owner-scoped listing of members assigned to one role."""

    def __init__(
        self,
        *,
        owner_id: int,
        role: discord.Role,
        members: Sequence[discord.Member],
        cache_complete: bool,
        reported_member_count: int,
    ) -> None:
        super().__init__(timeout=MEMBER_VIEW_TIMEOUT_SECONDS)
        self.owner_id = owner_id
        self.role = role
        self.reported_member_count = reported_member_count
        self.members = tuple(
            sorted(members, key=lambda member: (member.display_name.casefold(), member.id))
        )
        self.cache_complete = cache_complete
        self.page = 0
        self.message: discord.Message | discord.InteractionMessage | None = None
        self._state_lock = asyncio.Lock()
        self.refresh_controls()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.members) + MEMBERS_PER_PAGE - 1) // MEMBERS_PER_PAGE)

    def create_embed(self) -> discord.Embed:
        start = self.page * MEMBERS_PER_PAGE
        end = start + MEMBERS_PER_PAGE
        page_members = self.members[start:end]
        lines = [
            f"`{start + index:02d}.` {member.mention}  ·  "
            f"{discord.utils.escape_markdown(member.display_name.replace(chr(10), ' ').replace(chr(13), ' '))}"
            for index, member in enumerate(page_members, start=1)
        ]
        if not lines:
            body = "No cached members currently have this role."
        else:
            body = "\n".join(lines)

        safe_role_name = self.role.name.replace("\n", " ").replace("\r", " ")
        embed = discord.Embed(
            title=f"{discord.utils.escape_markdown(safe_role_name)}  •  Members",
            description=body,
            color=self.role.color if self.role.color.value else COLOR_PURPLE,
        )
        embed.add_field(name="REPORTED MEMBERS", value=f"`{self.reported_member_count:,}`", inline=True)
        embed.add_field(name="CACHED MEMBERS", value=f"`{len(self.members):,}`", inline=True)
        embed.add_field(name="PAGE", value=f"`{self.page + 1}/{self.page_count}`", inline=True)
        cache_label = (
            "Complete member cache"
            if self.cache_complete and len(self.members) >= self.reported_member_count
            else f"Showing cached list · {len(self.members):,}/{self.reported_member_count:,} available"
        )
        embed.set_footer(text=f"PAG CORE  •  {cache_label}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    def refresh_controls(self) -> None:
        pages = self.page_count
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "Previous":
                    item.disabled = self.page <= 0
                elif item.label == "Next":
                    item.disabled = self.page >= pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This member list belongs to the member who opened it.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                LOGGER.debug("Role member list was no longer editable at timeout.")

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        LOGGER.exception(
            "Role member view callback failed (item=%s).",
            getattr(item, "custom_id", None),
            exc_info=(type(error), error, error.__traceback__),
        )
        try:
            text = "The member list could not be updated. Please run `!rolemembers` again."
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            LOGGER.debug("Could not send role member view error response.")

    @discord.ui.button(label="Previous", emoji="◀", style=discord.ButtonStyle.secondary, custom_id="pag_rolemembers_previous", row=0)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async with self._state_lock:
            self.page = max(0, self.page - 1)
            self.refresh_controls()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next", emoji="▶", style=discord.ButtonStyle.secondary, custom_id="pag_rolemembers_next", row=0)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async with self._state_lock:
            self.page = min(self.page_count - 1, self.page + 1)
            self.refresh_controls()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Close", emoji="✕", style=discord.ButtonStyle.danger, custom_id="pag_rolemembers_close", row=0)
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()


# ============================================================================
# Cog and command handlers
# ============================================================================

class RoleInfoCog(commands.Cog):
    """PAG's allowlisted role directory, statistics and member browser."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot_logger = getattr(bot, "logger", None)
        self.logger = bot_logger if isinstance(bot_logger, logging.Logger) else LOGGER
        self.analyzer = RoleAnalyzer(self.logger)
        self._category_emoji_cache: dict[int, dict[str, discord.Emoji]] = {}
        self._emoji_upload_attempted: set[int] = set()
        self._emoji_upload_lock = asyncio.Lock()

    async def _collect(
        self,
        guild: discord.Guild,
        *,
        load_member_cache: bool = False,
    ) -> RoleSnapshot:
        return await self.analyzer.collect(
            guild,
            load_member_cache=load_member_cache,
        )

    @staticmethod
    def _find_record(snapshot: RoleSnapshot, role: discord.Role) -> RoleRecord | None:
        return next(
            (record for record in snapshot.records if record.role.id == role.id),
            None,
        )

    async def _ensure_category_emojis(
        self,
        guild: discord.Guild,
    ) -> dict[str, discord.Emoji]:
        """Create or reuse PAG's three animated role-category emojis.

        Upload is lazy because the extension loader can run before the bot has
        a connected guild cache. Upload errors never block role commands:
        Unicode emoji remain as a safe fallback.
        """
        guild_id = guild.id
        cached = self._category_emoji_cache.get(guild_id)
        if cached is not None:
            return cached

        async with self._emoji_upload_lock:
            cached = self._category_emoji_cache.get(guild_id)
            if cached is not None:
                return cached

            existing = {emoji.name: emoji for emoji in guild.emojis}
            result: dict[str, discord.Emoji] = {}
            for category, emoji_name in CATEGORY_EMOJI_NAMES.items():
                emoji = existing.get(emoji_name)
                if emoji is not None:
                    result[category] = emoji

            missing = [
                (category, emoji_name)
                for category, emoji_name in CATEGORY_EMOJI_NAMES.items()
                if category not in result
            ]

            # Do not repeat failed uploads on every command invocation.
            if missing and guild_id not in self._emoji_upload_attempted:
                self._emoji_upload_attempted.add(guild_id)
                bot_member = guild.me
                permissions = bot_member.guild_permissions if bot_member else None
                can_manage = bool(
                    permissions is not None
                    and (permissions.manage_emojis or permissions.administrator)
                )

                if not can_manage:
                    self.logger.warning(
                        "Cannot upload PAG animated role emojis in guild %s: "
                        "bot requires Manage Expressions / Manage Emojis. "
                        "Unicode fallbacks will be used.",
                        guild_id,
                    )
                else:
                    for category, emoji_name in missing:
                        filename = BANNER_FILES[category]
                        asset_path = ASSET_DIR / filename
                        if not asset_path.is_file():
                            self.logger.error(
                                "PAG role emoji source GIF is missing: %s",
                                asset_path,
                            )
                            continue

                        try:
                            image_data = asset_path.read_bytes()
                        except OSError:
                            self.logger.exception(
                                "Unable to read PAG role emoji source GIF: %s",
                                asset_path,
                            )
                            continue

                        if len(image_data) > MAX_DISCORD_EMOJI_BYTES:
                            self.logger.error(
                                "PAG role emoji %s is %s bytes; Discord's upload limit is %s bytes.",
                                emoji_name,
                                len(image_data),
                                MAX_DISCORD_EMOJI_BYTES,
                            )
                            continue

                        try:
                            emoji = await guild.create_custom_emoji(
                                name=emoji_name,
                                image=image_data,
                                reason="PAG Role Intelligence animated category emoji",
                            )
                        except discord.Forbidden:
                            self.logger.warning(
                                "Discord denied creation of PAG emoji %s in guild %s. "
                                "Check Manage Expressions permission and animated emoji slots.",
                                emoji_name,
                                guild_id,
                            )
                            break
                        except discord.HTTPException as error:
                            self.logger.warning(
                                "Discord rejected PAG emoji %s in guild %s: %s. "
                                "Unicode fallback will be used for this category.",
                                emoji_name,
                                guild_id,
                                error,
                            )
                            continue
                        except Exception:
                            self.logger.exception(
                                "Unexpected error while creating PAG emoji %s in guild %s.",
                                emoji_name,
                                guild_id,
                            )
                            continue

                        result[category] = emoji
                        self.logger.info(
                            "Uploaded PAG animated role emoji :%s: (%s) to guild %s.",
                            emoji.name,
                            emoji.id,
                            guild_id,
                        )

            self._category_emoji_cache[guild_id] = result
            return result

    async def _send_panel(
        self,
        destination: commands.Context | discord.Interaction,
        *,
        owner_id: int,
        snapshot: RoleSnapshot,
        initial_role: discord.Role | None = None,
    ) -> None:
        guild = destination.guild
        category_emojis = (
            await self._ensure_category_emojis(guild)
            if guild is not None
            else {}
        )
        view = RoleInfoView(
            owner_id=owner_id,
            snapshot=snapshot,
            initial_role_id=initial_role.id if initial_role else None,
            category_emojis=category_emojis,
        )
        if isinstance(destination, discord.Interaction):
            message = await destination.edit_original_response(
                embed=view.create_embed(),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            message = await destination.send(
                embed=view.create_embed(),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        view.message = message

    async def _validate_official_role(
        self,
        destination: commands.Context | discord.Interaction,
        snapshot: RoleSnapshot,
        role: discord.Role,
    ) -> RoleRecord | None:
        record = self._find_record(snapshot, role)
        if record is not None:
            return record

        message = (
            "That role is not part of the active official PAG directory. "
            "Empty, personal, managed and unrelated roles are intentionally excluded."
        )
        if isinstance(destination, discord.Interaction):
            await destination.edit_original_response(
                content=message,
                embed=None,
                view=None,
                attachments=[],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await destination.reply(
                message,
                mention_author=False,
                delete_after=12,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        return None

    async def _send_members_view(
        self,
        destination: commands.Context | discord.Interaction,
        *,
        owner_id: int,
        role: discord.Role,
        snapshot: RoleSnapshot,
    ) -> None:
        members_view = RoleMembersView(
            owner_id=owner_id,
            role=role,
            members=role.members,
            cache_complete=snapshot.member_cache_complete,
            reported_member_count=next(
                (record.member_count for record in snapshot.records if record.role.id == role.id),
                len(role.members),
            ),
        )
        if isinstance(destination, discord.Interaction):
            message = await destination.edit_original_response(
                embed=members_view.create_embed(),
                view=members_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            message = await destination.send(
                embed=members_view.create_embed(),
                view=members_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        members_view.message = message

    @staticmethod
    def _stats_embed(
        snapshot: RoleSnapshot,
        category_emojis: dict[str, discord.Emoji] | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{str((category_emojis or {}).get('leadership', '👑'))}  PAG  •  ROLE STATISTICS",
            description="Live breakdown of active, recognized PAG roles.",
            color=COLOR_GOLD,
        )
        embed.add_field(name="ACTIVE ROLES", value=f"`{len(snapshot.records):,}`", inline=True)
        embed.add_field(name="ROLE ASSIGNMENTS", value=f"`{snapshot.assignment_count:,}`", inline=True)
        active_divisions = sum(
            any(record.definition.category == category for record in snapshot.records)
            for category in CATEGORY_ORDER
        )
        embed.add_field(name="ACTIVE DIVISIONS", value=f"`{active_divisions:,}`", inline=True)

        for category in CATEGORY_ORDER:
            category_records = [
                record for record in snapshot.records
                if record.definition.category == category
            ]
            if not category_records:
                continue
            title, fallback_emoji, _, _ = CATEGORY_META[category]
            emoji = str((category_emojis or {}).get(category, fallback_emoji))
            embed.add_field(
                name=f"{emoji}  {title}",
                value=(
                    f"**{len(category_records):,}** active role(s)\n"
                    f"**{sum(record.member_count for record in category_records):,}** role assignment(s)"
                ),
                inline=True,
            )

        if not snapshot.records:
            embed.add_field(
                name="No active official roles",
                value="There are currently no non-empty official roles to report.",
                inline=False,
            )
        emoji_count = len(category_emojis or {})
        embed.set_footer(
            text=f"PAG CORE  •  {_cache_status(snapshot)}  •  Animated emojis: {emoji_count}/3"
        )
        embed.timestamp = discord.utils.utcnow()
        return embed

    # ------------------------------------------------------------------
    # Prefix commands
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.cooldown(1, 4.0, commands.BucketType.user)
    @commands.command(name="roleinfo", aliases=("role-info",))
    async def roleinfo_prefix(
        self,
        ctx: commands.Context,
        role: discord.Role | None = None,
    ) -> None:
        """Open the official role directory, optionally focused on one role."""
        if ctx.guild is None:
            return
        async with ctx.typing():
            snapshot = await self._collect(ctx.guild)
        if role is not None:
            if await self._validate_official_role(ctx, snapshot, role) is None:
                return
        await self._send_panel(
            ctx,
            owner_id=ctx.author.id,
            snapshot=snapshot,
            initial_role=role,
        )

    @commands.guild_only()
    @commands.cooldown(1, 4.0, commands.BucketType.user)
    @commands.command(name="rolemembers", aliases=("role-members",))
    async def role_members_prefix(
        self,
        ctx: commands.Context,
        role: discord.Role,
    ) -> None:
        """Browse members assigned to an active official PAG role."""
        if ctx.guild is None:
            return
        async with ctx.typing():
            snapshot = await self._collect(ctx.guild, load_member_cache=True)
        if await self._validate_official_role(ctx, snapshot, role) is None:
            return
        await self._send_members_view(
            ctx,
            owner_id=ctx.author.id,
            role=role,
            snapshot=snapshot,
        )

    @commands.guild_only()
    @commands.cooldown(1, 4.0, commands.BucketType.user)
    @commands.command(name="rolestats", aliases=("role-stats",))
    async def role_stats_prefix(self, ctx: commands.Context) -> None:
        """Show a compact statistical summary of active official PAG roles."""
        if ctx.guild is None:
            return
        async with ctx.typing():
            snapshot = await self._collect(ctx.guild)
        category_emojis = await self._ensure_category_emojis(ctx.guild)
        await ctx.send(
            embed=self._stats_embed(snapshot, category_emojis),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ------------------------------------------------------------------
    # Guild application commands
    # ------------------------------------------------------------------

    @app_commands.command(name="role-info", description="Open the PAG official role directory.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 4.0, key=lambda interaction: interaction.user.id)
    @app_commands.describe(role="Optionally open a specific active official PAG role.")
    async def role_info_slash(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        snapshot = await self._collect(interaction.guild)
        if role is not None:
            if await self._validate_official_role(interaction, snapshot, role) is None:
                return
        await self._send_panel(
            interaction,
            owner_id=interaction.user.id,
            snapshot=snapshot,
            initial_role=role,
        )

    @app_commands.command(name="role-members", description="Browse members of an active official PAG role.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 4.0, key=lambda interaction: interaction.user.id)
    @app_commands.describe(role="The active official PAG role to inspect.")
    async def role_members_slash(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        snapshot = await self._collect(interaction.guild, load_member_cache=True)
        if await self._validate_official_role(interaction, snapshot, role) is None:
            return
        await self._send_members_view(
            interaction,
            owner_id=interaction.user.id,
            role=role,
            snapshot=snapshot,
        )

    @app_commands.command(name="role-stats", description="Show statistics for active official PAG roles.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 4.0, key=lambda interaction: interaction.user.id)
    async def role_stats_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        snapshot = await self._collect(interaction.guild)
        category_emojis = await self._ensure_category_emojis(interaction.guild)
        await interaction.edit_original_response(
            embed=self._stats_embed(snapshot, category_emojis),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ------------------------------------------------------------------
    # Centralized error handling
    # ------------------------------------------------------------------

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        original = getattr(error, "original", error)

        if isinstance(error, commands.CommandOnCooldown):
            message = f"Please wait **{error.retry_after:.1f}s** before using this command again."
        elif isinstance(error, commands.MissingRequiredArgument):
            message = "Please specify a role. Example: `!rolemembers @Moderator`."
        elif isinstance(error, commands.BadArgument):
            message = "I couldn't resolve that role. Mention the role or provide its exact name."
        elif isinstance(error, commands.NoPrivateMessage):
            message = "This command can only be used inside the PAG server."
        else:
            self.logger.error(
                "Role-info prefix command failed: %s",
                original,
                exc_info=(type(original), original, original.__traceback__),
            )
            message = "The role command encountered an unexpected error. Please try again later."

        try:
            await ctx.reply(
                message,
                mention_author=False,
                delete_after=12,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            self.logger.debug("Could not send prefix-command error response.")

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Please wait **{error.retry_after:.1f}s** before using this command again."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You cannot use this application command here."
        elif isinstance(original, discord.Forbidden):
            message = "PAG Bot is missing a Discord permission required for this operation."
        elif isinstance(original, discord.HTTPException):
            message = "Discord rejected the request. Please try again in a moment."
        else:
            self.logger.error(
                "Role-info application command failed: %s",
                original,
                exc_info=(type(original), original, original.__traceback__),
            )
            message = "The role command encountered an unexpected error. Please try again later."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    message,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except discord.HTTPException:
            self.logger.debug("Could not send application-command error response.")


# ============================================================================
# Extension entry point
# ============================================================================

async def setup(bot: commands.Bot) -> None:
    """Load the Cog and scope its slash commands to PAG's configured guild.

    PAGBot synchronizes only ``tree.sync(guild=bot.guild_object)``. Registering
    these Cog application commands with the same guild is therefore essential;
    adding them globally would leave them out of PAG's guild command sync.
    """

    cog = RoleInfoCog(bot)
    config = getattr(bot, "config", None)
    guild_id = getattr(config, "discord_guild_id", None)

    if isinstance(guild_id, int) and guild_id > 0:
        await bot.add_cog(cog, guild=discord.Object(id=guild_id))
        LOGGER.info("Role-info Cog loaded with guild-scoped slash commands for %s.", guild_id)
    else:
        LOGGER.warning(
            "DISCORD_GUILD_ID is unavailable on the bot config; loading role-info Cog globally. "
            "Slash commands may not appear because PAGBot syncs a specific guild only."
        )
        await bot.add_cog(cog)
