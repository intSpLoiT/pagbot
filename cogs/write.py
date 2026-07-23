"""
PAG Core
Write Cog

Administrator-only message builder.

This system allows administrators to create
professional Discord embeds through an interactive
control panel.

Command:

    /write

The command opens a private message builder.

The administrator can configure:

    - Title
    - Description
    - Color
    - Footer
    - Author
    - Thumbnail
    - Image
    - URL
    - Mention
    - Target channel

The message is not sent immediately.

The administrator first creates the embed,
then previews it,
then manually confirms the send operation.

Architecture:

    /write
        |
        v
    WriteView
        |
        ├── Edit Content
        ├── Edit Appearance
        ├── Edit Images
        ├── Select Channel
        ├── Preview
        ├── Send
        └── Cancel
                |
                v
        Discord Embed
                |
                v
        Target Channel


Security:

    Only users with the Administrator permission
    can use this system.

    The original administrator is the only person
    allowed to control their own builder panel.
"""


from __future__ import annotations


import re


from dataclasses import dataclass


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


class WriteError(
    Exception
):
    """
    Base exception for the Write system.
    """


class InvalidWriteInput(
    WriteError
):
    """
    Raised when an invalid input is provided.
    """


class WriteSessionClosed(
    WriteError
):
    """
    Raised when a closed builder is used.
    """


@dataclass
class WriteData:
    """
    Stores all data used to construct
    the final Discord embed.
    """


    title: str = ""


    description: str = ""


    color: int = 0x5865F2


    footer: str = ""


    author: str = ""


    author_icon: str = ""


    thumbnail: str = ""


    image: str = ""


    url: str = ""


    mention: str = ""


    channel_id: int | None = None


    def create_embed(
        self,
    ) -> discord.Embed:
        """
        Create a Discord Embed from the current data.
        """

        title = (

            self.title.strip()

            if self.title.strip()

            else

            "PAG Message"

        )


        description = (

            self.description.strip()

            if self.description.strip()

            else

            "No description has been provided."

        )


        embed = discord.Embed(

            title=title[:256],

            description=description[:4096],

            color=discord.Color(

                self.color

            ),

        )


        if self.url.strip():

            embed.url = (

                self.url.strip()

            )


        if self.author.strip():

            embed.set_author(

                name=self.author[:256],

                icon_url=(

                    self.author_icon.strip()

                    if self.author_icon.strip()

                    else

                    discord.Embed.Empty

                ),

            )


        if self.thumbnail.strip():

            embed.set_thumbnail(

                url=self.thumbnail.strip()

            )


        if self.image.strip():

            embed.set_image(

                url=self.image.strip()

            )


        if self.footer.strip():

            embed.set_footer(

                text=self.footer[:2048]

            )


        return embed


