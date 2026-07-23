"""
PAG Core
System Commands

This module contains basic system commands used to monitor
the current state of the PAG Core bot.

Commands:

    /ping
        Check the current Discord latency.

    /status
        Display the current PAG Core status.

    /uptime
        Display the current bot uptime.
"""


from __future__ import annotations


import discord

from discord import app_commands

from discord.ext import commands


from config.constants import (
    BOT_NAME,
    BOT_VERSION,
)


class SystemCog(commands.Cog):
    """
    Core system commands for PAG Core.

    This Cog is responsible for basic health and status
    information.

    It does not contain business logic for:

    - Roblox
    - Ranks
    - Events
    - Achievements
    - Leaderboards
    """


    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot


    @app_commands.command(
        name="ping",
        description=(
            "Check the current PAG Core latency."
        ),
    )
    async def ping(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Display the current Discord latency.
        """

        latency = self.bot.latency * 1000


        embed = discord.Embed(
            title="PAG Core",
            description=(
                "The bot is currently connected "
                "and responding."
            ),
            color=discord.Color.green(),
        )


        embed.add_field(
            name="Status",
            value="ONLINE",
            inline=True,
        )


        embed.add_field(
            name="Latency",
            value=f"{latency:.2f} ms",
            inline=True,
        )


        embed.set_footer(
            text=(
                f"{BOT_NAME} • "
                f"v{BOT_VERSION}"
            ),
        )


        await interaction.response.send_message(
            embed=embed,
        )


    @app_commands.command(
        name="status",
        description=(
            "Display the current PAG Core status."
        ),
    )
    async def status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Display detailed bot status information.
        """

        if hasattr(
            self.bot,
            "get_status_data",
        ):

            status_data = (
                self.bot.get_status_data()
            )

        else:

            status_data = {

                "online": True,

                "guilds": len(
                    self.bot.guilds
                ),

                "latency_ms": round(
                    self.bot.latency * 1000,
                    2,
                ),

            }


        online = status_data.get(
            "online",
            False,
        )


        status_text = (
            "ONLINE"
            if online
            else
            "OFFLINE"
        )


        embed = discord.Embed(
            title="PAG Core Status",
            color=(
                discord.Color.green()
                if online
                else
                discord.Color.red()
            ),
        )


        embed.add_field(
            name="Status",
            value=status_text,
            inline=True,
        )


        embed.add_field(
            name="Latency",
            value=(
                f"{status_data.get(
                    'latency_ms',
                    0,
                )} ms"
            ),
            inline=True,
        )


        embed.add_field(
            name="Guilds",
            value=str(
                status_data.get(
                    "guilds",
                    0,
                )
            ),
            inline=True,
        )


        embed.add_field(
            name="Uptime",
            value=str(
                status_data.get(
                    "uptime",
                    "Unknown",
                )
            ),
            inline=True,
        )


        embed.add_field(
            name="Database",
            value=(
                "CONNECTED"
                if getattr(
                    self.bot.database,
                    "is_connected",
                    False,
                )
                else
                "DISCONNECTED"
            ),
            inline=True,
        )


        embed.add_field(
            name="Version",
            value=BOT_VERSION,
            inline=True,
        )


        embed.set_footer(
            text=BOT_NAME,
        )


        await interaction.response.send_message(
            embed=embed,
        )


    @app_commands.command(
        name="uptime",
        description=(
            "Display how long PAG Core has been online."
        ),
    )
    async def uptime(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Display the current bot uptime.
        """

        if hasattr(
            self.bot,
            "get_uptime_formatted",
        ):

            uptime = (
                self.bot.get_uptime_formatted()
            )

        else:

            uptime = "Unknown"


        embed = discord.Embed(
            title="PAG Core Uptime",
            description=(
                f"PAG Core has been online for:\n\n"
                f"**{uptime}**"
            ),
            color=discord.Color.blurple(),
        )


        await interaction.response.send_message(
            embed=embed,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Load the SystemCog extension.
    """

    await bot.add_cog(
        SystemCog(bot)
    )