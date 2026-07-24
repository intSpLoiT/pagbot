"""
PAG Core
Role Information Cog

This module provides a visual role information system.

Main features:

    - Display all server roles
    - Display role descriptions
    - Display role colors
    - Display member counts
    - Display role hierarchy
    - Categorize roles automatically
    - Browse roles with buttons
    - Select individual roles from a dropdown
    - Show role members
    - Display role statistics

Example commands:

    /role-info

    /role-info role:@Moderator

    /role-members role:@Moderator

    /role-stats


Architecture:

    Discord Interaction
            |
            v
       RoleInfoCog
            |
            v
      RoleAnalyzer
            |
            v
       RoleInfoView
            |
            v
      Discord UI


The system intentionally does not depend on a database.

All role information can be retrieved directly from
Discord's guild cache.
"""


from __future__ import annotations


from dataclasses import dataclass


from enum import Enum


from typing import Optional


import discord


from discord import (
    app_commands,
)


from discord.ext import (
    commands,
)


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


from core.logger import logger


class RoleCategory(
    Enum
):
    """
    Available automatic role categories.
    """


    MANAGEMENT = (
        "Management"
    )


    MODERATION = (
        "Moderation"
    )


    RANK = (
        "Ranks"
    )


    COMMUNITY = (
        "Community"
    )


    SPECIAL = (
        "Special"
    )


    SYSTEM = (
        "System"
    )


    OTHER = (
        "Other"
    )


@dataclass(
    slots=True,
)
class RoleInfo:
    """
    Normalized role information object.

    This prevents the UI layer from having to repeatedly
    inspect raw Discord Role objects.
    """


    role: discord.Role


    category: RoleCategory


    description: str


    member_count: int


    position: int


    is_managed: bool


    is_default: bool


    @property
    def name(self) -> str:
        """
        Return the role name.
        """

        return self.role.name


    @property
    def color(self) -> discord.Color:
        """
        Return the role color.

        If the role has no custom color, Discord's default
        color is used.
        """

        if self.role.color.value:

            return self.role.color


        return discord.Color.blurple()


