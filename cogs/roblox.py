"""
PAG Core
Roblox Integration Cog

This module provides Discord commands for interacting with
Roblox-related PAG Core systems.

The Cog is responsible for:

    - Receiving Discord commands
    - Validating user input
    - Calling the Roblox service layer
    - Formatting responses
    - Handling user-facing errors

The Cog is intentionally not responsible for making direct
Roblox API requests.

Architecture:

    Discord User
        |
        v
    /roblox
        |
        v
    RobloxCog
        |
        v
    RobloxService
        |
        v
    Roblox API
        |
        v
    Roblox Data
        |
        v
    Discord Response


Future systems depending on this Cog:

    - Member Profiles
    - Role Info
    - Top 10
    - Member Spotlight
    - Roblox Account Linking
    - Roblox Avatar Display
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


class RobloxCog(commands.Cog):
    """
    Roblox integration commands for PAG Core.

    This Cog acts as the Discord-facing layer of the Roblox
    integration system.

    The Cog should not directly contain:

        - HTTP requests
        - Roblox API URLs
        - API response parsing
        - Cache implementation
        - Database queries

    Those responsibilities belong to:

        services/roblox_service.py

        database/repositories/user_repository.py
    """


    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:
        """
        Initialize the Roblox Cog.

        The bot instance is stored so that the Cog can access
        shared application services in the future.
        """

        self.bot = bot


        self.service: Any = None


        self._service_initialized: bool = False


        logger.info(
            "RobloxCog initialized."
        )


    async def cog_load(self) -> None:
        """
        Prepare the Roblox Cog after it has been loaded.

        The actual RobloxService will be connected here once
        services/roblox_service.py has been created.

        Keeping this lifecycle hook now allows the service to be
        introduced later without changing the Cog architecture.
        """

        logger.info(
            "Preparing Roblox integration."
        )


        try:

            from services.roblox_service import (
                RobloxService,
            )


            self.service = RobloxService()


            self._service_initialized = True


            logger.info(
                "Roblox service initialized."
            )


        except ModuleNotFoundError:

            self._service_initialized = False


            logger.warning(
                "Roblox service is not available yet."
            )


            logger.warning(
                "Roblox commands will remain unavailable "
                "until RobloxService is implemented."
            )


        except Exception:

            self._service_initialized = False


            logger.exception(
                "Failed to initialize Roblox service."
            )


    async def cog_unload(self) -> None:
        """
        Clean up the Roblox Cog.

        If the service later owns an HTTP client session,
        its close method will be called here.
        """

        if self.service is None:

            return


        close_method = getattr(
            self.service,
            "close",
            None,
        )


        if close_method is None:

            return


        try:

            result = close_method()


            if result is not None:

                await result


        except Exception:

            logger.exception(
                "Failed to close Roblox service."
            )


    @staticmethod
    def _create_error_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Create a consistent error embed.

        Keeping error formatting centralized ensures that all
        Roblox commands use the same visual language.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
        )


    @staticmethod
    def _create_info_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Create a consistent informational embed.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple(),
        )


    @staticmethod
    def _create_success_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Create a consistent success embed.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
        )


    def _service_available(self) -> bool:
        """
        Check whether the Roblox service is currently available.

        This prevents commands from crashing if the service has
        not yet been implemented or could not be initialized.
        """

        return (
            self.service is not None
            and self._service_initialized
        )


    async def _send_service_unavailable(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Send a user-friendly service-unavailable response.
        """

        embed = self._create_error_embed(
            title="Roblox Integration Unavailable",
            description=(
                "The Roblox integration is currently "
                "unavailable.\n\n"
                "The service may still be initializing "
                "or temporarily unavailable."
            ),
        )


        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


    @staticmethod
    def _clean_username(
        username: str,
    ) -> str:
        """
        Clean and normalize a Roblox username.

        The command layer performs basic input normalization.

        Deeper validation belongs to the service layer.
        """

        return username.strip()


    @staticmethod
    def _validate_username(
        username: str,
    ) -> bool:
        """
        Perform basic username validation.

        This is intentionally lightweight.

        The Roblox service remains responsible for determining
        whether the username actually exists.
        """

        if not username:

            return False


        if len(username) > 20:

            return False


        return True


    @staticmethod
    def _get_data_value(
        data: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Safely retrieve a value from a service response.

        Supports both:

            dictionaries

        and:

            objects with attributes

        This allows the service layer to evolve from raw
        dictionaries into structured response objects later.
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


    def _build_user_embed(
        self,
        data: Any,
    ) -> discord.Embed:
        """
        Build a visually clean Roblox user information embed.

        The method intentionally accepts flexible service data
        so that the RobloxService can later return a structured
        dataclass instead of a raw dictionary.
        """

        username = self._get_data_value(
            data,
            "username",
            "Unknown",
        )


        display_name = self._get_data_value(
            data,
            "display_name",
            username,
        )


        user_id = self._get_data_value(
            data,
            "user_id",
            "Unknown",
        )


        description = self._get_data_value(
            data,
            "description",
            None,
        )


        avatar_url = self._get_data_value(
            data,
            "avatar_url",
            None,
        )


        profile_url = (
            f"https://www.roblox.com/users/"
            f"{user_id}/profile"
            if user_id != "Unknown"
            else
            None
        )


        embed = discord.Embed(
            title=(
                f"{display_name}"
                if display_name != username
                else
                username
            ),
            description=(
                f"**@{username}**"
            ),
            color=discord.Color.blurple(),
            url=profile_url,
        )


        embed.add_field(
            name="Username",
            value=f"`{username}`",
            inline=True,
        )


        embed.add_field(
            name="User ID",
            value=f"`{user_id}`",
            inline=True,
        )


        if display_name != username:

            embed.add_field(
                name="Display Name",
                value=f"`{display_name}`",
                inline=True,
            )


        if description:

            shortened_description = str(
                description
            )


            if len(
                shortened_description
            ) > 1024:

                shortened_description = (
                    shortened_description[
                        :1021
                    ]
                    + "..."
                )


            embed.add_field(
                name="Description",
                value=shortened_description,
                inline=False,
            )


        if avatar_url:

            embed.set_thumbnail(
                url=avatar_url
            )


        embed.set_footer(
            text=(
                f"{BOT_NAME} • "
                f"Roblox Integration • "
                f"v{BOT_VERSION}"
            ),
        )


        return embed


    @app_commands.command(
        name="roblox",
        description=(
            "Look up a Roblox user."
        ),
    )
    @app_commands.describe(
        username=(
            "The Roblox username to search for."
        ),
    )
    async def roblox(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Look up a Roblox user by username.

        Example:

            /roblox username:Builderman
        """

        username = self._clean_username(
            username
        )


        if not self._validate_username(
            username
        ):

            embed = self._create_error_embed(
                title="Invalid Username",
                description=(
                    "Please enter a valid Roblox "
                    "username."
                ),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        if not self._service_available():

            await self._send_service_unavailable(
                interaction
            )


            return


        await interaction.response.defer()


        try:

            data = await self.service.get_user(
                username
            )


        except Exception:

            logger.exception(
                "Roblox user lookup failed: %s",
                username,
            )


            embed = self._create_error_embed(
                title="Roblox Lookup Failed",
                description=(
                    "An error occurred while retrieving "
                    "this Roblox user."
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        if data is None:

            embed = self._create_error_embed(
                title="User Not Found",
                description=(
                    f"No Roblox user was found for:\n"
                    f"`{username}`"
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        embed = self._build_user_embed(
            data
        )


        await interaction.followup.send(
            embed=embed
        )


    @app_commands.command(
        name="roblox-avatar",
        description=(
            "Display a Roblox user's avatar."
        ),
    )
    @app_commands.describe(
        username=(
            "The Roblox username to look up."
        ),
    )
    async def roblox_avatar(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Display a Roblox avatar thumbnail.

        The thumbnail itself is retrieved by the service layer.
        """

        username = self._clean_username(
            username
        )


        if not self._validate_username(
            username
        ):

            embed = self._create_error_embed(
                title="Invalid Username",
                description=(
                    "Please enter a valid Roblox "
                    "username."
                ),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        if not self._service_available():

            await self._send_service_unavailable(
                interaction
            )


            return


        await interaction.response.defer()


        try:

            data = await self.service.get_user(
                username
            )


        except Exception:

            logger.exception(
                "Roblox avatar lookup failed: %s",
                username,
            )


            embed = self._create_error_embed(
                title="Avatar Lookup Failed",
                description=(
                    "The Roblox avatar could not "
                    "be retrieved."
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        if data is None:

            embed = self._create_error_embed(
                title="User Not Found",
                description=(
                    f"No Roblox user was found for:\n"
                    f"`{username}`"
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        actual_username = self._get_data_value(
            data,
            "username",
            username,
        )


        display_name = self._get_data_value(
            data,
            "display_name",
            actual_username,
        )


        user_id = self._get_data_value(
            data,
            "user_id",
            None,
        )


        avatar_url = self._get_data_value(
            data,
            "avatar_url",
            None,
        )


        embed = discord.Embed(
            title=display_name,
            description=(
                f"Roblox avatar of "
                f"**{actual_username}**"
            ),
            color=discord.Color.blurple(),
        )


        if avatar_url:

            embed.set_image(
                url=avatar_url
            )


        if user_id is not None:

            embed.add_field(
                name="User ID",
                value=f"`{user_id}`",
                inline=True,
            )


        embed.set_footer(
            text=(
                f"{BOT_NAME} • "
                f"Roblox Avatar System"
            ),
        )


        await interaction.followup.send(
            embed=embed
        )


    @app_commands.command(
        name="roblox-profile",
        description=(
            "Display a detailed Roblox profile."
        ),
    )
    @app_commands.describe(
        username=(
            "The Roblox username to look up."
        ),
    )
    async def roblox_profile(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Display an expanded Roblox profile.

        This command is designed to become the foundation
        for the future PAG member profile system.
        """

        username = self._clean_username(
            username
        )


        if not self._validate_username(
            username
        ):

            embed = self._create_error_embed(
                title="Invalid Username",
                description=(
                    "Please enter a valid Roblox "
                    "username."
                ),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        if not self._service_available():

            await self._send_service_unavailable(
                interaction
            )


            return


        await interaction.response.defer()


        try:

            data = await self.service.get_profile(
                username
            )


        except AttributeError:

            logger.warning(
                "RobloxService does not yet implement "
                "get_profile()."
            )


            try:

                data = await self.service.get_user(
                    username
                )


            except Exception:

                logger.exception(
                    "Fallback Roblox lookup failed."
                )


                embed = self._create_error_embed(
                    title="Profile Unavailable",
                    description=(
                        "The Roblox profile service "
                        "is not ready yet."
                    ),
                )


                await interaction.followup.send(
                    embed=embed
                )


                return


        except Exception:

            logger.exception(
                "Roblox profile lookup failed: %s",
                username,
            )


            embed = self._create_error_embed(
                title="Profile Lookup Failed",
                description=(
                    "An error occurred while retrieving "
                    "the Roblox profile."
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        if data is None:

            embed = self._create_error_embed(
                title="User Not Found",
                description=(
                    f"No Roblox user was found for:\n"
                    f"`{username}`"
                ),
            )


            await interaction.followup.send(
                embed=embed
            )


            return


        embed = self._build_user_embed(
            data
        )


        created_at = self._get_data_value(
            data,
            "created_at",
            None,
        )


        is_banned = self._get_data_value(
            data,
            "is_banned",
            None,
        )


        if created_at:

            embed.add_field(
                name="Account Created",
                value=str(
                    created_at
                ),
                inline=True,
            )


        if is_banned is not None:

            embed.add_field(
                name="Account Status",
                value=(
                    "Banned"
                    if is_banned
                    else
                    "Active"
                ),
                inline=True,
            )


        await interaction.followup.send(
            embed=embed
        )


    @app_commands.command(
        name="roblox-link",
        description=(
            "Link a Roblox account to your PAG profile."
        ),
    )
    @app_commands.describe(
        username=(
            "The Roblox username to link."
        ),
    )
    async def roblox_link(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Link a Roblox account to a Discord user.

        The actual database operation will be implemented
        through the service and repository layers.

        This command is currently prepared as the public
        interface for the future account-linking system.
        """

        username = self._clean_username(
            username
        )


        if not self._validate_username(
            username
        ):

            embed = self._create_error_embed(
                title="Invalid Username",
                description=(
                    "Please enter a valid Roblox "
                    "username."
                ),
            )


            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )


            return


        if not self._service_available():

            await self._send_service_unavailable(
                interaction
            )


            return


        await interaction.response.defer(
            ephemeral=True
        )


        try:

            user_data = await self.service.get_user(
                username
            )


        except Exception:

            logger.exception(
                "Roblox account linking lookup failed."
            )


            embed = self._create_error_embed(
                title="Account Linking Failed",
                description=(
                    "The Roblox account could not "
                    "be verified."
                ),
            )


            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )


            return


        if user_data is None:

            embed = self._create_error_embed(
                title="Roblox User Not Found",
                description=(
                    "The Roblox username could not "
                    "be found."
                ),
            )


            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )


            return


        user_id = self._get_data_value(
            user_data,
            "user_id",
            None,
        )


        actual_username = self._get_data_value(
            user_data,
            "username",
            username,
        )


        if user_id is None:

            embed = self._create_error_embed(
                title="Invalid Roblox Data",
                description=(
                    "Roblox returned incomplete "
                    "user information."
                ),
            )


            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )


            return


        try:

            link_method = getattr(
                self.service,
                "link_account",
                None,
            )


            if link_method is None:

                embed = self._create_info_embed(
                    title="Account Linking Prepared",
                    description=(
                        "The Roblox account was found, "
                        "but the database linking system "
                        "is not implemented yet."
                    ),
                )


                embed.add_field(
                    name="Roblox Username",
                    value=(
                        f"`{actual_username}`"
                    ),
                    inline=True,
                )


                embed.add_field(
                    name="Roblox User ID",
                    value=f"`{user_id}`",
                    inline=True,
                )


                await interaction.followup.send(
                    embed=embed,
                    ephemeral=True,
                )


                return


            await link_method(
                discord_id=interaction.user.id,
                roblox_id=user_id,
                roblox_username=actual_username,
            )


        except Exception:

            logger.exception(
                "Failed to link Roblox account."
            )


            embed = self._create_error_embed(
                title="Account Linking Failed",
                description=(
                    "The Roblox account could not "
                    "be linked."
                ),
            )


            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )


            return


        embed = self._create_success_embed(
            title="Roblox Account Linked",
            description=(
                "Your Roblox account has been "
                "successfully linked to PAG."
            ),
        )


        embed.add_field(
            name="Username",
            value=f"`{actual_username}`",
            inline=True,
        )


        embed.add_field(
            name="User ID",
            value=f"`{user_id}`",
            inline=True,
        )


        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


    @roblox.autocomplete(
        "username"
    )
    async def roblox_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        Provide username autocomplete suggestions.

        This is intentionally prepared for a future
        Roblox username search service.

        The service can later search Roblox users based on
        the current input and return suggestions.
        """

        if not current:

            return []


        if not self._service_available():

            return []


        search_method = getattr(
            self.service,
            "search_users",
            None,
        )


        if search_method is None:

            return []


        try:

            results = await search_method(
                current
            )


        except Exception:

            logger.exception(
                "Roblox username autocomplete failed."
            )


            return []


        choices: list[
            app_commands.Choice[str]
        ] = []


        for result in results[:25]:

            username = self._get_data_value(
                result,
                "username",
                None,
            )


            if not username:

                continue


            choices.append(
                app_commands.Choice(
                    name=str(
                        username
                    )[
                        :100
                    ],
                    value=str(
                        username
                    )[
                        :100
                    ],
                )
            )


        return choices


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Load the Roblox Cog.

    The extension loader automatically discovers this
    setup function and loads the Cog.
    """

    await bot.add_cog(
        RobloxCog(
            bot
        )
    )
