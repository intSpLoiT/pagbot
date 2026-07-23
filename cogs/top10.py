"""
PAG Core
Top 10 Cog

This Cog provides the complete Discord interface
for the PAG Top 10 ranking system.

Features:

    /top10
        Display the current Top 10 ranking.

    /top10-set
        Add or replace a player at a position.

    /top10-edit
        Edit an existing player.

    /top10-remove
        Remove a player.

    /top10-reset
        Clear the entire Top 10.

The ranking system follows one simple rule:

    Position 1 = Best player

    Position 2 = Second best player

    Position 3 = Third best player

    ...

    Position 10 = Tenth best player


The actual data is managed by:

    services.top10_service.Top10Service

This Cog is responsible for:

    - Discord commands
    - Discord permissions
    - Embeds
    - Buttons
    - Pagination
    - Error handling
"""


from __future__ import annotations


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


from services.top10_service import (
    Top10Entry,
    Top10Error,
    Top10Service,
    InvalidPositionError,
    PlayerAlreadyExistsError,
    PlayerNotFoundError,
    PositionOccupiedError,
)


class Top10PermissionError(
    Top10Error
):
    """
    Raised when a user is not allowed to
    modify the Top 10.
    """


class Top10View(
    discord.ui.View
):
    """
    Interactive Top 10 display.

    The view displays one player per page.

    Page 1:

        #1 Player

    Page 2:

        #2 Player

    ...

    Page 10:

        #10 Player

    This makes the Roblox avatar much more visible
    and gives each ranked player their own visual
    profile card.
    """


    def __init__(
        self,

        interaction: discord.Interaction,

        entries: list[Top10Entry],

        *,

        timeout: float = 300,

    ) -> None:

        super().__init__(

            timeout=timeout

        )


        self.owner_id = (

            interaction.user.id

        )


        self.entries = (

            entries

        )


        self.page = 0


        self.message: Optional[

            discord.InteractionMessage

        ] = None


        self._refresh_buttons()


    async def interaction_check(

        self,

        interaction: discord.Interaction,

    ) -> bool:

        """
        Ensure only the original user
        controls the panel.
        """

        if (

            interaction.user.id

            !=

            self.owner_id

        ):

            await interaction.response.send_message(

                (

                    "Only the user who opened "

                    "this Top 10 panel can "

                    "control it."

                ),

                ephemeral=True,

            )


            return False


        return True


    def _refresh_buttons(

        self,

    ) -> None:

        """
        Update navigation button states.
        """

        self.previous_button.disabled = (

            self.page <= 0

        )


        self.next_button.disabled = (

            self.page

            >=

            len(

                self.entries

            )

            - 1

        )


    def _get_current_entry(

        self,

    ) -> Top10Entry | None:

        """
        Return the currently displayed entry.
        """

        if not self.entries:

            return None


        if (

            self.page

            >=

            len(

                self.entries

            )

        ):

            return None


        return self.entries[

            self.page

        ]


    def create_embed(

        self,

    ) -> discord.Embed:

        """
        Build the visual Top 10 profile card.
        """

        entry = (

            self._get_current_entry()

        )


        if entry is None:

            return discord.Embed(

                title=(

                    "PAG TOP 10"

                ),

                description=(

                    "The Top 10 is currently empty."

                ),

                color=discord.Color.blurple(),

            )


        if entry.position == 1:

            title_prefix = (

                "1st"

            )

        elif entry.position == 2:

            title_prefix = (

                "2nd"

            )

        elif entry.position == 3:

            title_prefix = (

                "3rd"

            )

        else:

            title_prefix = (

                f"{entry.position}th"

            )


        embed = discord.Embed(

            title=(

                f"PAG TOP 10"

            ),

            description=(

                f"## #{entry.position} "

                f"{entry.roblox_display_name}\n\n"

                f"`{entry.roblox_username}`"

            ),

            color=discord.Color.blurple(),

            url=entry.profile_url,

        )


        if entry.avatar_url:

            embed.set_thumbnail(

                url=entry.avatar_url

            )


        embed.add_field(

            name=(

                "Position"

            ),

            value=(

                f"**#{entry.position}**\n"

                f"{title_prefix} place"

            ),

            inline=True,

        )


        embed.add_field(

            name=(

                "PAG Rank"

            ),

            value=(

                f"**{entry.rank}**"

            ),

            inline=True,

        )


        embed.add_field(

            name=(

                "Roblox ID"

            ),

            value=(

                f"`{entry.roblox_user_id}`"

            ),

            inline=True,

        )


        if entry.notes:

            embed.add_field(

                name=(

                    "Notes"

                ),

                value=(

                    entry.notes[:1024]

                ),

                inline=False,

            )


        embed.add_field(

            name=(

                "Ranking System"

            ),

            value=(

                "Lower position number = "

                "higher ranking."

            ),

            inline=False,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Top 10 • "

                f"{self.page + 1}/"

                f"{len(self.entries)} • "

                f"v{BOT_VERSION}"

            ),

        )


        return embed


    @discord.ui.button(

        label="Previous",

        style=discord.ButtonStyle.secondary,

        emoji="◀",

    )
    async def previous_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """
        Display the previous ranked player.
        """

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
    async def next_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """
        Display the next ranked player.
        """

        if (

            self.page

            <

            len(

                self.entries

            )

            - 1

        ):

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
    async def close_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """
        Disable the interface.
        """

        for child in self.children:

            child.disabled = True


        await interaction.response.edit_message(

            embed=self.create_embed(),

            view=self,

        )