class RoleAnalyzer:
    """
    Analyze and categorize Discord roles.

    This class contains role logic independently from the Cog.

    This makes it possible to later reuse the same analyzer
    for:

        - Role dashboards
        - Statistics
        - Member profiles
        - Web dashboards
    """


    ROLE_DESCRIPTIONS: dict[str, str] = {

        "Owner": (
            "The highest authority within the community. "
            "Responsible for the overall direction, "
            "management and long-term development of PAG."
        ),

        "Co-Owner": (
            "A senior leadership role trusted with major "
            "management responsibilities and community "
            "decisions."
        ),

        "Admin": (
            "Responsible for maintaining the server, "
            "managing staff and handling important "
            "community operations."
        ),

        "Moderator": (
            "Helps maintain order within the community, "
            "handles moderation tasks and supports members."
        ),

        "Tester": (
            "A member trusted to test systems, features "
            "and updates before they become publicly "
            "available."
        ),

        "Member": (
            "A member of the PAG community."
        ),

        "LT": (
            "Legend Tier. The highest rank tier within "
            "the PAG ranking structure."
        ),

        "PT": (
            "Prime Tier. A highly experienced and skilled "
            "member of the PAG community."
        ),

        "ET": (
            "Expert Tier. A member who demonstrates a "
            "high level of skill and consistency."
        ),

        "AT": (
            "Advanced Tier. A member with strong ability "
            "and developed experience."
        ),

        "ST": (
            "Standard Tier. A regular competitive rank "
            "within the PAG ranking system."
        ),

        "RT": (
            "Rookie Tier. The entry-level competitive rank "
            "within the PAG ranking system."
        ),

    }


    @classmethod
    def get_description(
        cls,
        role: discord.Role,
    ) -> str:
        """
        Retrieve a description for a role.

        Exact role names are checked first.

        If no custom description exists, a generic
        description is automatically generated.
        """

        if role.name in cls.ROLE_DESCRIPTIONS:

            return cls.ROLE_DESCRIPTIONS[
                role.name
            ]


        if role.is_default:

            return (
                "The default role assigned to every "
                "member of this Discord server."
            )


        if role.managed:

            return (
                "A system-managed role controlled by "
                "an external Discord integration."
            )


        return (
            f"The {role.name} role within the "
            "PAG community."
        )


    @classmethod
    def categorize(
        cls,
        role: discord.Role,
    ) -> RoleCategory:
        """
        Automatically determine the category of a role.

        The system uses role names and Discord metadata
        to determine the most suitable category.
        """

        name = role.name.lower()


        if role.is_default:

            return RoleCategory.SYSTEM


        if role.managed:

            return RoleCategory.SYSTEM


        management_keywords = [

            "owner",

            "admin",

            "director",

            "leader",

            "management",

            "executive",

        ]


        if any(
            keyword in name
            for keyword in management_keywords
        ):

            return RoleCategory.MANAGEMENT


        moderation_keywords = [

            "mod",

            "moderator",

            "helper",

            "support",

            "trial mod",

        ]


        if any(
            keyword in name
            for keyword in moderation_keywords
        ):

            return RoleCategory.MODERATION


        rank_names = {

            "rt",

            "st",

            "at",

            "et",

            "pt",

            "lt",

            "rookie tier",

            "standard tier",

            "advanced tier",

            "expert tier",

            "prime tier",

            "legend tier",

        }


        if name in rank_names:

            return RoleCategory.RANK


        community_keywords = [

            "member",

            "tester",

            "recruit",

            "guest",

            "verified",

        ]


        if any(
            keyword in name
            for keyword in community_keywords
        ):

            return RoleCategory.COMMUNITY


        special_keywords = [

            "event",

            "champion",

            "winner",

            "elite",

            "special",

        ]


        if any(
            keyword in name
            for keyword in special_keywords
        ):

            return RoleCategory.SPECIAL


        return RoleCategory.OTHER


    @classmethod
    def analyze(
        cls,
        role: discord.Role,
    ) -> RoleInfo:
        """
        Convert a Discord Role into RoleInfo.
        """

        return RoleInfo(

            role=role,

            category=cls.categorize(
                role
            ),

            description=cls.get_description(
                role
            ),

            member_count=len(
                role.members
            ),

            position=role.position,

            is_managed=role.managed,

            is_default=role.is_default,

        )


    @classmethod
    def analyze_guild(
        cls,
        guild: discord.Guild,
    ) -> list[RoleInfo]:
        """
        Analyze all roles in a guild.
        """

        results: list[
            RoleInfo
        ] = []


        for role in guild.roles:

            results.append(
                cls.analyze(
                    role
                )
            )


        results.sort(

            key=lambda item: (
                item.position
            ),

            reverse=True,

        )


        return results


