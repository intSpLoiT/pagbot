"""
PAG Core
Profile Cog

This module contains the PAG member profile system.

The profile system combines:

    - Discord identity
    - Roblox identity
    - Roblox avatar
    - PAG rank
    - Activity statistics
    - Achievement statistics
    - Profile metadata

Current architecture:

    Discord User
          |
          v
    ProfileCog
          |
          v
    RobloxService
          |
          v
    Roblox API
          |
          v
    RobloxUser
          |
          v
    PAG Profile Response


Future integrations:

    - RankService
    - AchievementService
    - ActivityService
    - UserRepository
    - ProfileRenderer
"""


from __future__ import annotations


from typing import Any


import discord


from discord import app_commands


from discord.ext import commands


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


from core.logger import logger


class ProfileCog(commands.Cog):
    """
    PAG member profile system.

    This Cog is responsible for:

        - Displaying member profiles
        - Displaying Roblox identity
        - Displaying avatars
        - Displaying PAG rank information
        - Displaying basic statistics

    The Cog itself does not directly communicate with Roblox.

    Roblox-related operations are delegated to:

        services.roblox_service.RobloxService
    """


    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        """
        Initialize the Profile Cog.
        """

        self.bot = bot


        self.roblox_service: Any = None


        self._service_initialized: bool = False


        logger.info(
            "ProfileCog initialized."
        )


    async def cog_load(self) -> None:
        """
        Initialize services required by the profile system.

        The RobloxService is used to retrieve Roblox identity
        and avatar data.
        """

        logger.info(
            "Initializing ProfileCog services."
        )


        try:

            from services.roblox_service import (
                RobloxService,
            )


            existing_service = getattr(
                self.bot,
                "roblox_service",
                None,
            )


            if existing_service is not None:

                self.roblox_service = (
                    existing_service
                )


            else:

                self.roblox_service = (
                    RobloxService()
                )


            self._service_initialized = True


            logger.info(
                "ProfileCog Roblox service initialized."
            )


        except ModuleNotFoundError:

            self._service_initialized = False


            logger.warning(
                "RobloxService is not available."
            )


        except Exception:

            self._service_initialized = False


            logger.exception(
                "Failed to initialize ProfileCog services."
            )


    async def cog_unload(self) -> None:
        """
        Clean up ProfileCog resources.

        The service is not closed here if it is shared with
        another Cog or registered globally on the bot.

        This prevents one Cog from accidentally shutting down
        a service still used by another system.
        """

        logger.info(
            "ProfileCog unloaded."
        )


    @staticmethod
    def _get_value(
        data: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Safely retrieve a value from either a dictionary
        or an object.
        """

        if data is None:

            return default


        if isinstance(
            data,
            dict,
        ):

            return data.get(
                key,
                default,
            )


        return getattr(
            data,
            key,
            default,
        )


    def _create_profile_embed(
        self,
        interaction: discord.Interaction,
        user_data: Any,
    ) -> discord.Embed:
        """
        Build a PAG member profile embed.

        The design intentionally leaves space for future
        profile systems such as:

            - Rank
            - XP
            - Achievements
            - Activity
            - Events
        """

        username = self._get_value(
            user_data,
            "username",
            "Unknown",
        )


        display_name = self._get_value(
            user_data,
            "display_name",
            username,
        )


        user_id = self._get_value(
            user_data,
            "user_id",
            "Unknown",
        )


        description = self._get_value(
            user_data,
            "description",
            None,
        )


        avatar_url = self._get_value(
            user_data,
            "avatar_url",
            None,
        )


        profile_url = self._get_value(
            user_data,
            "profile_url",
            None,
        )


        embed = discord.Embed(
            title=(
                f"{display_name}"
            ),
            description=(
                f"**Roblox Profile**\n"
                f"`@{username}`"
            ),
            color=discord.Color.blurple(),
            url=profile_url,
        )


        if avatar_url:

            embed.set_thumbnail(
                url=avatar_url
            )


        embed.add_field(
            name="Roblox Username",
            value=(
                f"`{username}`"
            ),
            inline=True,
        )


        embed.add_field(
            name="Roblox User ID",
            value=(
                f"`{user_id}`"
            ),
            inline=True,
        )


        embed.add_field(
            name="PAG Rank",
            value=(
                "Not assigned"
            ),
            inline=True,
        )


        embed.add_field(
            name="Achievements",
            value=(
                "0"
            ),
            inline=True,
        )


        embed.add_field(
            name="Activity",
            value=(
                "0 points"
            ),
            inline=True,
        )


        embed.add_field(
            name="Events",
            value=(
                "0 joined"
            ),
            inline=True,
        )


        if description:

            clean_description = str(
                description
            )


            if len(
                clean_description
            ) > 1024:

                clean_description = (
                    clean_description[
                        :1021
                    ]
                    + "..."
                )


            embed.add_field(
                name="Roblox About",
                value=(
                    clean_description
                ),
                inline=False,
            )


        embed.set_author(
            name=(
                interaction.user.display_name
            ),
            icon_url=(
                interaction.user.display_avatar.url
            ),
        )


        embed.set_footer(
            text=(
                f"{BOT_NAME} • "
                f"PAG Profile System • "
                f"v{BOT_VERSION}"
            ),
        )


        return embed


    @app_commands.command(
        name="profile-2",
        description=(
            "Display a PAG member profile."
        ),
    )
    @app_commands.describe(
        username=(
            "Optional Roblox username."
        ),
    )
    async def profile(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        """
        Display a PAG member profile.

        If no username is provided, the command currently
        uses the Discord user's display name as a fallback.

        Once account linking is implemented, the command will
        automatically retrieve the linked Roblox account.
        """

        if not self._service_initialized:

            embed = discord.Embed(
                title=(
                    "Profile Unavailable"
                ),
                description=(
                    "The Roblox profile service "
                    "is currently unavailable."
                ),
                color=discord.Color.red(),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        if username is None:

            username = (
                interaction.user.display_name
            )


        username = username.strip()


        if not username:

            embed = discord.Embed(
                title=(
                    "Invalid Username"
                ),
                description=(
                    "Please provide a valid Roblox "
                    "username."
                ),
                color=discord.Color.red(),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        await interaction.response.defer()


        try:

            user_data = (
                await self.roblox_service.get_profile(
                    username
                )
            )


        except Exception:

            logger.exception(
                "Profile lookup failed for: %s",
                username,
            )


            embed = discord.Embed(
                title=(
                    "Profile Lookup Failed"
                ),
                description=(
                    "The Roblox profile could not "
                    "be retrieved."
                ),
                color=discord.Color.red(),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        if user_data is None:

            embed = discord.Embed(
                title=(
                    "Profile Not Found"
                ),
                description=(
                    f"No Roblox profile was found "
                    f"for `{username}`."
                ),
                color=discord.Color.red(),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        embed = self._create_profile_embed(
            interaction,
            user_data,
        )


        await interaction.followup.send(
            embed=embed
        )


    @app_commands.command(
        name="my-profile",
        description=(
            "Display your PAG member profile."
        ),
    )
    async def my_profile(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Display the current user's profile.

        The current version uses the Discord display name
        as the Roblox username fallback.

        This will later be replaced by:

            Discord ID
                |
                v
            Linked Roblox Account
                |
                v
            Profile
        """

        await self.profile.callback(
            self,
            interaction,
            interaction.user.display_name,
        )


    @app_commands.command(
        name="profile-preview",
        description=(
            "Preview the PAG profile design."
        ),
    )
    async def profile_preview(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Display a preview profile using sample data.

        This command is useful during development before
        the complete member database exists.
        """

        preview_data = {

            "username": (
                "Velgrath"
            ),

            "display_name": (
                "Velgrath"
            ),

            "user_id": (
                123456789
            ),

            "description": (
                "PAG member profile preview."
            ),

            "avatar_url": None,

            "profile_url": None,

        }


        embed = self._create_profile_embed(
            interaction,
            preview_data,
        )


        embed.title = (
            "PAG Profile Preview"
        )


        embed.set_footer(
            text=(
                f"{BOT_NAME} • "
                "Profile Preview"
            ),
        )


        await interaction.response.send_message(
            embed=embed,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Load the ProfileCog extension.
    """

    await bot.add_cog(
        ProfileCog(
            bot
        )
    )