class Top10Cog(
    commands.Cog
):
    """
    Discord interface for the PAG Top 10 system.
    """


    def __init__(

        self,

        bot: commands.Bot,

    ) -> None:

        self.bot = bot


        self.service: Top10Service | None = None


        logger.info(

            "Top10Cog initialized."

        )


    async def cog_load(

        self,

    ) -> None:

        """
        Initialize the Top10Service.

        The Cog first attempts to use a shared
        service registered on the bot.

        If one does not exist, a local service
        is created.
        """

        existing_service = getattr(

            self.bot,

            "top10_service",

            None,

        )


        if existing_service is not None:

            self.service = (

                existing_service

            )


            logger.info(

                "Using shared Top10Service."

            )


            return


        roblox_service = getattr(

            self.bot,

            "roblox_service",

            None,

        )


        database_path = (

            "data/pag.db"

        )


        self.service = (

            Top10Service(

                database_path=database_path,

                roblox_service=roblox_service,

            )

        )


        self.bot.top10_service = (

            self.service

        )


        logger.info(

            "Top10Service created by Top10Cog."

        )


    def _require_service(

        self,

    ) -> Top10Service:

        """
        Return the active Top10Service.
        """

        if self.service is None:

            raise Top10Error(

                "Top10Service is not initialized."

            )


        return self.service


    @staticmethod
    def _is_staff(

        interaction: discord.Interaction,

    ) -> bool:

        """
        Determine whether the user can manage
        Top 10 entries.

        Current permission system:

            - Administrator permission
            - Manage Guild permission

        This can later be replaced with
        custom PAG staff roles.
        """

        if interaction.guild is None:

            return False


        member = interaction.user


        if not isinstance(

            member,

            discord.Member,

        ):

            return False


        permissions = (

            member.guild_permissions

        )


        return (

            permissions.administrator

            or

            permissions.manage_guild

        )


    @app_commands.command(

        name="top10",

        description=(

            "View the PAG Top 10 ranking."

        ),

    )
    async def top10(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """
        Display the current Top 10.
        """

        service = (

            self._require_service()

        )


        entries = (

            await service.get_all()

        )


        if not entries:

            embed = discord.Embed(

                title=(

                    "PAG TOP 10"

                ),

                description=(

                    "The Top 10 is currently empty."

                ),

                color=discord.Color.blurple(),

            )


            embed.set_footer(

                text=(

                    f"{BOT_NAME} • "

                    f"Top 10 • "

                    f"v{BOT_VERSION}"

                ),

            )


            await interaction.response.send_message(

                embed=embed

            )


            return


        view = (

            Top10View(

                interaction,

                entries,

            )

        )


        await interaction.response.send_message(

            embed=view.create_embed(),

            view=view,

        )


        view.message = (

            await interaction.original_response()

        )


    @app_commands.command(

        name="top10-set",

        description=(

            "Add a player to the PAG Top 10."

        ),

    )
    @app_commands.describe(

        position=(

            "Ranking position from 1 to 10."

        ),

        username=(

            "Roblox username."

        ),

        rank=(

            "PAG rank, for example PT1."

        ),

        notes=(

            "Optional notes about the player."

        ),

    )
    async def top10_set(

        self,

        interaction: discord.Interaction,

        position: app_commands.Range[

            int,

            1,

            10

        ],

        username: str,

        rank: str,

        notes: str | None = None,

    ) -> None:

        """
        Add a player to a specific Top 10 position.
        """

        if not self._is_staff(

            interaction

        ):

            await interaction.response.send_message(

                (

                    "You do not have permission "

                    "to modify the Top 10."

                ),

                ephemeral=True,

            )


            return


        service = (

            self._require_service()

        )


        await interaction.response.defer(

            ephemeral=True

        )


        try:

            entry = (

                await service.add(

                    position=int(

                        position

                    ),

                    username=username,

                    rank=rank,

                    added_by=interaction.user.id,

                    notes=notes,

                    replace_existing=False,

                )

            )


        except PositionOccupiedError:

            await interaction.followup.send(

                (

                    f"Position **#{position}** "

                    "is already occupied."

                ),

                ephemeral=True,

            )


            return


        except PlayerAlreadyExistsError:

            await interaction.followup.send(

                (

                    f"**{username}** is already "

                    "in the Top 10."

                ),

                ephemeral=True,

            )


            return


        except PlayerNotFoundError:

            await interaction.followup.send(

                (

                    f"Roblox user **{username}** "

                    "could not be found."

                ),

                ephemeral=True,

            )


            return


        except Top10Error as error:

            await interaction.followup.send(

                str(error),

                ephemeral=True,

            )


            return


        except Exception:

            logger.exception(

                "Unexpected error while adding Top 10 player."

            )


            await interaction.followup.send(

                (

                    "An unexpected error occurred "

                    "while adding the player."

                ),

                ephemeral=True,

            )


            return


        embed = discord.Embed(

            title=(

                "Top 10 Updated"

            ),

            description=(

                f"**#{entry.position}** "

                f"{entry.roblox_display_name}\n"

                f"`{entry.roblox_username}`"

            ),

            color=discord.Color.green(),

        )


        if entry.avatar_url:

            embed.set_thumbnail(

                url=entry.avatar_url

            )


        embed.add_field(

            name=(

                "PAG Rank"

            ),

            value=(

                f"`{entry.rank}`"

            ),

            inline=True,

        )


        embed.add_field(

            name=(

                "Position"

            ),

            value=(

                f"`#{entry.position}`"

            ),

            inline=True,

        )


        await interaction.followup.send(

            embed=embed,

            ephemeral=True,

        )


    @app_commands.command(

        name="top10-edit",

        description=(

            "Edit an existing Top 10 player."

        ),

    )
    @app_commands.describe(

        position=(

            "Current position."

        ),

        username=(

            "New Roblox username."

        ),

        rank=(

            "New PAG rank."

        ),

        notes=(

            "New notes."

        ),

        new_position=(

            "Move the player to another position."

        ),

    )
    async def top10_edit(

        self,

        interaction: discord.Interaction,

        position: app_commands.Range[

            int,

            1,

            10

        ],

        username: str | None = None,

        rank: str | None = None,

        notes: str | None = None,

        new_position: app_commands.Range[

            int,

            1,

            10

        ] | None = None,

    ) -> None:

        """
        Edit a Top 10 entry.
        """

        if not self._is_staff(

            interaction

        ):

            await interaction.response.send_message(

                (

                    "You do not have permission "

                    "to modify the Top 10."

                ),

                ephemeral=True,

            )


            return


        service = (

            self._require_service()

        )


        await interaction.response.defer(

            ephemeral=True

        )


        try:

            entry = (

                await service.update(

                    position=int(

                        position

                    ),

                    updated_by=interaction.user.id,

                    username=username,

                    rank=rank,

                    notes=notes,

                    new_position=(

                        int(

                            new_position

                        )

                        if new_position

                        is not None

                        else

                        None

                    ),

                )

            )


        except PlayerNotFoundError:

            await interaction.followup.send(

                (

                    f"No player exists at "

                    f"position **#{position}**."

                ),

                ephemeral=True,

            )


            return


        except PositionOccupiedError as error:

            await interaction.followup.send(

                str(error),

                ephemeral=True,

            )


            return


        except Top10Error as error:

            await interaction.followup.send(

                str(error),

                ephemeral=True,

            )


            return


        embed = discord.Embed(

            title=(

                "Top 10 Entry Updated"

            ),

            description=(

                f"**#{entry.position}** "

                f"{entry.roblox_display_name}\n"

                f"`{entry.roblox_username}`"

            ),

            color=discord.Color.green(),

        )


        if entry.avatar_url:

            embed.set_thumbnail(

                url=entry.avatar_url

            )


        embed.add_field(

            name=(

                "PAG Rank"

            ),

            value=(

                f"`{entry.rank}`"

            ),

            inline=True,

        )


        await interaction.followup.send(

            embed=embed,

            ephemeral=True,

        )


    @app_commands.command(

        name="top10-remove",

        description=(

            "Remove a player from the PAG Top 10."

        ),

    )
    @app_commands.describe(

        position=(

            "Position to remove."

        ),

    )
    async def top10_remove(

        self,

        interaction: discord.Interaction,

        position: app_commands.Range[

            int,

            1,

            10

        ],

    ) -> None:

        """
        Remove a player from the Top 10.
        """

        if not self._is_staff(

            interaction

        ):

            await interaction.response.send_message(

                (

                    "You do not have permission "

                    "to modify the Top 10."

                ),

                ephemeral=True,

            )


            return


        service = (

            self._require_service()

        )


        try:

            entry = (

                await service.remove(

                    int(

                        position

                    )

                )

            )


        except PlayerNotFoundError:

            await interaction.response.send_message(

                (

                    f"No player exists at "

                    f"position **#{position}**."

                ),

                ephemeral=True,

            )


            return


        embed = discord.Embed(

            title=(

                "Top 10 Player Removed"

            ),

            description=(

                f"**#{entry.position}** "

                f"{entry.roblox_display_name} "

                "has been removed from the Top 10."

            ),

            color=discord.Color.orange(),

        )


        await interaction.response.send_message(

            embed=embed,

            ephemeral=True,

        )


    @app_commands.command(

        name="top10-reset",

        description=(

            "Clear the entire PAG Top 10."

        ),

    )
    async def top10_reset(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """
        Clear all Top 10 entries.

        This operation requires administrator
        permission.
        """

        if interaction.guild is None:

            await interaction.response.send_message(

                (

                    "This command can only be "

                    "used inside a server."

                ),

                ephemeral=True,

            )


            return


        member = interaction.user


        if not isinstance(

            member,

            discord.Member,

        ):

            await interaction.response.send_message(

                (

                    "This command can only be "

                    "used inside a server."

                ),

                ephemeral=True,

            )


            return


        if not member.guild_permissions.administrator:

            await interaction.response.send_message(

                (

                    "Only server administrators "

                    "can reset the Top 10."

                ),

                ephemeral=True,

            )


            return


        service = (

            self._require_service()

        )


        deleted_count = (

            await service.clear()

        )


        embed = discord.Embed(

            title=(

                "Top 10 Reset"

            ),

            description=(

                f"Removed **{deleted_count}** "

                "entries from the Top 10."

            ),

            color=discord.Color.red(),

        )


        await interaction.response.send_message(

            embed=embed,

            ephemeral=True,

        )


async def setup(

    bot: commands.Bot,

) -> None:

    """
    Load the Top10Cog extension.
    """

    await bot.add_cog(

        Top10Cog(

            bot

        )

    )