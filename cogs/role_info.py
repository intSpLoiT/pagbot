"""PAG Role Intelligence System.

Drop-in replacement for the existing ``cogs/role_info.py``.

Commands
--------
Prefix:
    !roleinfo [@role]       Open the interactive official-role panel.
    !rolemembers @role      List members assigned to an official role.
    !rolestats              Show official role statistics.

Slash:
    /role-info [role]
    /role-members role
    /role-stats

Only explicitly recognized PAG staff, security and community roles are
included. Empty roles, @everyone, personal vanity roles and unrelated game
roles are intentionally excluded. Role descriptions explain the intended
PAG function; actual Discord permissions remain controlled by server setup.

This module uses only discord.py and Python's standard library. Animated GIFs
are shipped beside this file in ``role_info_assets/``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands


# ---------------------------------------------------------------------------
# Visual identity
# ---------------------------------------------------------------------------

PAG_PURPLE: Final[discord.Color] = discord.Color.from_rgb(104, 64, 172)
PAG_GOLD: Final[discord.Color] = discord.Color.from_rgb(222, 181, 91)
PAG_DARK: Final[discord.Color] = discord.Color.from_rgb(35, 25, 54)

ASSET_DIR: Final[Path] = Path(__file__).resolve().with_name("role_info_assets")

CATEGORY_META: Final[dict[str, tuple[str, str, str]]] = {
    "leadership": (
        "Leadership",
        "👑",
        "PAG leadership, executive coordination and server administration.",
    ),
    "security": (
        "Security & Support",
        "🛡️",
        "Server protection, moderation and member-support responsibilities.",
    ),
    "community": (
        "Community & Partners",
        "✦",
        "VIP, community programmes and recognized partner groups.",
    ),
}

BANNER_FILES: Final[dict[str, str]] = {
    "leadership": "roleinfo_leadership.gif",
    "security": "roleinfo_security.gif",
    "community": "roleinfo_community.gif",
}


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """Curated public-facing definition for one official PAG role."""

    category: str
    description: str
    emoji: str
    display_title: str


@dataclass(slots=True)
class RoleRecord:
    """A Discord role together with its curated PAG metadata."""

    role: discord.Role
    definition: RoleDefinition
    member_count: int

    @property
    def position(self) -> int:
        return self.role.position


# Exact normalized names are used rather than broad substring matching.
# This prevents decorative/personal roles such as member nicknames or bot
# labels from accidentally appearing in the official role directory.
ROLE_DEFINITIONS: Final[dict[str, RoleDefinition]] = {
    # Leadership and administration
    "emperor": RoleDefinition(
        "leadership",
        "The highest ceremonial leadership tier in the PAG structure. It represents top-level direction and oversight of the community.",
        "👑",
        "Emperor",
    ),
    "temporary owner": RoleDefinition(
        "leadership",
        "A delegated ownership role used for a defined period when operational continuity or founder coverage is required.",
        "⌛",
        "Temporary Owner",
    ),
    "co owner": RoleDefinition(
        "leadership",
        "A senior leadership position that supports ownership decisions and the ongoing coordination of PAG operations.",
        "⚜️",
        "Co-Owner",
    ),
    "executive": RoleDefinition(
        "leadership",
        "An executive coordination role focused on high-level operations, staff alignment and the delivery of PAG decisions.",
        "◆",
        "Executive",
    ),
    "left wing": RoleDefinition(
        "leadership",
        "A leadership wing within the PAG structure, helping coordinate assigned areas and maintain operational continuity.",
        "◀",
        "Left Wing",
    ),
    "right wing": RoleDefinition(
        "leadership",
        "A leadership wing within the PAG structure, helping coordinate assigned areas and maintain operational continuity.",
        "▶",
        "Right Wing",
    ),
    "head admin": RoleDefinition(
        "leadership",
        "The senior administration tier responsible for coordinating administrative work and supporting consistent staff standards.",
        "🏛️",
        "Head Admin",
    ),
    "admin": RoleDefinition(
        "leadership",
        "An administration role for trusted members who help manage server operations and apply the community's established rules.",
        "🔰",
        "Admin",
    ),
    "tester manager": RoleDefinition(
        "leadership",
        "Coordinates testing activity, organizes tester feedback and helps prepare system changes for review.",
        "🧪",
        "Tester Manager",
    ),
    "hoster": RoleDefinition(
        "leadership",
        "Supports the organization and hosting of PAG activities, sessions or community events.",
        "🎙️",
        "Hoster",
    ),
    "tryout hoster": RoleDefinition(
        "leadership",
        "Coordinates tryout sessions and helps keep the evaluation process organized and consistent.",
        "🏁",
        "Tryout Hoster",
    ),
    "ally owner": RoleDefinition(
        "community",
        "The designated point of contact for an allied community, supporting partner coordination and communication with PAG.",
        "🤝",
        "Ally Owner",
    ),

    # Security and member support
    "pag security": RoleDefinition(
        "security",
        "The PAG security identity for designated protection and security-system operations. Its actual access is determined by Discord permissions.",
        "🛡️",
        "PAG Security",
    ),
    "senior moderator": RoleDefinition(
        "security",
        "A senior moderation tier that supports difficult moderation cases, staff guidance and consistent rule enforcement.",
        "⚖️",
        "Senior Moderator",
    ),
    "moderator": RoleDefinition(
        "security",
        "Helps maintain a respectful server environment, reviews reported issues and handles moderation tasks within assigned permissions.",
        "🔨",
        "Moderator",
    ),
    "trial moderator": RoleDefinition(
        "security",
        "A trial moderation position for learning PAG procedures and demonstrating reliable, consistent moderation practice.",
        "🛡️",
        "Trial Moderator",
    ),
    "ticketyetkilisi": RoleDefinition(
        "security",
        "Supports the ticket workflow by reviewing incoming requests and directing members to the appropriate staff team.",
        "🎫",
        "Ticket Staff",
    ),
    "sailor yetkilisi": RoleDefinition(
        "security",
        "The designated staff contact for Sailor-related member questions and coordination.",
        "⚓",
        "Sailor Staff",
    ),
    "rivals yetkilisi": RoleDefinition(
        "security",
        "The designated staff contact for Rivals-related member questions and coordination.",
        "🎯",
        "Rivals Staff",
    ),

    # Community, VIP and recognized groups
    "vip": RoleDefinition(
        "community",
        "A PAG community recognition role for members with VIP status. It does not imply any permissions beyond those configured in Discord.",
        "👑",
        "VIP",
    ),
    "prime tier 1": RoleDefinition(
        "community",
        "A Prime progression tier used by PAG to distinguish community or competitive standing.",
        "✦",
        "Prime Tier 1",
    ),
    "prime tier 2": RoleDefinition(
        "community",
        "A Prime progression tier used by PAG to distinguish community or competitive standing.",
        "✦",
        "Prime Tier 2",
    ),
    "prime tier 3": RoleDefinition(
        "community",
        "A Prime progression tier used by PAG to distinguish community or competitive standing.",
        "✦",
        "Prime Tier 3",
    ),
    "prime tier 4": RoleDefinition(
        "community",
        "A Prime progression tier used by PAG to distinguish community or competitive standing.",
        "✦",
        "Prime Tier 4",
    ),
    "prime tier 5": RoleDefinition(
        "community",
        "A Prime progression tier used by PAG to distinguish community or competitive standing.",
        "✦",
        "Prime Tier 5",
    ),
    "tsb": RoleDefinition(
        "community",
        "A community group label for members associated with TSB.",
        "⚔️",
        "TSB",
    ),
    "sailor": RoleDefinition(
        "community",
        "A community group label for members associated with Sailor.",
        "⚓",
        "Sailor",
    ),
    "rivals": RoleDefinition(
        "community",
        "A community group label for members associated with Rivals.",
        "🎯",
        "Rivals",
    ),
    "brainrot games": RoleDefinition(
        "community",
        "A community interest role for members who follow Brainrot Games activity.",
        "🎮",
        "Brainrot Games",
    ),
    "fc": RoleDefinition(
        "community",
        "A community group label for members associated with FC.",
        "⚽",
        "FC",
    ),
    "blox fruits": RoleDefinition(
        "community",
        "A community interest role for members who follow Blox Fruits activity.",
        "🍈",
        "Blox Fruits",
    ),
}


CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "leadership",
    "security",
    "community",
)


def normalize_role_name(name: str) -> str:
    """Normalize stylized Unicode role names into comparable plain text."""

    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.casefold().replace("_", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


class RoleAnalyzer:
    """Build an active, allowlisted view of PAG roles from the guild cache."""

    @staticmethod
    async def collect(guild: discord.Guild) -> tuple[list[RoleRecord], bool]:
        """Return active official roles and whether the member cache is complete.

        For reasonably sized guilds, ask Discord.py to populate its member
        cache before counting. A bounded timeout prevents a role command from
        hanging in a large or temporarily unavailable guild.
        """

        if not guild.chunked and guild.member_count and guild.member_count <= 2500:
            try:
                await asyncio.wait_for(guild.chunk(cache=True), timeout=12.0)
            except (asyncio.TimeoutError, discord.HTTPException, discord.Forbidden):
                pass
            except Exception:
                logging.getLogger("PAG.RoleInfo").exception(
                    "Unexpected error while refreshing guild member cache."
                )

        cache_complete = bool(guild.chunked)
        records: list[RoleRecord] = []

        for role in guild.roles:
            if role.is_default or role.managed:
                continue

            definition = ROLE_DEFINITIONS.get(normalize_role_name(role.name))
            if definition is None:
                continue

            member_count = len(role.members)
            if member_count <= 0:
                continue

            records.append(
                RoleRecord(
                    role=role,
                    definition=definition,
                    member_count=member_count,
                )
            )

        category_rank = {key: index for index, key in enumerate(CATEGORY_ORDER)}
        records.sort(
            key=lambda item: (
                category_rank.get(item.definition.category, 99),
                -item.position,
                normalize_role_name(item.role.name),
            )
        )
        return records, cache_complete


class RoleCategorySelect(discord.ui.Select):
    """Category selector bound to one role information panel."""

    def __init__(self, panel: "RoleInfoView") -> None:
        self.panel = panel
        options: list[discord.SelectOption] = []

        for category in CATEGORY_ORDER:
            roles = panel.roles_by_category.get(category, [])
            if not roles:
                continue
            title, emoji, _ = CATEGORY_META[category]
            options.append(
                discord.SelectOption(
                    label=title,
                    value=category,
                    emoji=emoji,
                    description=f"Browse {len(roles)} active role(s).",
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No active official roles",
                    value="none",
                    description="No non-empty official roles were detected.",
                )
            )

        super().__init__(
            placeholder="Choose a PAG role division...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            disabled=not bool(panel.roles),
            custom_id=f"pag_role_category_{panel.owner_id}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            await interaction.response.defer()
            return

        self.panel.active_category = self.values[0]
        self.panel.page = 0
        self.panel.refresh_controls()
        await interaction.response.edit_message(
            embed=self.panel.create_embed(),
            view=self.panel,
        )


class RoleInfoView(discord.ui.View):
    """Interactive category and role browser for one command invocation."""

    def __init__(
        self,
        *,
        owner_id: int,
        records: list[RoleRecord],
        cache_complete: bool,
        initial_role_id: int | None = None,
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.records = records
        self.cache_complete = cache_complete
        self.roles_by_category: dict[str, list[RoleRecord]] = defaultdict(list)

        for record in records:
            self.roles_by_category[record.definition.category].append(record)

        self.active_category: str | None = None
        self.page = 0
        self.message: discord.Message | discord.InteractionMessage | None = None

        if initial_role_id is not None:
            for category in CATEGORY_ORDER:
                category_roles = self.roles_by_category.get(category, [])
                for index, record in enumerate(category_roles):
                    if record.role.id == initial_role_id:
                        self.active_category = category
                        self.page = index
                        break
                if self.active_category is not None:
                    break

        self.add_item(RoleCategorySelect(self))
        self.refresh_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This role panel belongs to the member who opened it.",
                ephemeral=True,
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
        roles = self.current_roles
        if not roles:
            return None
        self.page = max(0, min(self.page, len(roles) - 1))
        return roles[self.page]

    def refresh_controls(self) -> None:
        roles = self.current_roles
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "pag_role_previous":
                item.disabled = not roles or self.page <= 0
            elif item.custom_id == "pag_role_next":
                item.disabled = not roles or self.page >= len(roles) - 1

    def _set_banner(self, embed: discord.Embed, category: str) -> None:
        filename = BANNER_FILES.get(category)
        if filename and (ASSET_DIR / filename).is_file():
            embed.set_image(url=f"attachment://{filename}")

    def create_embed(self) -> discord.Embed:
        if self.active_category is None:
            return self._create_overview()
        record = self.current_record
        if record is None:
            return self._create_overview()
        return self._create_role_embed(record)

    def _create_overview(self) -> discord.Embed:
        total_roles = len(self.records)
        total_assignments = sum(record.member_count for record in self.records)
        embed = discord.Embed(
            title="PAG  •  ROLE INTELLIGENCE",
            description=(
                "**Official role directory**\n"
                "A curated overview of PAG leadership, security and community roles.\n\n"
                "Select a division below to inspect its active roles."
            ),
            color=PAG_PURPLE,
        )

        embed.add_field(
            name="ACTIVE OFFICIAL ROLES",
            value=f"`{total_roles}`",
            inline=True,
        )
        embed.add_field(
            name="ROLE ASSIGNMENTS",
            value=f"`{total_assignments}`",
            inline=True,
        )
        embed.add_field(
            name="DIVISIONS",
            value=f"`{sum(bool(self.roles_by_category.get(key)) for key in CATEGORY_ORDER)}`",
            inline=True,
        )

        for category in CATEGORY_ORDER:
            roles = self.roles_by_category.get(category, [])
            if not roles:
                continue
            title, emoji, summary = CATEGORY_META[category]
            lines = [
                f"{record.definition.emoji} **{discord.utils.escape_markdown(record.role.name)}** · `{record.member_count}`"
                for record in roles[:7]
            ]
            if len(roles) > 7:
                lines.append(f"*and {len(roles) - 7} more role(s)*")
            embed.add_field(
                name=f"{emoji}  {title}  •  {len(roles)} active",
                value="\n".join(lines) if lines else summary,
                inline=False,
            )

        if not self.records:
            embed.add_field(
                name="No active official roles",
                value=(
                    "No recognized PAG staff, security or community roles currently "
                    "have members assigned. Empty and unrelated roles are hidden."
                ),
                inline=False,
            )

        cache_note = (
            "Live member cache"
            if self.cache_complete
            else "Counts use the bot's currently available member cache"
        )
        embed.set_footer(text=f"PAG Core  •  ROLE INTELLIGENCE  •  {cache_note}")
        self._set_banner(embed, "leadership")
        return embed

    def _create_role_embed(self, record: RoleRecord) -> discord.Embed:
        role = record.role
        category = record.definition.category
        category_title, category_emoji, _ = CATEGORY_META[category]
        color = role.color if role.color.value else PAG_PURPLE

        embed = discord.Embed(
            title=f"{record.definition.emoji}  {record.definition.display_title}",
            description=(
                f"{role.mention}\n\n"
                f"{record.definition.description}\n\n"
                "*This description explains the role's intended PAG function. "
                "Its actual permissions are determined by the server's Discord role settings.*"
            ),
            color=color,
        )
        embed.add_field(
            name="MEMBERS",
            value=f"`{record.member_count:,}`",
            inline=True,
        )
        embed.add_field(
            name="HIERARCHY",
            value=f"`#{record.position}`",
            inline=True,
        )
        embed.add_field(
            name="ROLE CATEGORY",
            value=f"{category_emoji} `{category_title}`",
            inline=True,
        )
        embed.add_field(
            name="ROLE ID",
            value=f"`{role.id}`",
            inline=True,
        )
        embed.add_field(
            name="ROLE COLOR",
            value=f"`#{role.color.value:06X}`" if role.color.value else "`Default`",
            inline=True,
        )
        embed.add_field(
            name="POSITION IN DIVISION",
            value=f"`{self.page + 1}/{len(self.current_roles)}`",
            inline=True,
        )
        embed.set_footer(
            text=(
                f"PAG Core  •  {category_title.upper()}  •  "
                f"{self.page + 1} OF {len(self.current_roles)}"
            )
        )
        self._set_banner(embed, category)
        return embed

    @staticmethod
    def build_files() -> list[discord.File]:
        """Create fresh Discord file handles for the bundled animated banners."""
        files: list[discord.File] = []
        for filename in BANNER_FILES.values():
            path = ASSET_DIR / filename
            if path.is_file():
                files.append(discord.File(path, filename=filename))
        return files

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

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
        if self.active_category is not None:
            self.page = max(0, self.page - 1)
        self.refresh_controls()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

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
        if self.active_category is not None:
            self.page = min(len(self.current_roles) - 1, self.page + 1)
        self.refresh_controls()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

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
        self.active_category = None
        self.page = 0
        self.refresh_controls()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

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


class RoleInfoCog(commands.Cog):
    """PAG's curated and animated role directory."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = getattr(bot, "logger", logging.getLogger("PAG.RoleInfo"))

    async def _guild_records(
        self,
        guild: discord.Guild,
    ) -> tuple[list[RoleRecord], bool]:
        return await RoleAnalyzer.collect(guild)

    @staticmethod
    def _find_active_record(
        records: list[RoleRecord],
        role: discord.Role,
    ) -> RoleRecord | None:
        return next((record for record in records if record.role.id == role.id), None)

    async def _send_panel(
        self,
        *,
        destination: commands.Context | discord.Interaction,
        owner_id: int,
        records: list[RoleRecord],
        cache_complete: bool,
        initial_role: discord.Role | None = None,
        interaction_mode: bool = False,
    ) -> None:
        view = RoleInfoView(
            owner_id=owner_id,
            records=records,
            cache_complete=cache_complete,
            initial_role_id=initial_role.id if initial_role else None,
        )
        files = view.build_files()
        embed = view.create_embed()

        if interaction_mode:
            assert isinstance(destination, discord.Interaction)
            message = await destination.edit_original_response(
                embed=embed,
                view=view,
                attachments=files,
            )
            view.message = message
        else:
            assert isinstance(destination, commands.Context)
            message = await destination.send(embed=embed, view=view, files=files)
            view.message = message

    async def _validate_role(
        self,
        ctx_or_interaction: commands.Context | discord.Interaction,
        records: list[RoleRecord],
        role: discord.Role,
    ) -> RoleRecord | None:
        record = self._find_active_record(records, role)
        if record is None:
            message = (
                "That role is not part of the active official PAG directory. "
                "Empty, personal and unrelated roles are intentionally excluded."
            )
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.edit_original_response(
                    content=message,
                    embed=None,
                    view=None,
                )
            else:
                await ctx_or_interaction.reply(message, mention_author=False, delete_after=12)
        return record

    # ------------------------------------------------------------------
    # Main role directory
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.command(name="roleinfo", aliases=("role-info",))
    async def roleinfo_prefix(
        self,
        ctx: commands.Context,
        role: discord.Role | None = None,
    ) -> None:
        """Open a fresh interactive role panel in the current channel."""

        async with ctx.typing():
            records, cache_complete = await self._guild_records(ctx.guild)

        if role is not None and await self._validate_role(ctx, records, role) is None:
            return

        await self._send_panel(
            destination=ctx,
            owner_id=ctx.author.id,
            records=records,
            cache_complete=cache_complete,
            initial_role=role,
        )

    @app_commands.command(
        name="role-info",
        description="Open the PAG official role directory.",
    )
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
        records, cache_complete = await self._guild_records(interaction.guild)
        if role is not None and await self._validate_role(interaction, records, role) is None:
            return

        await self._send_panel(
            destination=interaction,
            owner_id=interaction.user.id,
            records=records,
            cache_complete=cache_complete,
            initial_role=role,
            interaction_mode=True,
        )

    # ------------------------------------------------------------------
    # Role member directory
    # ------------------------------------------------------------------

    async def _send_role_members(
        self,
        *,
        destination: commands.Context | discord.Interaction,
        role: discord.Role,
        members: list[discord.Member],
        interaction_mode: bool = False,
    ) -> None:
        members.sort(key=lambda member: member.display_name.casefold())
        shown = members[:35]
        lines = [f"{index}. {member.mention}" for index, member in enumerate(shown, start=1)]
        if len(members) > len(shown):
            lines.append(f"\n*And {len(members) - len(shown)} more member(s).* ")

        embed = discord.Embed(
            title=f"{role.name}  •  Members",
            description="\n".join(lines) if lines else "No members currently have this role.",
            color=role.color if role.color.value else PAG_PURPLE,
        )
        embed.add_field(name="TOTAL MEMBERS", value=f"`{len(members):,}`", inline=True)
        embed.add_field(name="ROLE POSITION", value=f"`#{role.position}`", inline=True)
        embed.set_footer(text="PAG Core  •  OFFICIAL ROLE DIRECTORY")

        if interaction_mode:
            assert isinstance(destination, discord.Interaction)
            await destination.edit_original_response(embed=embed)
        else:
            assert isinstance(destination, commands.Context)
            await destination.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="rolemembers")
    async def role_members_prefix(
        self,
        ctx: commands.Context,
        role: discord.Role,
    ) -> None:
        async with ctx.typing():
            records, _ = await self._guild_records(ctx.guild)
        if await self._validate_role(ctx, records, role) is None:
            return
        await self._send_role_members(
            destination=ctx,
            role=role,
            members=list(role.members),
        )

    @app_commands.command(
        name="role-members",
        description="List members assigned to an active official PAG role.",
    )
    @app_commands.describe(role="The official PAG role to inspect.")
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
        records, _ = await self._guild_records(interaction.guild)
        if await self._validate_role(interaction, records, role) is None:
            return
        await self._send_role_members(
            destination=interaction,
            role=role,
            members=list(role.members),
            interaction_mode=True,
        )

    # ------------------------------------------------------------------
    # Official role statistics
    # ------------------------------------------------------------------

    @staticmethod
    def _build_stats_embed(records: list[RoleRecord], cache_complete: bool) -> discord.Embed:
        embed = discord.Embed(
            title="PAG  •  ROLE STATISTICS",
            description="Live breakdown of active, recognized PAG roles.",
            color=PAG_GOLD,
        )
        assignments = sum(record.member_count for record in records)
        embed.add_field(name="ACTIVE ROLES", value=f"`{len(records):,}`", inline=True)
        embed.add_field(name="ROLE ASSIGNMENTS", value=f"`{assignments:,}`", inline=True)

        for category in CATEGORY_ORDER:
            category_records = [r for r in records if r.definition.category == category]
            if not category_records:
                continue
            title, emoji, _ = CATEGORY_META[category]
            embed.add_field(
                name=f"{emoji}  {title}",
                value=(
                    f"**{len(category_records)}** active role(s)\n"
                    f"**{sum(r.member_count for r in category_records):,}** role assignment(s)"
                ),
                inline=True,
            )

        if not records:
            embed.add_field(
                name="No active roles",
                value="There are currently no non-empty official roles to report.",
                inline=False,
            )
        embed.set_footer(
            text=(
                "PAG Core  •  LIVE MEMBER CACHE"
                if cache_complete
                else "PAG Core  •  COUNTS FROM AVAILABLE MEMBER CACHE"
            )
        )
        return embed

    @commands.guild_only()
    @commands.command(name="rolestats")
    async def role_stats_prefix(self, ctx: commands.Context) -> None:
        async with ctx.typing():
            records, cache_complete = await self._guild_records(ctx.guild)
        await ctx.send(embed=self._build_stats_embed(records, cache_complete))

    @app_commands.command(
        name="role-stats",
        description="Show statistics for active official PAG roles.",
    )
    async def role_stats_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        records, cache_complete = await self._guild_records(interaction.guild)
        await interaction.edit_original_response(
            embed=self._build_stats_embed(records, cache_complete)
        )


async def setup(bot: commands.Bot) -> None:
    """Load the PAG Role Intelligence Cog."""
    await bot.add_cog(RoleInfoCog(bot))
