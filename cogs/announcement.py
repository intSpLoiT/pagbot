"""
PAG Core
Announcement Cog

Professional announcement creation system.

Command:

    /announcement

Only server administrators can use this system.

The system provides:

    - Announcement types
    - Structured templates
    - Interactive editing
    - Channel selection
    - Preview
    - Confirmation before sending
    - Controlled mentions
    - Professional embeds

Supported announcement types:

    - Update
    - Event
    - Important
    - Rank
    - Recruitment
    - Partnership
    - Maintenance
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


from core.logger import logger


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


class AnnouncementType(
    Enum
):
    """
    Available announcement categories.
    """


    UPDATE = (

        "Update"

    )


    EVENT = (

        "Event"

    )


    IMPORTANT = (

        "Important"

    )


    RANK = (

        "Rank Update"

    )


    RECRUITMENT = (

        "Recruitment"

    )


    PARTNERSHIP = (

        "Partnership"

    )


    MAINTENANCE = (

        "Maintenance"

    )


@dataclass
class AnnouncementData:
    """
    Stores announcement information.
    """


    announcement_type: AnnouncementType = (

        AnnouncementType.UPDATE

    )


    title: str = ""


    description: str = ""


    channel_id: int | None = None


    mention: str = ""


    def get_color(

        self,

    ) -> discord.Color:

        """
        Return a color based on
        announcement category.
        """

        colors = {

            AnnouncementType.UPDATE:

                discord.Color.blurple(),

            AnnouncementType.EVENT:

                discord.Color.green(),

            AnnouncementType.IMPORTANT:

                discord.Color.red(),

            AnnouncementType.RANK:

                discord.Color.gold(),

            AnnouncementType.RECRUITMENT:

                discord.Color.purple(),

            AnnouncementType.PARTNERSHIP:

                discord.Color.teal(),

            AnnouncementType.MAINTENANCE:

                discord.Color.orange(),

        }


        return colors.get(

            self.announcement_type,

            discord.Color.blurple(),

        )


    def get_prefix(

        self,

    ) -> str:

        """
        Return the visual announcement prefix.
        """

        prefixes = {

            AnnouncementType.UPDATE:

                "PAG UPDATE",

            AnnouncementType.EVENT:

                "PAG EVENT",

            AnnouncementType.IMPORTANT:

                "PAG IMPORTANT",

            AnnouncementType.RANK:

                "PAG RANK SYSTEM",

            AnnouncementType.RECRUITMENT:

                "PAG RECRUITMENT",

            AnnouncementType.PARTNERSHIP:

                "PAG PARTNERSHIP",

            AnnouncementType.MAINTENANCE:

                "PAG MAINTENANCE",

        }


        return prefixes.get(

            self.announcement_type,

            "PAG ANNOUNCEMENT",

        )


    def create_embed(

        self,

    ) -> discord.Embed:

        """
        Build the final announcement embed.
        """

        title = (

            self.title.strip()

            if self.title.strip()

            else

            "New Announcement"

        )


        description = (

            self.description.strip()

            if self.description.strip()

            else

            "No announcement content has been provided."

        )


        embed = discord.Embed(

            title=(

                f"{self.get_prefix()}\n"

                f"{title}"

            )[:256],

            description=description[:4096],

            color=self.get_color(),

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"{self.announcement_type.value} • "

                f"v{BOT_VERSION}"

            )

        )


        return embed


class AnnouncementTypeSelect(
    discord.ui.Select
):
    """
    Dropdown for selecting an announcement type.
    """


    def __init__(

        self,

        view: "AnnouncementView",

    ) -> None:

        self.announcement_view = view


        options = [

            discord.SelectOption(

                label="Update",

                description=(

                    "General clan updates."

                ),

                value="UPDATE",

                emoji="📢",

            ),

            discord.SelectOption(

                label="Event",

                description=(

                    "Events and activities."

                ),

                value="EVENT",

                emoji="🎉",

            ),

            discord.SelectOption(

                label="Important",

                description=(

                    "Important server information."

                ),

                value="IMPORTANT",

                emoji="⚠️",

            ),

            discord.SelectOption(

                label="Rank Update",

                description=(

                    "Rank system changes."

                ),

                value="RANK",

                emoji="🏆",

            ),

            discord.SelectOption(

                label="Recruitment",

                description=(

                    "Recruitment announcements."

                ),

                value="RECRUITMENT",

                emoji="👥",

            ),

            discord.SelectOption(

                label="Partnership",

                description=(

                    "Partnership announcements."

                ),

                value="PARTNERSHIP",

                emoji="🤝",

            ),

            discord.SelectOption(

                label="Maintenance",

                description=(

                    "Maintenance information."

                ),

                value="MAINTENANCE",

                emoji="🔧",

            ),

        ]


        super().__init__(

            placeholder=(

                "Select announcement type..."

            ),

            options=options,

            row=0,

        )


    async def callback(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Update the announcement category.
        """

        selected = (

            self.values[0]

        )


        self.announcement_view.data.announcement_type = (

            AnnouncementType[

                selected

            ]

        )


        await interaction.response.edit_message(

            embed=(

                self.announcement_view.create_panel_embed()

            ),

            view=self.announcement_view,

        )