class WriteContentModal(
    discord.ui.Modal
):
    """
    Modal used to edit the primary content
    of the message.
    """


    def __init__(
        self,

        view: "WriteView",

    ) -> None:

        super().__init__(

            title="Edit Message Content"

        )


        self.write_view = view


        self.title_input = discord.ui.TextInput(

            label="Title",

            placeholder=(

                "Enter the embed title..."

            ),

            default=(

                view.data.title

                if view.data.title

                else

                None

            ),

            max_length=256,

            required=False,

        )


        self.description_input = discord.ui.TextInput(

            label="Description",

            placeholder=(

                "Enter the message content..."

            ),

            default=(

                view.data.description

                if view.data.description

                else

                None

            ),

            style=discord.TextStyle.paragraph,

            max_length=4096,

            required=False,

        )


        self.footer_input = discord.ui.TextInput(

            label="Footer",

            placeholder=(

                "Optional footer text..."

            ),

            default=(

                view.data.footer

                if view.data.footer

                else

                None

            ),

            max_length=2048,

            required=False,

        )


        self.author_input = discord.ui.TextInput(

            label="Author",

            placeholder=(

                "Optional author name..."

            ),

            default=(

                view.data.author

                if view.data.author

                else

                None

            ),

            max_length=256,

            required=False,

        )


        self.add_item(

            self.title_input

        )


        self.add_item(

            self.description_input

        )


        self.add_item(

            self.footer_input

        )


        self.add_item(

            self.author_input

        )


    async def on_submit(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save the content changes.
        """

        self.write_view.data.title = (

            str(

                self.title_input.value

            ).strip()

        )


        self.write_view.data.description = (

            str(

                self.description_input.value

            ).strip()

        )


        self.write_view.data.footer = (

            str(

                self.footer_input.value

            ).strip()

        )


        self.write_view.data.author = (

            str(

                self.author_input.value

            ).strip()

        )


        await interaction.response.send_message(

            (

                "Message content updated."

            ),

            ephemeral=True,

        )


class WriteAppearanceModal(
    discord.ui.Modal
):
    """
    Modal used to configure the embed appearance.
    """


    def __init__(
        self,

        view: "WriteView",

    ) -> None:

        super().__init__(

            title="Edit Appearance"

        )


        self.write_view = view


        self.color_input = discord.ui.TextInput(

            label="Color",

            placeholder=(

                "Example: #5865F2"

            ),

            default=(

                f"#{view.data.color:06X}"

            ),

            max_length=7,

            required=True,

        )


        self.add_item(

            self.color_input

        )


    async def on_submit(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save the appearance changes.
        """

        color_value = (

            str(

                self.color_input.value

            ).strip()

        )


        if color_value.startswith(

            "#"

        ):

            color_value = (

                color_value[1:]

            )


        if not re.fullmatch(

            r"[0-9a-fA-F]{6}",

            color_value,

        ):

            await interaction.response.send_message(

                (

                    "Invalid color.\n\n"

                    "Use the format:\n"

                    "`#5865F2`"

                ),

                ephemeral=True,

            )


            return


        self.write_view.data.color = int(

            color_value,

            16,

        )


        await interaction.response.send_message(

            (

                "Embed appearance updated."

            ),

            ephemeral=True,

        )


class WriteImagesModal(
    discord.ui.Modal
):
    """
    Modal used to configure images and URLs.
    """


    def __init__(
        self,

        view: "WriteView",

    ) -> None:

        super().__init__(

            title="Edit Images and URLs"

        )


        self.write_view = view


        self.thumbnail_input = discord.ui.TextInput(

            label="Thumbnail URL",

            placeholder=(

                "https://example.com/image.png"

            ),

            default=(

                view.data.thumbnail

                if view.data.thumbnail

                else

                None

            ),

            max_length=1000,

            required=False,

        )


        self.image_input = discord.ui.TextInput(

            label="Large Image URL",

            placeholder=(

                "https://example.com/banner.png"

            ),

            default=(

                view.data.image

                if view.data.image

                else

                None

            ),

            max_length=1000,

            required=False,

        )


        self.author_icon_input = discord.ui.TextInput(

            label="Author Icon URL",

            placeholder=(

                "https://example.com/icon.png"

            ),

            default=(

                view.data.author_icon

                if view.data.author_icon

                else

                None

            ),

            max_length=1000,

            required=False,

        )


        self.url_input = discord.ui.TextInput(

            label="Embed Click URL",

            placeholder=(

                "https://example.com"

            ),

            default=(

                view.data.url

                if view.data.url

                else

                None

            ),

            max_length=1000,

            required=False,

        )


        self.add_item(

            self.thumbnail_input

        )


        self.add_item(

            self.image_input

        )


        self.add_item(

            self.author_icon_input

        )


        self.add_item(

            self.url_input

        )


    async def on_submit(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save image and URL configuration.
        """

        self.write_view.data.thumbnail = (

            str(

                self.thumbnail_input.value

            ).strip()

        )


        self.write_view.data.image = (

            str(

                self.image_input.value

            ).strip()

        )


        self.write_view.data.author_icon = (

            str(

                self.author_icon_input.value

            ).strip()

        )


        self.write_view.data.url = (

            str(

                self.url_input.value

            ).strip()

        )


        await interaction.response.send_message(

            (

                "Images and URLs updated."

            ),

            ephemeral=True,

        )


class WriteMentionModal(
    discord.ui.Modal
):
    """
    Modal used to configure optional mentions.
    """


    def __init__(
        self,

        view: "WriteView",

    ) -> None:

        super().__init__(

            title="Edit Mention"

        )


        self.write_view = view


        self.mention_input = discord.ui.TextInput(

            label="Mention",

            placeholder=(

                "Example: @everyone, @here, or leave empty"

            ),

            default=(

                view.data.mention

                if view.data.mention

                else

                None

            ),

            max_length=100,

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

        Save mention configuration.
        """

        mention = (

            str(

                self.mention_input.value

            ).strip()

        )


        allowed_mentions = (

            "@everyone",

            "@here",

        )


        if mention and mention not in allowed_mentions:

            await interaction.response.send_message(

                (

                    "Only the following mentions "

                    "are currently supported:\n\n"

                    "`@everyone`\n"

                    "`@here`"

                ),

                ephemeral=True,

            )


            return


        self.write_view.data.mention = (

            mention

        )


        await interaction.response.send_message(

            (

                "Mention configuration updated."

            ),

            ephemeral=True,

        )


class WriteChannelSelect(
    discord.ui.ChannelSelect
):
    """
    Channel selector for the message builder.
    """


    def __init__(
        self,

        view: "WriteView",

    ) -> None:

        self.write_view = view


        super().__init__(

            placeholder=(

                "Select the target channel..."

            ),

            channel_types=[

                discord.ChannelType.text,

                discord.ChannelType.news,

            ],

            min_values=1,

            max_values=1,

        )


    async def callback(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """

        Save the selected channel.
        """

        selected_channel = (

            self.values[0]

        )


        self.write_view.data.channel_id = (

            selected_channel.id

        )


        await interaction.response.send_message(

            (

                f"Target channel set to "

                f"{selected_channel.mention}."

            ),

            ephemeral=True,

        )


class WriteView(
    discord.ui.View
):
    """
    Main interactive message builder.

    The view is private to the administrator
    who created it.
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


        self.guild_id = (

            interaction.guild.id

            if interaction.guild

            else

            None

        )


        self.data = (

            WriteData()

        )


        self.closed = False


        self.channel_select = (

            WriteChannelSelect(

                self

            )

        )


        self.add_item(

            self.channel_select

        )


    async def interaction_check(

        self,

        interaction: discord.Interaction,

    ) -> bool:

        """

        Ensure only the original administrator
        can control the builder.
        """

        if (

            interaction.user.id

            !=

            self.owner_id

        ):

            await interaction.response.send_message(

                (

                    "This message builder belongs "

                    "to another administrator."

                ),

                ephemeral=True,

            )


            return False


        return True


    async def on_timeout(

        self,

    ) -> None:

        """

        Disable all controls after timeout.
        """

        self.closed = True


        for child in self.children:

            child.disabled = True


        if hasattr(

            self,

            "message",

        ) and self.message:

            try:

                await self.message.edit(

                    view=self

                )

            except discord.HTTPException:

                pass


    def create_panel_embed(

        self,

    ) -> discord.Embed:

        """

        Create the private builder control panel.
        """

        embed = discord.Embed(

            title=(

                "PAG MESSAGE BUILDER"

            ),

            description=(

                "Configure your message using "

                "the controls below.\n\n"

                "The message will not be sent "

                "until you press **Send**."

            ),

            color=discord.Color.dark_grey(),

        )


        target_channel = (

            "Not selected"

        )


        if self.data.channel_id:

            target_channel = (

                f"<#{self.data.channel_id}>"

            )


        embed.add_field(

            name="Content",

            value=(

                f"Title: "

                f"`{self.data.title or 'Not set'}`\n"

                f"Description: "

                f"`{'Configured' if self.data.description else 'Not set'}`"

            ),

            inline=False,

        )


        embed.add_field(

            name="Appearance",

            value=(

                f"Color: "

                f"`#{self.data.color:06X}`\n"

                f"Footer: "

                f"`{self.data.footer or 'Not set'}`"

            ),

            inline=True,

        )


        embed.add_field(

            name="Target",

            value=target_channel,

            inline=True,

        )


        embed.add_field(

            name="Media",

            value=(

                f"Thumbnail: "

                f"`{'Yes' if self.data.thumbnail else 'No'}`\n"

                f"Image: "

                f"`{'Yes' if self.data.image else 'No'}`"

            ),

            inline=True,

        )


        embed.set_footer(

            text=(

                f"{BOT_NAME} • "

                f"Administrator Message Builder • "

                f"v{BOT_VERSION}"

            )

        )


        return embed


    def create_preview_embed(

        self,

    ) -> discord.Embed:

        """

        Create the actual message preview.
        """

        return self.data.create_embed()


    @discord.ui.button(

        label="Content",

        style=discord.ButtonStyle.primary,

        row=1,

    )
    async def content_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the content editor.
        """

        await interaction.response.send_modal(

            WriteContentModal(

                self

            )

        )


    @discord.ui.button(

        label="Appearance",

        style=discord.ButtonStyle.secondary,

        row=1,

    )
    async def appearance_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the appearance editor.
        """

        await interaction.response.send_modal(

            WriteAppearanceModal(

                self

            )

        )


    @discord.ui.button(

        label="Images & URLs",

        style=discord.ButtonStyle.secondary,

        row=1,

    )
    async def images_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the image editor.
        """

        await interaction.response.send_modal(

            WriteImagesModal(

                self

            )

        )


    @discord.ui.button(

        label="Mention",

        style=discord.ButtonStyle.secondary,

        row=2,

    )
    async def mention_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Open the mention editor.
        """

        await interaction.response.send_modal(

            WriteMentionModal(

                self

            )

        )


    @discord.ui.button(

        label="Preview",

        style=discord.ButtonStyle.success,

        row=2,

    )
    async def preview_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Show the final embed preview privately.
        """

        embed = (

            self.create_preview_embed()

        )


        await interaction.response.send_message(

            embed=embed,

            ephemeral=True,

        )


    @discord.ui.button(

        label="Send",

        style=discord.ButtonStyle.success,

        row=3,

    )
    async def send_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Send the final message.
        """

        if self.closed:

            await interaction.response.send_message(

                (

                    "This message builder has expired."

                ),

                ephemeral=True,

            )


            return


        if self.data.channel_id is None:

            await interaction.response.send_message(

                (

                    "You must select a target channel "

                    "before sending."

                ),

                ephemeral=True,

            )


            return


        channel = (

            interaction.guild.get_channel(

                self.data.channel_id

            )

            if interaction.guild

            else

            None

        )


        if channel is None:

            await interaction.response.send_message(

                (

                    "The selected channel could "

                    "not be found."

                ),

                ephemeral=True,

            )


            return


        if not isinstance(

            channel,

            (

                discord.TextChannel,

                discord.NewsChannel,

            ),

        ):

            await interaction.response.send_message(

                (

                    "The selected channel is not "

                    "a supported text channel."

                ),

                ephemeral=True,

            )


            return


        embed = (

            self.create_preview_embed()

        )


        mention = (

            self.data.mention

        )


        try:

            await channel.send(

                content=(

                    mention

                    if mention

                    else

                    None

                ),

                embed=embed,

                allowed_mentions=discord.AllowedMentions(

                    everyone=(

                        mention

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

                    "I do not have permission "

                    "to send messages in that channel."

                ),

                ephemeral=True,

            )


            return


        except discord.HTTPException:

            logger.exception(

                "Discord rejected the Write message."

            )


            await interaction.response.send_message(

                (

                    "Discord rejected the message. "

                    "Check the embed content and URLs."

                ),

                ephemeral=True,

            )


            return


        self.closed = True


        for child in self.children:

            child.disabled = True


        await interaction.response.send_message(

            (

                f"Message successfully sent to "

                f"{channel.mention}."

            ),

            ephemeral=True,

        )


    @discord.ui.button(

        label="Cancel",

        style=discord.ButtonStyle.danger,

        row=3,

    )
    async def cancel_button(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button,

    ) -> None:

        """

        Cancel the message builder.
        """

        self.closed = True


        for child in self.children:

            child.disabled = True


        await interaction.response.edit_message(

            embed=discord.Embed(

                title=(

                    "Message Builder Closed"

                ),

                description=(

                    "The message was cancelled."

                ),

                color=discord.Color.red(),

            ),

            view=self,

        )


class WriteCog(
    commands.Cog
):
    """
    Administrator-only Write system.
    """


    def __init__(

        self,

        bot: commands.Bot,

    ) -> None:

        self.bot = bot


        logger.info(

            "WriteCog initialized."

        )


    @staticmethod
    def is_administrator(

        interaction: discord.Interaction,

    ) -> bool:

        """
        Check whether the user has the
        Administrator permission.
        """

        if interaction.guild is None:

            return False


        member = interaction.user


        if not isinstance(

            member,

            discord.Member,

        ):

            return False


        return (

            member.guild_permissions.administrator

        )


    @app_commands.command(

        name="write",

        description=(

            "Open the administrator message builder."

        ),

    )
    async def write(

        self,

        interaction: discord.Interaction,

    ) -> None:

        """
        Open the Write system.
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

            WriteView(

                interaction

            )

        )


        await interaction.response.send_message(

            embed=view.create_panel_embed(),

            view=view,

            ephemeral=True,

        )


        try:

            view.message = (

                await interaction.original_response()

            )

        except discord.HTTPException:

            logger.exception(

                "Could not retrieve Write panel message."

            )


async def setup(

    bot: commands.Bot,

) -> None:

    """
    Load the WriteCog extension.
    """

    await bot.add_cog(

        WriteCog(

            bot

        )

    )