class RoleInfoView(
    discord.ui.View
):
    """
    Interactive role information interface.

    The View provides:

        - Previous page
        - Next page
        - Role selection
        - Close button
    """


    def __init__(
        self,
        interaction: discord.Interaction,
        roles: list[RoleInfo],
        *,
        timeout: float = 300,
    ) -> None:

        super().__init__(
            timeout=timeout
        )


        self.owner_id = (
            interaction.user.id
        )


        self.roles = roles


        self.page = 0


        self.page_size = 1


        self.message: Optional[
            discord.InteractionMessage
        ] = None


        self._refresh_buttons()


    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        """
        Prevent unrelated users from controlling
        another user's role information panel.
        """

        if (
            interaction.user.id
            !=
            self.owner_id
        ):

            await interaction.response.send_message(

                "Only the user who opened this panel "
                "can control it.",

                ephemeral=True,

            )


            return False


        return True


    def _refresh_buttons(
        self,
    ) -> None:
        """
        Update button states.
        """

        self.previous_page.disabled = (
            self.page <= 0
        )


        self.next_page.disabled = (
            self.page
            >=
            len(
                self.roles
            )
            - 1
        )


    def _get_current_role(
        self,
    ) -> RoleInfo | None:
        """
        Get the role currently displayed.
        """

        if not self.roles:

            return None


        if self.page >= len(
            self.roles
        ):

            return None


        return self.roles[
            self.page
        ]


    def create_embed(
        self,
    ) -> discord.Embed:
        """
        Create the current role information embed.
        """

        role_info = (
            self._get_current_role()
        )


        if role_info is None:

            return discord.Embed(

                title=(
                    "No Role Information"
                ),

                description=(
                    "No roles are available."
                ),

                color=discord.Color.red(),

            )


        role = role_info.role


        embed = discord.Embed(

            title=(
                f"Role Information"
            ),

            description=(

                f"## {role.mention}\n\n"

                f"{role_info.description}"

            ),

            color=role_info.color,

        )


        embed.add_field(

            name="Category",

            value=(

                f"`{role_info.category.value}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Members",

            value=(

                f"`{role_info.member_count}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Position",

            value=(

                f"`#{role_info.position}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Role Color",

            value=(

                f"`#{role.color.value:06X}`"

                if role.color.value

                else

                "`Default`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Managed",

            value=(

                "Yes"

                if role_info.is_managed

                else

                "No"

            ),

            inline=True,

        )


        embed.add_field(

            name="Role ID",

            value=(

                f"`{role.id}`"

            ),

            inline=True,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Role {self.page + 1}/"

                f"{len(self.roles)} • "

                f"v{BOT_VERSION}"

            ),

        )


        return embed


    @discord.ui.button(

        label="Previous",

        style=discord.ButtonStyle.secondary,

        emoji="◀",

    )
    async def previous_page(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        if self.page > 0:

            self.page -= 1


        self._refresh_buttons()


        await interaction.response.edit_message(

            embed=self.create_embed(),

            view=self,

        )


    @discord.ui.button(

        label="Next",

        style=discord.ButtonStyle.primary,

        emoji="▶",

    )
    async def next_page(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        if self.page < len(
            self.roles
        ) - 1:

            self.page += 1


        self._refresh_buttons()


        await interaction.response.edit_message(

            embed=self.create_embed(),

            view=self,

        )


    @discord.ui.button(

        label="Close",

        style=discord.ButtonStyle.danger,

        emoji="✕",

    )
    async def close_panel(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        for child in self.children:

            child.disabled = True


        await interaction.response.edit_message(

            embed=self.create_embed(),

            view=self,

        )


class RoleInfoCog(
    commands.Cog
):
    """
    Discord role information system.
    """


    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot


        logger.info(

            "RoleInfoCog initialized."

        )


    @app_commands.command(

        name="role-info",

        description=(

            "View detailed information about "
            "server roles."

        ),

    )
    @app_commands.describe(

        role=(

            "Optional role to inspect."

        ),

    )
    async def role_info(

        self,

        interaction: discord.Interaction,

        role: discord.Role | None = None,

    ) -> None:

        """
        Display detailed information about a role.

        If no role is specified, all server roles are
        displayed one by one using the interactive panel.
        """

        guild = interaction.guild


        if guild is None:

            await interaction.response.send_message(

                "This command can only be used inside "
                "a server.",

                ephemeral=True,

            )


            return


        if role is not None:

            role_info = (
                RoleAnalyzer.analyze(
                    role
                )
            )


            embed = discord.Embed(

                title=(

                    f"Role Information"

                ),

                description=(

                    f"## {role.mention}\n\n"

                    f"{role_info.description}"

                ),

                color=role_info.color,

            )


            embed.add_field(

                name="Category",

                value=(

                    f"`{role_info.category.value}`"

                ),

                inline=True,

            )


            embed.add_field(

                name="Members",

                value=(

                    f"`{role_info.member_count}`"

                ),

                inline=True,

            )


            embed.add_field(

                name="Position",

                value=(

                    f"`#{role_info.position}`"

                ),

                inline=True,

            )


            embed.add_field(

                name="Role ID",

                value=(

                    f"`{role.id}`"

                ),

                inline=True,

            )


            embed.set_footer(

                text=(

                    f"{BOT_NAME} • "

                    f"Role Information • "

                    f"v{BOT_VERSION}"

                ),

            )


            await interaction.response.send_message(

                embed=embed

            )


            return


        roles = (

            RoleAnalyzer.analyze_guild(
                guild
            )
        )


        if not roles:

            await interaction.response.send_message(

                "No roles were found.",

                ephemeral=True,

            )


            return


        view = RoleInfoView(

            interaction,

            roles,

        )


        await interaction.response.send_message(

            embed=view.create_embed(),

            view=view,

        )


        view.message = (

            await interaction.original_response()

        )


    @app_commands.command(

        name="role-members",

        description=(

            "View members who have a specific role."

        ),

    )
    @app_commands.describe(

        role=(

            "The role to inspect."

        ),

    )
    async def role_members(

        self,

        interaction: discord.Interaction,

        role: discord.Role,

    ) -> None:

        """
        Display members assigned to a role.
        """

        members = list(
            role.members
        )


        members.sort(

            key=lambda member: (

                member.display_name.lower()

            )

        )


        if not members:

            description = (

                "No members currently have this role."

            )


        else:

            visible_members = members[
                :50
            ]


            lines = []


            for member in visible_members:

                lines.append(

                    f"• {member.mention}"

                )


            description = (

                "\n".join(
                    lines
                )

            )


            if len(
                members
            ) > 50:

                description += (

                    f"\n\nAnd "

                    f"{len(members) - 50} "

                    f"more members."

                )


        embed = discord.Embed(

            title=(

                f"{role.name} Members"

            ),

            description=description,

            color=(

                role.color

                if role.color.value

                else

                discord.Color.blurple()

            ),

        )


        embed.add_field(

            name="Total Members",

            value=(

                f"`{len(members)}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Role Position",

            value=(

                f"`#{role.position}`"

            ),

            inline=True,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Role Members • "

                f"v{BOT_VERSION}"

            ),

        )


        await interaction.response.send_message(

            embed=embed

        )


    @app_commands.command(

        name="role-stats",

        description=(

            "View statistics about server roles."

        ),

    )
    async def role_stats(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """
        Display role distribution statistics.
        """

        guild = interaction.guild


        if guild is None:

            await interaction.response.send_message(

                "This command can only be used inside "
                "a server.",

                ephemeral=True,

            )


            return


        roles = (

            RoleAnalyzer.analyze_guild(
                guild
            )

        )


        category_counts: dict[
            RoleCategory,
            int
        ] = {}


        for role_info in roles:

            category_counts[
                role_info.category
            ] = (

                category_counts.get(

                    role_info.category,

                    0,

                )

                + 1

            )


        embed = discord.Embed(

            title=(

                "PAG Role Statistics"

            ),

            description=(

                "A breakdown of the role structure "
                "within this server."

            ),

            color=discord.Color.blurple(),

        )


        for category in RoleCategory:

            count = category_counts.get(

                category,

                0,

            )


            if count == 0:

                continue


            embed.add_field(

                name=(

                    category.value

                ),

                value=(

                    f"`{count}` roles"

                ),

                inline=True,

            )


        embed.add_field(

            name="Total Roles",

            value=(

                f"`{len(roles)}`"

            ),

            inline=True,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Role Statistics • "

                f"v{BOT_VERSION}"

            ),

        )


        await interaction.response.send_message(

            embed=embed

        )


async def setup(

    bot: commands.Bot,

) -> None:

    """
    Load the RoleInfoCog extension.
    """

    await bot.add_cog(

        RoleInfoCog(

            bot

        )

    )