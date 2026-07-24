from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services.top10_service import (
    InvalidPositionError,
    PlayerAlreadyExistsError,
    PlayerNotFoundError,
    PositionOccupiedError,
    Top10Entry,
    Top10Error,
    Top10Service,
)


# ============================================================
# CONSTANTS
# ============================================================


MIN_POSITION = 1
MAX_POSITION = Top10Service.MAX_ENTRIES

PAG_FALLBACK_AVATAR = (
    "https://tr.rbxcdn.com/"
    "30DAY-AvatarHeadshot-Png"
)


# ============================================================
# EMBED FACTORY
# ============================================================


class Top10Embeds:
    """
    Centralized embed factory for the Top 10 system.

    Keeping embeds in one place makes the Cog easier to extend
    and keeps all responses visually consistent.
    """

    @staticmethod
    def error(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def success(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def warning(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def empty() -> discord.Embed:
        return discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "The PAG Top 10 is currently empty.\n\n"
                "No players have been added yet."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def overview(
        entries: list[Top10Entry],
    ) -> discord.Embed:
        """
        Creates the compact Top 10 overview.

        This is used for:
            /top10
            !top10
            View Rankings button
        """

        if not entries:
            return Top10Embeds.empty()

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        lines: list[str] = []

        for entry in entries:
            prefix = medals.get(
                entry.position,
                f"`#{entry.position}`",
            )

            lines.append(
                (
                    f"{prefix} "
                    f"**{entry.roblox_display_name}**\n"
                    f"└ `{entry.roblox_username}` "
                    f"• `{entry.rank}`"
                )
            )

        embed = discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "The official PAG player ranking.\n\n"
                + "\n\n".join(lines)
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_footer(
            text=(
                f"PAG • {len(entries)}/"
                f"{Top10Service.MAX_ENTRIES} positions filled"
            ),
        )

        return embed

    @staticmethod
    def player(
        entry: Top10Entry,
        *,
        index: int,
        total: int,
    ) -> discord.Embed:
        """
        Creates the detailed player view.

        The avatar is shown as the thumbnail in the
        upper-right corner of the embed.
        """

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        position_icon = medals.get(
            entry.position,
            "🏆",
        )

        embed = discord.Embed(
            title=(
                f"{position_icon} "
                f"#{entry.position} "
                f"{entry.roblox_display_name}"
            ),
            description=(
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"**Roblox Username**\n"
                f"`{entry.roblox_username}`\n\n"
                f"**PAG Rank**\n"
                f"`{entry.rank}`"
            ),
            color=(
                discord.Color.gold()
                if entry.is_first_place
                else discord.Color.blurple()
            ),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🏆 Position",
            value=f"**#{entry.position}**",
            inline=True,
        )

        embed.add_field(
            name="🎖️ Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        embed.add_field(
            name="🆔 Roblox ID",
            value=f"`{entry.roblox_user_id}`",
            inline=True,
        )

        if entry.notes:
            embed.add_field(
                name="📝 Notes",
                value=entry.notes[:1024],
                inline=False,
            )

        if entry.profile_url:
            embed.add_field(
                name="🔗 Profile",
                value=(
                    f"[Open Roblox Profile]"
                    f"({entry.profile_url})"
                ),
                inline=False,
            )

        if entry.avatar_url:
            embed.set_thumbnail(
                url=entry.avatar_url,
            )

        embed.set_footer(
            text=(
                f"PAG Top 10 • "
                f"{index + 1}/{total}"
            ),
        )

        return embed


# ============================================================
# ERROR TRANSLATION
# ============================================================


class Top10ErrorFormatter:
    """
    Converts service exceptions into user-facing messages.

    The service remains independent from Discord.
    """

    @staticmethod
    def message(
        error: Exception,
        *,
        username: str | None = None,
        position: int | None = None,
    ) -> tuple[str, str]:
        if isinstance(
            error,
            InvalidPositionError,
        ):
            return (
                "❌ Invalid Position",
                (
                    "The position must be between "
                    f"**{MIN_POSITION}** and "
                    f"**{MAX_POSITION}**."
                ),
            )

        if isinstance(
            error,
            PlayerAlreadyExistsError,
        ):
            return (
                "❌ Player Already Exists",
                (
                    f"**{username or 'This player'}** "
                    "is already in the PAG Top 10."
                ),
            )

        if isinstance(
            error,
            PositionOccupiedError,
        ):
            return (
                "❌ Position Occupied",
                (
                    f"Position **#{position}** is already "
                    "occupied by another player."
                ),
            )

        if isinstance(
            error,
            PlayerNotFoundError,
        ):
            return (
                "❌ Player Not Found",
                (
                    f"**{username or 'The requested player'}** "
                    "could not be found."
                ),
            )

        if isinstance(
            error,
            Top10Error,
        ):
            return (
                "❌ Top 10 Error",
                (
                    "The Top 10 service could not complete "
                    "this operation."
                ),
            )

        return (
            "❌ Unexpected Error",
            (
                "An unexpected error occurred while "
                "processing the request."
            ),
        )


# ============================================================
# TOP 10 PAGINATION VIEW
# ============================================================


class Top10RankingView(
    discord.ui.View,
):
    """
    Public Top 10 navigation panel.

    The view is intentionally lightweight:
        - entries are loaded once
        - buttons only change the current index
        - no repeated database query for every page
    """

    def __init__(
        self,
        *,
        entries: list[Top10Entry],
        author_id: int | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(
            timeout=timeout,
        )

        self.entries = entries
        self.author_id = author_id
        self.current_index = 0

        self._refresh_buttons()

    def _refresh_buttons(
        self,
    ) -> None:
        """
        Enable or disable navigation buttons
        according to the current page.
        """

        self.previous_button.disabled = (
            self.current_index <= 0
        )

        self.next_button.disabled = (
            self.current_index >= len(
                self.entries,
            ) - 1
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        """
        If author_id is None, the ranking is public.

        If author_id exists, only the command owner
        may use the controls.
        """

        if (
            self.author_id is not None
            and interaction.user.id != self.author_id
        ):
            await interaction.response.send_message(
                (
                    "❌ You cannot control "
                    "this ranking panel."
                ),
                ephemeral=True,
            )

            return False

        return True

    async def _update_page(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self.entries:
            await interaction.response.edit_message(
                embed=Top10Embeds.empty(),
                view=None,
            )

            return

        self._refresh_buttons()

        entry = self.entries[
            self.current_index
        ]

        await interaction.response.edit_message(
            embed=Top10Embeds.player(
                entry,
                index=self.current_index,
                total=len(self.entries),
            ),
            view=self,
        )

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.current_index > 0:
            self.current_index -= 1

        await self._update_page(
            interaction,
        )

    @discord.ui.button(
        label="Overview",
        emoji="📋",
        style=discord.ButtonStyle.primary,
    )
    async def overview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=Top10Embeds.overview(
                self.entries,
            ),
            view=self,
        )

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.current_index < len(
            self.entries,
        ) - 1:
            self.current_index += 1

        await self._update_page(
            interaction,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            view=self,
        )

        self.stop()

    async def on_timeout(
        self,
    ) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# TOP 10 ADD MODAL
# ============================================================


class Top10AddModal(
    discord.ui.Modal,
    title="Add Player to PAG Top 10",
):
    """
    Modal for adding a player.

    The modal only collects data.
    Top10Service remains responsible for:
        - Roblox resolution
        - duplicate prevention
        - position validation
        - database operations
    """

    position = discord.ui.TextInput(
        label="Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Enter the exact Roblox username",
        min_length=1,
        max_length=20,
        required=True,
    )

    rank = discord.ui.TextInput(
        label="PAG Rank",
        placeholder="Example: PT1",
        min_length=1,
        max_length=50,
        required=True,
    )

    notes = discord.ui.TextInput(
        label="Notes",
        placeholder="Optional notes",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        added_by: int,
    ) -> None:
        super().__init__()

        self.service = service
        self.logger = logger
        self.added_by = added_by

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Defer immediately before the service call.

        This is important because add() may resolve
        a Roblox profile before writing to SQLite.
        """

        try:
            position = int(
                self.position.value.strip(),
            )

        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    (
                        "Position must be a number "
                        "between 1 and 10."
                    ),
                ),
                ephemeral=True,
            )

            return

        username = (
            self.username.value.strip()
        )

        rank = (
            self.rank.value.strip()
        )

        notes = (
            self.notes.value.strip()
            or None
        )

        if not username:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Username",
                    (
                        "The Roblox username "
                        "cannot be empty."
                    ),
                ),
                ephemeral=True,
            )

            return

        if not rank:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Rank",
                    (
                        "The PAG rank "
                        "cannot be empty."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = await self.service.add(
                position=position,
                username=username,
                rank=rank,
                added_by=self.added_by,
                notes=notes,
                replace_existing=False,
            )

        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = (
                Top10ErrorFormatter.message(
                    error,
                    username=username,
                    position=position,
                )
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    title,
                    description,
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected error while adding "
                "Top 10 player.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Unexpected Error",
                    (
                        "The player could not be added "
                        "because of an unexpected error."
                    ),
                ),
                ephemeral=True,
            )

            return

        embed = Top10Embeds.success(
            "✅ Player Added",
            (
                f"**{entry.roblox_display_name}** "
                "has been added to the PAG Top 10."
            ),
        )

        embed.add_field(
            name="🏆 Position",
            value=f"**#{entry.position}**",
            inline=True,
        )

        embed.add_field(
            name="🎖️ Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        embed.add_field(
            name="👤 Roblox",
            value=f"`{entry.roblox_username}`",
            inline=True,
        )

        if entry.avatar_url:
            embed.set_thumbnail(
                url=entry.avatar_url,
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# TOP 10 EDIT MODAL
# ============================================================


class Top10EditModal(
    discord.ui.Modal,
    title="Edit PAG Top 10 Player",
):
    """
    Edit an existing Top 10 entry.

    Empty optional fields keep their current values.
    """

    username = discord.ui.TextInput(
        label="New Roblox Username",
        placeholder="Leave empty to keep current username",
        required=False,
        max_length=20,
    )

    rank = discord.ui.TextInput(
        label="New PAG Rank",
        placeholder="Leave empty to keep current rank",
        required=False,
        max_length=50,
    )

    new_position = discord.ui.TextInput(
        label="New Position",
        placeholder="Leave empty to keep current position",
        required=False,
        max_length=2,
    )

    notes = discord.ui.TextInput(
        label="New Notes",
        placeholder=(
            "Leave empty to keep current notes"
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        position: int,
        updated_by: int,
    ) -> None:
        super().__init__()

        self.service = service
        self.logger = logger
        self.position_value = position
        self.updated_by = updated_by

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        username = (
            self.username.value.strip()
            or None
        )

        rank = (
            self.rank.value.strip()
            or None
        )

        notes = (
            self.notes.value.strip()
            or None
        )

        new_position: int | None = None

        if self.new_position.value.strip():
            try:
                new_position = int(
                    self.new_position.value.strip(),
                )

            except ValueError:
                await interaction.response.send_message(
                    embed=Top10Embeds.error(
                        "❌ Invalid Position",
                        (
                            "New position must be "
                            "a number between 1 and 10."
                        ),
                    ),
                    ephemeral=True,
                )

                return

        if (
            username is None
            and rank is None
            and notes is None
            and new_position is None
        ):
            await interaction.response.send_message(
                embed=Top10Embeds.warning(
                    "⚠️ Nothing to Change",
                    (
                        "At least one field must be "
                        "changed before saving."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = await self.service.update(
                position=self.position_value,
                updated_by=self.updated_by,
                username=username,
                rank=rank,
                notes=notes,
                new_position=new_position,
            )

        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = (
                Top10ErrorFormatter.message(
                    error,
                    username=username,
                    position=(
                        new_position
                        or self.position_value
                    ),
                )
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    title,
                    description,
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected error while editing "
                "Top 10 player.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Unexpected Error",
                    (
                        "The player could not be updated."
                    ),
                ),
                ephemeral=True,
            )

            return

        embed = Top10Embeds.success(
            "✅ Player Updated",
            (
                f"**{entry.roblox_display_name}** "
                "has been updated successfully."
            ),
        )

        embed.add_field(
            name="🏆 Position",
            value=f"**#{entry.position}**",
            inline=True,
        )

        embed.add_field(
            name="🎖️ Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        if entry.avatar_url:
            embed.set_thumbnail(
                url=entry.avatar_url,
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# ADMIN MANAGEMENT VIEW
# ============================================================


class Top10ManagementView(
    discord.ui.View,
):
    """
    Administrator-only management panel.

    The panel intentionally does not perform database
    operations directly. Every operation goes through
    Top10Service.
    """

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
        cog: "Top10",
    ) -> None:
        super().__init__(
            timeout=300,
        )

        self.service = service
        self.logger = logger
        self.author_id = author_id
        self.cog = cog

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                (
                    "❌ This management panel belongs "
                    "to another administrator."
                ),
                ephemeral=True,
            )

            return False

        if not (
            isinstance(
                interaction.user,
                discord.Member,
            )
            and interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                (
                    "❌ You no longer have "
                    "Administrator permission."
                ),
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Add Player",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def add_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10AddModal(
                service=self.service,
                logger=self.logger,
                added_by=interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="Edit Player",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def edit_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10EditPositionModal(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="View Rankings",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def view_rankings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entries = (
                await self.service.get_all()
            )

        except Exception:
            self.logger.exception(
                "Failed to load Top 10 rankings.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Failed to Load",
                    (
                        "The Top 10 rankings could "
                        "not be loaded."
                    ),
                ),
                ephemeral=True,
            )

            return

        if not entries:
            await interaction.followup.send(
                embed=Top10Embeds.empty(),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=Top10Embeds.player(
                entries[0],
                index=0,
                total=len(entries),
            ),
            view=Top10RankingView(
                entries=entries,
                author_id=self.author_id,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove Player",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def remove_player(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10RemoveModal(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="Reset",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def reset_top10(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_message(
            embed=Top10Embeds.warning(
                "⚠️ Reset PAG Top 10?",
                (
                    "This will permanently remove "
                    "all Top 10 entries.\n\n"
                    "This action cannot be undone."
                ),
            ),
            view=Top10ResetView(
                service=self.service,
                logger=self.logger,
                author_id=self.author_id,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def close_panel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="🔒 Top 10 management panel closed.",
            embed=None,
            view=self,
        )

        self.stop()

    async def on_timeout(
        self,
    ) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# EDIT POSITION MODAL
# ============================================================


class Top10EditPositionModal(
    discord.ui.Modal,
    title="Select Player to Edit",
):
    position = discord.ui.TextInput(
        label="Current Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__()

        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            position = int(
                self.position.value.strip(),
            )

        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    (
                        "Position must be a number "
                        "between 1 and 10."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = (
                await self.service.get_by_position(
                    position,
                )
            )

        except (
            InvalidPositionError,
            Top10Error,
        ) as error:
            title, description = (
                Top10ErrorFormatter.message(
                    error,
                    position=position,
                )
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    title,
                    description,
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Failed to find Top 10 entry "
                "for editing.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Lookup Failed",
                    (
                        "The selected position "
                        "could not be loaded."
                    ),
                ),
                ephemeral=True,
            )

            return

        if entry is None:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Position Empty",
                    (
                        f"No player exists at "
                        f"position **#{position}**."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=Top10Embeds.player(
                entry,
                index=0,
                total=1,
            ),
            view=Top10EditConfirmView(
                service=self.service,
                logger=self.logger,
                entry=entry,
                author_id=self.author_id,
            ),
            ephemeral=True,
        )


# ============================================================
# EDIT CONFIRM VIEW
# ============================================================


class Top10EditConfirmView(
    discord.ui.View,
):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        entry: Top10Entry,
        author_id: int,
    ) -> None:
        super().__init__(
            timeout=180,
        )

        self.service = service
        self.logger = logger
        self.entry = entry
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This panel belongs to another administrator.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Edit",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            Top10EditModal(
                service=self.service,
                logger=self.logger,
                position=self.entry.position,
                updated_by=interaction.user.id,
            ),
        )

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❎ Edit cancelled.",
            embed=None,
            view=self,
        )

        self.stop()


# ============================================================
# REMOVE MODAL
# ============================================================


class Top10RemoveModal(
    discord.ui.Modal,
    title="Remove PAG Top 10 Player",
):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__()

        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            position = int(
                self.position.value.strip(),
            )

        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    (
                        "Position must be a number "
                        "between 1 and 10."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = await self.service.get_by_position(
                position,
            )

        except (
            InvalidPositionError,
            Top10Error,
        ) as error:
            title, description = (
                Top10ErrorFormatter.message(
                    error,
                    position=position,
                )
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    title,
                    description,
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Failed to load entry before removal.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Lookup Failed",
                    (
                        "The player could not be "
                        "loaded before removal."
                    ),
                ),
                ephemeral=True,
            )

            return

        if entry is None:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Position Empty",
                    (
                        f"No player exists at "
                        f"position **#{position}**."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=Top10Embeds.warning(
                "⚠️ Confirm Removal",
                (
                    f"Remove **{entry.roblox_display_name}** "
                    f"from position **#{position}**?"
                ),
            ),
            view=Top10RemoveConfirmView(
                service=self.service,
                logger=self.logger,
                entry=entry,
                author_id=self.author_id,
            ),
            ephemeral=True,
        )


# ============================================================
# REMOVE CONFIRM VIEW
# ============================================================


class Top10RemoveConfirmView(
    discord.ui.View,
):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        entry: Top10Entry,
        author_id: int,
    ) -> None:
        super().__init__(
            timeout=60,
        )

        self.service = service
        self.logger = logger
        self.entry = entry
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This panel belongs to another administrator.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Remove",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_remove(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            removed = await self.service.remove(
                self.entry.position,
            )

        except (
            InvalidPositionError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = (
                Top10ErrorFormatter.message(
                    error,
                    position=self.entry.position,
                )
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    title,
                    description,
                ),
                ephemeral=True,
            )

            self.stop()

            return

        except Exception:
            self.logger.exception(
                "Unexpected error while removing "
                "Top 10 player.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Remove Failed",
                    (
                        "The player could not be removed."
                    ),
                ),
                ephemeral=True,
            )

            self.stop()

            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Player Removed",
                (
                    f"**{removed.roblox_display_name}** "
                    "has been removed from the PAG Top 10."
                ),
            ),
            ephemeral=True,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_remove(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="❎ Removal cancelled.",
            embed=None,
            view=None,
        )

        self.stop()


# ============================================================
# RESET VIEW
# ============================================================


class Top10ResetView(
    discord.ui.View,
):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__(
            timeout=60,
        )

        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(
        label="Confirm Reset",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            deleted_count = (
                await self.service.clear()
            )

        except Exception:
            self.logger.exception(
                "Failed to reset Top 10.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Reset Failed",
                    (
                        "The Top 10 could not "
                        "be reset."
                    ),
                ),
                ephemeral=True,
            )

            self.stop()

            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Top 10 Reset",
                (
                    f"Successfully removed "
                    f"**{deleted_count}** entries."
                ),
            ),
            ephemeral=True,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="❎ Reset cancelled.",
            embed=None,
            view=None,
        )

        self.stop()


# ============================================================
# TOP 10 COG
# ============================================================


class Top10(
    commands.Cog,
):
    """
    PAG Core
    Top 10 Cog

    Public:
        /top10
        !top10

    Administrator:
        /top10-set
        !top10-set

        /top10-edit
        !top10-edit

        /top10-remove
        !top10-remove

        /top10-reset
        !top10-reset

    All data operations are delegated to:
        services.top10_service.Top10Service
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        top10_service: Top10Service,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.service = top10_service
        self.logger = logger

    # ========================================================
    # SHARED DATA HELPERS
    # ========================================================

    async def _load_entries(
        self,
    ) -> list[Top10Entry]:
        """
        Single source of truth for loading rankings.
        """

        return await self.service.get_all()

    async def _send_ranking(
        self,
        *,
        send: Any,
        entries: list[Top10Entry],
        ephemeral: bool = False,
    ) -> None:
        """
        Shared ranking response.

        The same visual system is used by slash commands,
        prefix commands and management panels.
        """

        if not entries:
            await send(
                embed=Top10Embeds.empty(),
                ephemeral=ephemeral,
            )

            return

        await send(
            embed=Top10Embeds.player(
                entries[0],
                index=0,
                total=len(entries),
            ),
            view=Top10RankingView(
                entries=entries,
            ),
            ephemeral=ephemeral,
        )

    # ========================================================
    # SLASH: /TOP10
    # ========================================================

    @app_commands.command(
        name="top10",
        description="Display the official PAG Top 10.",
    )
    @app_commands.guild_only()
    async def top10(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer()

        try:
            entries = (
                await self._load_entries()
            )

        except Exception:
            self.logger.exception(
                "Failed to load Top 10.",
            )

            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Top 10 Unavailable",
                    (
                        "The PAG Top 10 could not "
                        "be loaded right now."
                    ),
                ),
            )

            return

        if not entries:
            await interaction.followup.send(
                embed=Top10Embeds.empty(),
            )

            return

        await interaction.followup.send(
            embed=Top10Embeds.player(
                entries[0],
                index=0,
                total=len(entries),
            ),
            view=Top10RankingView(
                entries=entries,
            ),
        )

    # ========================================================
    # PREFIX: !TOP10
    # ========================================================

    @commands.command(
        name="top10",
    )
    @commands.guild_only()
    async def top10_prefix(
        self,
        ctx: commands.Context,
    ) -> None:
        try:
            entries = (
                await self._load_entries()
            )

        except Exception:
            self.logger.exception(
                "Failed to load Top 10 via prefix.",
            )

            await ctx.send(
                embed=Top10Embeds.error(
                    "❌ Top 10 Unavailable",
                    (
                        "The PAG Top 10 could not "
                        "be loaded right now."
                    ),
                ),
            )

            return

        if not entries:
            await ctx.send(
                embed=Top10Embeds.empty(),
            )

            return

        await ctx.send(
            embed=Top10Embeds.player(
                entries[0],
                index=0,
                total=len(entries),
            ),
            view=Top10RankingView(
                entries=entries,
            ),
        )

    # ========================================================
    # SLASH: /TOP10-SET
    # ========================================================

    @app_commands.command(
        name="top10-set",
        description="Open the PAG Top 10 management panel.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_set(
        self,
        interaction: discord.Interaction,
    ) -> None:
        embed = discord.Embed(
            title="🏆 PAG TOP 10 MANAGEMENT",
            description=(
                "Manage the official PAG Top 10 "
                "using the controls below.\n\n"
                "➕ **Add Player**\n"
                "Add a Roblox player to a position.\n\n"
                "✏️ **Edit Player**\n"
                "Update an existing entry.\n\n"
                "🗑️ **Remove Player**\n"
                "Remove a player after confirmation.\n\n"
                "⚠️ **Reset**\n"
                "Clear the entire Top 10."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
                cog=self,
            ),
            ephemeral=True,
        )

    # ========================================================
    # PREFIX: !TOP10-SET
    # ========================================================

    @commands.command(
        name="top10-set",
    )
    @commands.guild_only()
    @commands.has_permissions(
        administrator=True,
    )
    async def top10_set_prefix(
        self,
        ctx: commands.Context,
    ) -> None:
        embed = discord.Embed(
            title="🏆 PAG TOP 10 MANAGEMENT",
            description=(
                "Use the buttons below to manage "
                "the PAG Top 10."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        await ctx.send(
            embed=embed,
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
                cog=self,
            ),
        )

    # ========================================================
    # SLASH: /TOP10-RESET
    # ========================================================

    @app_commands.command(
        name="top10-reset",
        description="Reset the entire PAG Top 10.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_reset(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            embed=Top10Embeds.warning(
                "⚠️ Reset PAG Top 10?",
                (
                    "This will remove every player "
                    "from the ranking.\n\n"
                    "This action cannot be undone."
                ),
            ),
            view=Top10ResetView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(
            error,
            app_commands.MissingPermissions,
        ):
            message = (
                "❌ You need **Administrator** "
                "permission to use this command."
            )

        else:
            self.logger.exception(
                "Top 10 slash command error.",
            )

            message = (
                "❌ An unexpected error occurred "
                "while processing this command."
            )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )

        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(
            error,
            commands.MissingPermissions,
        ):
            await ctx.send(
                embed=Top10Embeds.error(
                    "❌ Missing Permissions",
                    (
                        "You need **Administrator** "
                        "permission to use this command."
                    ),
                ),
                delete_after=8,
            )

            return

        if isinstance(
            error,
            commands.CommandNotFound,
        ):
            return

        self.logger.exception(
            "Top 10 prefix command error.",
        )

        await ctx.send(
            embed=Top10Embeds.error(
                "❌ Command Error",
                (
                    "An unexpected error occurred "
                    "while processing the command."
                ),
            ),
            delete_after=8,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Top10(
            bot,
            top10_service=bot.top10_service,
            logger=bot.logger,
        ),
    )