class AnnouncementContentModal(
    discord.ui.Modal
):
    """
    Modal for editing announcement content.
    """


    def __init__(

        self,

        view: "AnnouncementView",

    ) -> None:

        super().__init__(

            title="Edit Announcement"

        )


        self.announcement_view = view


        self.title_input = discord.ui.TextInput(

            label="Announcement Title",

            placeholder=(

                "Example: New Rank System"

            ),

            default=(

                view.data.title

                if view.data.title

                else

                None

            ),

            max_length=200,

            required=True,

        )


        self.description_input = discord.ui.TextInput(

            label="Announcement Content",

            placeholder=(

                "Write the announcement..."

            ),

            default=(

                view.data.description

                if view.data.description

                else

                None

            ),

            style=discord.TextStyle.paragraph,

            max_length=4096,

            required=True,

        )


        self.add_item(

            self.title_input

        )


        self.add_item(

            self.description_input

        )


    async def on_submit(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save announcement content.
        """

        self.announcement_view.data.title = (

            str(

                self.title_input.value

            ).strip()

        )


        self.announcement_view.data.description = (

            str(

                self.description_input.value

            ).strip()

        )


        await interaction.response.edit_message(

            embed=(

                self.announcement_view.create_panel_embed()

            ),

            view=self.announcement_view,

        )


class AnnouncementMentionModal(
    discord.ui.Modal
):
    """
    Modal for configuring mentions.
    """


    def __init__(

        self,

        view: "AnnouncementView",

    ) -> None:

        super().__init__(

            title="Announcement Mention"

        )


        self.announcement_view = view


        self.mention_input = discord.ui.TextInput(

            label="Mention",

            placeholder=(

                "Leave empty, @everyone, or @here"

            ),

            default=(

                view.data.mention

                if view.data.mention

                else

                None

            ),

            max_length=20,

            required=False,

        )


        self.add_item(

            self.mention_input

        )


    async def on_submit(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save the mention.
        """

        mention = (

            str(

                self.mention_input.value

            ).strip()

        )


        if mention not in (

            "",

            "@everyone",

            "@here",

        ):

            await interaction.response.send_message(

                (

                    "Only `@everyone` and `@here` "

                    "are supported."

                ),

                ephemeral=True,

            )


            return


        self.announcement_view.data.mention = (

            mention

        )


        await interaction.response.edit_message(

            embed=(

                self.announcement_view.create_panel_embed()

            ),

            view=self.announcement_view,

        )


class AnnouncementChannelSelect(
    discord.ui.ChannelSelect
):
    """
    Channel selector.
    """


    def __init__(

        self,

        view: "AnnouncementView",

    ) -> None:

        self.announcement_view = view


        super().__init__(

            placeholder=(

                "Select announcement channel..."

            ),

            channel_types=[

                discord.ChannelType.text,

                discord.ChannelType.news,

            ],

            min_values=1,

            max_values=1,

            row=1,

        )


    async def callback(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save selected channel.
        """

        channel = (

            self.values[0]

        )


        self.announcement_view.data.channel_id = (

            channel.id

        )


        await interaction.response.edit_message(

            embed=(

                self.announcement_view.create_panel_embed()

            ),

            view=self.announcement_view,

        )


class AnnouncementView(
    discord.ui.View
):
    """
    Main announcement management panel.
    """


    def __init__(

        self,

        interaction: discord.Interaction,

    ) -> None:

        super().__init__(

            timeout=600

        )


        self.owner_id = (

            interaction.user.id

        )


        self.data = (

            AnnouncementData()

        )


        self.closed = False


        self.add_item(

            AnnouncementTypeSelect(

                self

            )

        )


        self.add_item(

            AnnouncementChannelSelect(

                self

            )

        )


    async def interaction_check(

        self,

        interaction: discord.Interaction,

    ) -> bool:

        """

        Only the original administrator
        can control this panel.
        """

        if (

            interaction.user.id

            !=

            self.owner_id

        ):

            await interaction.response.send_message(

                (

                    "This announcement panel belongs "

                    "to another administrator."

                ),

                ephemeral=True,

            )


            return False


        return True


    def create_panel_embed(

        self,

    ) -> discord.Embed:

        """

        Create the management panel.
        """

        target = (

            "Not selected"

        )


        if self.data.channel_id:

            target = (

                f"<#{self.data.channel_id}>"

            )


        embed = discord.Embed(

            title=(

                "PAG ANNOUNCEMENT SYSTEM"

            ),

            description=(

                "Create a professional clan "

                "announcement.\n\n"

                "Select a category, edit the content, "

                "choose a channel, preview the message, "

                "then send it."

            ),

            color=self.data.get_color(),

        )


        embed.add_field(

            name="Type",

            value=(

                f"`{self.data.announcement_type.value}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Channel",

            value=target,

            inline=True,

        )


        embed.add_field(

            name="Title",

            value=(

                self.data.title[:1024]

                if self.data.title

                else

                "`Not configured`"

            ),

            inline=False,

        )


        embed.add_field(

            name="Content",

            value=(

                "Configured"

                if self.data.description

                else

                "`Not configured`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Mention",

            value=(

                self.data.mention

                if self.data.mention

                else

                "None"

            ),

            inline=True,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Announcement System • "

                f"v{BOT_VERSION}"

            )

        )


        return embed


    @discord.ui.button(

        label="Edit Content",

        style=discord.ButtonStyle.primary,

        row=2,

    )
    async def edit_content(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the content editor.
        """

        await interaction.response.send_modal(

            AnnouncementContentModal(

                self

            )

        )


    @discord.ui.button(

        label="Mention",

        style=discord.ButtonStyle.secondary,

        row=2,

    )
    async def edit_mention(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the mention editor.
        """

        await interaction.response.send_modal(

            AnnouncementMentionModal(

                self

            )

        )


    @discord.ui.button(

        label="Preview",

        style=discord.ButtonStyle.success,

        row=3,

    )
    async def preview(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Show the final announcement preview.
        """

        if not self.data.title:

            await interaction.response.send_message(

                (

                    "Please configure an announcement "

                    "title first."

                ),

                ephemeral=True,

            )


            return


        if not self.data.description:

            await interaction.response.send_message(

                (

                    "Please configure announcement "

                    "content first."

                ),

                ephemeral=True,

            )


            return


        await interaction.response.send_message(

            content=(

                self.data.mention

                if self.data.mention

                else

                None

            ),

            embed=self.data.create_embed(),

            ephemeral=True,

        )


    @discord.ui.button(

        label="Send Announcement",

        style=discord.ButtonStyle.success,

        row=3,

    )
    async def send(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Send the announcement.
        """

        if not self.data.title:

            await interaction.response.send_message(

                (

                    "The announcement needs a title."

                ),

                ephemeral=True,

            )


            return


        if not self.data.description:

            await interaction.response.send_message(

                (

                    "The announcement needs content."

                ),

                ephemeral=True,

            )


            return


        if self.data.channel_id is None:

            await interaction.response.send_message(

                (

                    "Please select a channel."

                ),

                ephemeral=True,

            )


            return


        if interaction.guild is None:

            await interaction.response.send_message(

                (

                    "This command can only be used "

                    "inside a server."

                ),

                ephemeral=True,

            )


            return


        channel = (

            interaction.guild.get_channel(

                self.data.channel_id

            )

        )


        if not isinstance(

            channel,

            (

                discord.TextChannel,

                discord.NewsChannel,

            ),

        ):

            await interaction.response.send_message(

                (

                    "The selected channel is invalid."

                ),

                ephemeral=True,

            )


            return


        try:

            await channel.send(

                content=(

                    self.data.mention

                    if self.data.mention

                    else

                    None

                ),

                embed=self.data.create_embed(),

                allowed_mentions=discord.AllowedMentions(

                    everyone=(

                        self.data.mention

                        in

                        (

                            "@everyone",

                            "@here",

                        )

                    )

                ),

            )


        except discord.Forbidden:

            await interaction.response.send_message(

                (

                    "I do not have permission to "

                    "send messages in that channel."

                ),

                ephemeral=True,

            )


            return


        except discord.HTTPException:

            logger.exception(

                "Announcement sending failed."

            )


            await interaction.response.send_message(

                (

                    "Discord rejected the announcement."

                ),

                ephemeral=True,

            )


            return


        self.closed = True


        for child in self.children:

            child.disabled = True


        await interaction.response.edit_message(

            embed=discord.Embed(

                title=(

                    "Announcement Sent"

                ),

                description=(

                    f"The announcement was successfully "

                    f"sent to {channel.mention}."

                ),

                color=discord.Color.green(),

            ),

            view=self,

        )


    @discord.ui.button(

        label="Cancel",

        style=discord.ButtonStyle.danger,

        row=3,

    )
    async def cancel(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Cancel the announcement builder.
        """

        self.closed = True


        for child in self.children:

            child.disabled = True


        await interaction.response.edit_message(

            embed=discord.Embed(

                title=(

                    "Announcement Cancelled"

                ),

                description=(

                    "The announcement was not sent."

                ),

                color=discord.Color.red(),

            ),

            view=self,

        )


class AnnouncementCog(
    commands.Cog
):
    """
    Administrator-only announcement system.
    """


    def __init__(

        self,

        bot: commands.Bot,

    ) -> None:

        self.bot = bot


        logger.info(

            "AnnouncementCog initialized."

        )


    @staticmethod
    def is_administrator(

        interaction: discord.Interaction,

    ) -> bool:

        """

        Check Administrator permission.
        """

        if interaction.guild is None:

            return False


        if not isinstance(

            interaction.user,

            discord.Member,

        ):

            return False


        return (

            interaction.user.guild_permissions.administrator

        )


    @app_commands.command(

        name="announcement",

        description=(

            "Create a professional PAG announcement."

        ),

    )
    async def announcement(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Open the announcement system.
        """

        if not self.is_administrator(

            interaction

        ):

            await interaction.response.send_message(

                (

                    "This command is restricted "

                    "to server administrators."

                ),

                ephemeral=True,

            )


            return


        view = (

            AnnouncementView(

                interaction

            )

        )


        await interaction.response.send_message(

            embed=view.create_panel_embed(),

            view=view,

            ephemeral=True,

        )


async def setup(

    bot: commands.Bot,

) -> None:

    """
    Load the AnnouncementCog.
    """

    await bot.add_cog(

        AnnouncementCog(

            bot

        )

    )