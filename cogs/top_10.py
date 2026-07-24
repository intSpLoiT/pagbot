from __future__ import annotations

import logging
from datetime import datetime

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
# SMALL HELPERS
# ============================================================


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    value = text.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ============================================================
# EMBEDS
# ============================================================


class Top10Embeds:
    """
    All Top 10 embeds are centralized here.

    This keeps the Cog clean and makes styling changes
    easy later.
    """

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def empty() -> discord.Embed:
        return discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "The PAG Top 10 is currently empty.\n\n"
                "No players have been registered yet."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def overview(entries: list[Top10Entry]) -> discord.Embed:
        if not entries:
            return Top10Embeds.empty()

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        lines: list[str] = []

        for entry in entries:
            prefix = medals.get(entry.position, f"`#{entry.position}`")

            rank_text = f"`{entry.rank}`" if entry.rank else "`Unknown`"
            username_text = f"`{entry.roblox_username}`" if entry.roblox_username else "`Unknown`"

            lines.append(
                (
                    f"{prefix} **{entry.roblox_display_name}**\n"
                    f"└ {username_text} • {rank_text}"
                )
            )

        embed = discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "Official ranking overview.\n\n"
                + "\n\n".join(lines)
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_footer(
            text=f"PAG • {len(entries)}/10 positions filled",
        )
        return embed

    @staticmethod
    def player(entry: Top10Entry, *, page_index: int, total_pages: int) -> discord.Embed:
        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        icon = medals.get(entry.position, "🏆")
        profile_url = entry.profile_url or None

        embed = discord.Embed(
            title=f"{icon} #{entry.position} {entry.roblox_display_name}",
            url=profile_url,
            description=(
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"**Roblox Username**\n"
                f"`{entry.roblox_username}`\n\n"
                f"**PAG Rank**\n"
                f"`{entry.rank}`"
            ),
            color=discord.Color.gold() if entry.is_first_place else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🏆 Position",
            value=f"**#{entry.position}**",
            inline=True,
        )

        embed.add_field(
            name="👤 Roblox ID",
            value=f"`{entry.roblox_user_id}`",
            inline=True,
        )

        embed.add_field(
            name="🎖️ Rank",
            value=f"`{entry.rank}`",
            inline=True,
        )

        if entry.notes:
            embed.add_field(
                name="📝 Notes",
                value=_truncate(entry.notes, 1024) or "Unknown",
                inline=False,
            )

        embed.add_field(
            name="➕ Added By",
            value=f"<@{entry.added_by}>",
            inline=True,
        )

        embed.add_field(
            name="✏️ Updated By",
            value=f"<@{entry.updated_by}>",
            inline=True,
        )

        created_dt = _parse_iso_dt(entry.created_at)
        updated_dt = _parse_iso_dt(entry.updated_at)

        if created_dt is not None:
            embed.add_field(
                name="📅 Created",
                value=discord.utils.format_dt(created_dt, style="R"),
                inline=True,
            )

        if updated_dt is not None:
            embed.add_field(
                name="🕒 Updated",
                value=discord.utils.format_dt(updated_dt, style="R"),
                inline=True,
            )

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        if entry.profile_url:
            embed.set_footer(
                text=f"PAG Top 10 • Page {page_index + 1}/{total_pages}",
            )
        else:
            embed.set_footer(
                text=f"PAG Top 10 • Page {page_index + 1}/{total_pages}",
            )

        return embed

    @staticmethod
    def management(count: int, is_full: bool) -> discord.Embed:
        status_text = "Full" if is_full else "Open"

        embed = discord.Embed(
            title="🏆 PAG TOP 10 MANAGEMENT",
            description=(
                "Manage the ranking system using the controls below.\n\n"
                "➕ **Add / Replace**\n"
                "Add a player to a position.\n\n"
                "✏️ **Edit**\n"
                "Update an existing player.\n\n"
                "🗑️ **Remove**\n"
                "Remove a player after confirmation.\n\n"
                "⚠️ **Reset**\n"
                "Clear the entire ranking.\n\n"
                "📊 **View Rankings**\n"
                "Show the current Top 10."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="📈 Current Entries",
            value=f"`{count}/10`",
            inline=True,
        )

        embed.add_field(
            name="📌 Status",
            value=f"`{status_text}`",
            inline=True,
        )

        embed.set_footer(
            text="PAG • Admin tools",
        )
        return embed


# ============================================================
# ERROR MAPPING
# ============================================================


class Top10ErrorMapper:
    @staticmethod
    def map(error: Exception, *, position: int | None = None, username: str | None = None) -> tuple[str, str]:
        if isinstance(error, InvalidPositionError):
            return (
                "❌ Invalid Position",
                "Position must be between **1** and **10**.",
            )

        if isinstance(error, PlayerAlreadyExistsError):
            return (
                "❌ Player Already Exists",
                f"**{username or 'This player'}** is already in the Top 10.",
            )

        if isinstance(error, PositionOccupiedError):
            if position is None:
                return (
                    "❌ Position Occupied",
                    "That position is already occupied.",
                )
            return (
                "❌ Position Occupied",
                f"Position **#{position}** is already occupied.",
            )

        if isinstance(error, PlayerNotFoundError):
            if position is None:
                return (
                    "❌ Player Not Found",
                    f"**{username or 'The requested player'}** could not be found.",
                )
            return (
                "❌ Player Not Found",
                f"No player exists at position **#{position}**.",
            )

        if isinstance(error, Top10Error):
            return (
                "❌ Top 10 Error",
                "The Top 10 service could not complete this operation.",
            )

        return (
            "❌ Unexpected Error",
            "An unexpected error occurred while processing the request.",
        )


# ============================================================
# RANKING VIEW
# ============================================================


class Top10RankingView(discord.ui.View):
    """
    Lightweight page view for the public Top 10 display.

    It loads entries once and navigates locally.
    A refresh button is available if the service is provided.
    """

    def __init__(
        self,
        *,
        entries: list[Top10Entry],
        service: Top10Service | None = None,
        author_id: int | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.entries = entries
        self.service = service
        self.author_id = author_id
        self.current_index = 0
        self.show_overview = False
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_entries = bool(self.entries)

        self.previous_button.disabled = (
            not has_entries
            or self.show_overview
            or self.current_index <= 0
        )
        self.next_button.disabled = (
            not has_entries
            or self.show_overview
            or self.current_index >= len(self.entries) - 1
        )
        self.overview_button.disabled = not has_entries
        self.refresh_button.disabled = self.service is None or not has_entries

    def _current_embed(self) -> discord.Embed:
        if not self.entries:
            return Top10Embeds.empty()

        if self.show_overview:
            return Top10Embeds.overview(self.entries)

        current = self.entries[self.current_index]
        return Top10Embeds.player(
            current,
            page_index=self.current_index,
            total_pages=len(self.entries),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ You cannot control this ranking panel.",
                ephemeral=True,
            )
            return False
        return True

    async def _edit_current(self, interaction: discord.Interaction) -> None:
        if not self.entries:
            await interaction.response.edit_message(
                embed=Top10Embeds.empty(),
                view=None,
            )
            return

        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self._current_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = False
        if self.current_index > 0:
            self.current_index -= 1
        await self._edit_current(interaction)

    @discord.ui.button(
        label="Overview",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def overview_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = not self.show_overview
        await self._edit_current(interaction)

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.show_overview = False
        if self.current_index < len(self.entries) - 1:
            self.current_index += 1
        await self._edit_current(interaction)

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.service is None:
            await interaction.response.send_message(
                "❌ Refresh is unavailable.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            self.entries = await self.service.get_all()
        except Exception:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Refresh Failed",
                    "The latest ranking could not be loaded.",
                ),
                ephemeral=True,
            )
            return

        if not self.entries:
            await interaction.followup.send(
                embed=Top10Embeds.empty(),
                ephemeral=True,
            )
            await interaction.message.edit(view=None)
            return

        if self.current_index >= len(self.entries):
            self.current_index = len(self.entries) - 1

        self._sync_buttons()
        await interaction.followup.send(
            embed=self._current_embed(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=None)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# MANAGEMENT PANEL VIEW
# ============================================================


class Top10ManagementView(discord.ui.View):
    """
    Private admin panel for Top 10 operations.

    It is locked to the command author and requires
    Administrator permission on interaction.
    """

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This management panel belongs to another administrator.",
                ephemeral=True,
            )
            return False

        if not (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "❌ You need Administrator permission to use this panel.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Add / Replace",
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
                replace_existing=True,
            )
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
            Top10EditModal(
                service=self.service,
                logger=self.logger,
                updated_by=interaction.user.id,
            )
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
            )
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
        await interaction.response.defer(ephemeral=True)

        try:
            entries = await self.service.get_all()
        except Exception:
            self.logger.exception("Failed to load Top 10 rankings.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Failed to Load",
                    "The ranking list could not be loaded.",
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
                page_index=0,
                total_pages=len(entries),
            ),
            view=Top10RankingView(
                entries=entries,
                service=self.service,
                author_id=self.author_id,
            ),
            ephemeral=True,
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
                "⚠️ Reset Top 10?",
                (
                    "This will remove every player from the ranking.\n\n"
                    "This action cannot be undone."
                ),
            ),
            view=Top10ResetConfirmView(
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

        await interaction.response.edit_message(view=None)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ============================================================
# ADD MODAL
# ============================================================


class Top10AddModal(discord.ui.Modal, title="Add / Replace PAG Top 10 Player"):
    position = discord.ui.TextInput(
        label="Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

    username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Exact Roblox username",
        min_length=1,
        max_length=20,
        required=True,
    )

    rank = discord.ui.TextInput(
        label="PAG Rank",
        placeholder="PT1, ET2, LT, etc.",
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
        replace_existing: bool = True,
    ) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self.added_by = added_by
        self.replace_existing = replace_existing

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    "Position must be a number between **1** and **10**.",
                ),
                ephemeral=True,
            )
            return

        username = self.username.value.strip()
        rank = self.rank.value.strip()
        notes = self.notes.value.strip() or None

        if not username:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Username",
                    "Roblox username cannot be empty.",
                ),
                ephemeral=True,
            )
            return

        if not rank:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Rank",
                    "PAG rank cannot be empty.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.add(
                position=position,
                username=username,
                rank=rank,
                added_by=self.added_by,
                notes=notes,
                replace_existing=self.replace_existing,
            )
        except (
            InvalidPositionError,
            PlayerAlreadyExistsError,
            PositionOccupiedError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(
                error,
                position=position,
                username=username,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except sqlite3.IntegrityError:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Database Conflict",
                    "A database constraint prevented this player from being added.",
                ),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Unexpected error while adding Top 10 player.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Unexpected Error",
                    "The player could not be added.",
                ),
                ephemeral=True,
            )
            return

        embed = Top10Embeds.success(
            "✅ Player Added",
            f"**{entry.roblox_display_name}** has been placed at **#{entry.position}**.",
        )
        embed.add_field(name="Roblox", value=f"`{entry.roblox_username}`", inline=True)
        embed.add_field(name="Rank", value=f"`{entry.rank}`", inline=True)
        embed.add_field(name="User ID", value=f"`{entry.roblox_user_id}`", inline=True)

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# EDIT MODAL
# ============================================================


class Top10EditModal(discord.ui.Modal, title="Edit PAG Top 10 Player"):
    position = discord.ui.TextInput(
        label="Current Position",
        placeholder="1 - 10",
        min_length=1,
        max_length=2,
        required=True,
    )

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
        placeholder="Leave empty to keep current notes",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        updated_by: int,
    ) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self.updated_by = updated_by

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    "Current position must be a number between **1** and **10**.",
                ),
                ephemeral=True,
            )
            return

        username = self.username.value.strip() or None
        rank = self.rank.value.strip() or None
        notes = self.notes.value.strip() or None

        new_position: int | None = None
        if self.new_position.value.strip():
            try:
                new_position = int(self.new_position.value.strip())
            except ValueError:
                await interaction.response.send_message(
                    embed=Top10Embeds.error(
                        "❌ Invalid Position",
                        "New position must be a number between **1** and **10**.",
                    ),
                    ephemeral=True,
                )
                return

        if username is None and rank is None and notes is None and new_position is None:
            await interaction.response.send_message(
                embed=Top10Embeds.warning(
                    "⚠️ Nothing to Update",
                    "At least one field must be changed before saving.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.update(
                position=position,
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
            title, description = Top10ErrorMapper.map(
                error,
                position=new_position or position,
                username=username,
            )
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except sqlite3.IntegrityError:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Database Conflict",
                    "A database constraint prevented this player from being updated.",
                ),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Unexpected error while editing Top 10 player.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Unexpected Error",
                    "The player could not be updated.",
                ),
                ephemeral=True,
            )
            return

        embed = Top10Embeds.success(
            "✅ Player Updated",
            f"**{entry.roblox_display_name}** has been updated successfully.",
        )
        embed.add_field(name="Position", value=f"**#{entry.position}**", inline=True)
        embed.add_field(name="Roblox", value=f"`{entry.roblox_username}`", inline=True)
        embed.add_field(name="Rank", value=f"`{entry.rank}`", inline=True)

        if entry.avatar_url:
            embed.set_thumbnail(url=entry.avatar_url)

        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# REMOVE MODAL + CONFIRM VIEW
# ============================================================


class Top10RemoveConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        entry: Top10Entry,
        author_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.logger = logger
        self.entry = entry
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This confirmation panel belongs to another administrator.",
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

        await interaction.response.defer(ephemeral=True)

        try:
            removed = await self.service.remove(self.entry.position)
        except (
            InvalidPositionError,
            PlayerNotFoundError,
            Top10Error,
        ) as error:
            title, description = Top10ErrorMapper.map(error, position=self.entry.position)
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            self.stop()
            return
        except Exception:
            self.logger.exception("Unexpected error while removing Top 10 player.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Remove Failed",
                    "The player could not be removed.",
                ),
                ephemeral=True,
            )
            self.stop()
            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Player Removed",
                f"**{removed.roblox_display_name}** has been removed from **#{removed.position}**.",
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
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❎ Removal cancelled.",
            embed=None,
            view=None,
        )
        self.stop()


class Top10RemoveModal(discord.ui.Modal, title="Remove PAG Top 10 Player"):
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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            position = int(self.position.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=Top10Embeds.error(
                    "❌ Invalid Position",
                    "Position must be a number between **1** and **10**.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            entry = await self.service.get_by_position(position)
        except (InvalidPositionError, Top10Error) as error:
            title, description = Top10ErrorMapper.map(error, position=position)
            await interaction.followup.send(
                embed=Top10Embeds.error(title, description),
                ephemeral=True,
            )
            return
        except Exception:
            self.logger.exception("Failed to load player before removal.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Lookup Failed",
                    "The selected player could not be loaded.",
                ),
                ephemeral=True,
            )
            return

        if entry is None:
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Position Empty",
                    f"No player exists at position **#{position}**.",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=Top10Embeds.warning(
                "⚠️ Confirm Removal",
                f"Remove **{entry.roblox_display_name}** from **#{entry.position}**?",
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
# RESET CONFIRM VIEW
# ============================================================


class Top10ResetConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        service: Top10Service,
        logger: logging.Logger,
        author_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.logger = logger
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This confirmation panel belongs to another administrator.",
                ephemeral=True,
            )
            return False
        return True

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

        await interaction.response.defer(ephemeral=True)

        try:
            deleted_count = await self.service.clear()
        except Exception:
            self.logger.exception("Failed to reset Top 10.")
            await interaction.followup.send(
                embed=Top10Embeds.error(
                    "❌ Reset Failed",
                    "The Top 10 could not be reset.",
                ),
                ephemeral=True,
            )
            self.stop()
            return

        await interaction.followup.send(
            embed=Top10Embeds.success(
                "✅ Top 10 Reset",
                f"Successfully removed **{deleted_count}** entries.",
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
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❎ Reset cancelled.",
            embed=None,
            view=None,
        )
        self.stop()


# ============================================================
# MAIN COG
# ============================================================


class Top10(commands.Cog):
    """
    PAG Core
    Top 10 Cog

    Slash:
        /top10
        /top10-set
        /top10-edit
        /top10-remove
        /top10-reset

    Prefix:
        !top10
        !top10-set
        !top10-edit
        !top10-remove
        !top10-reset

    Data work is delegated to Top10Service.
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

    async def _load_entries(self) -> list[Top10Entry]:
        return await self.service.get_all()

    async def _management_embed(self) -> discord.Embed:
        count = await self.service.count()
        is_full = await self.service.is_full()
        return Top10Embeds.management(count, is_full)

    async def _send_ranking(
        self,
        *,
        destination: discord.Interaction | commands.Context,
        ephemeral: bool = False,
    ) -> None:
        try:
            entries = await self._load_entries()
        except Exception:
            self.logger.exception("Failed to load Top 10.")
            error_embed = Top10Embeds.error(
                "❌ Top 10 Unavailable",
                "The PAG Top 10 could not be loaded right now.",
            )
            if isinstance(destination, discord.Interaction):
                if destination.response.is_done():
                    await destination.followup.send(embed=error_embed, ephemeral=ephemeral)
                else:
                    await destination.response.send_message(embed=error_embed, ephemeral=ephemeral)
            else:
                await destination.send(embed=error_embed)
            return

        if not entries:
            empty_embed = Top10Embeds.empty()
            if isinstance(destination, discord.Interaction):
                if destination.response.is_done():
                    await destination.followup.send(embed=empty_embed, ephemeral=ephemeral)
                else:
                    await destination.response.send_message(embed=empty_embed, ephemeral=ephemeral)
            else:
                await destination.send(embed=empty_embed)
            return

        view = Top10RankingView(
            entries=entries,
            service=self.service,
            author_id=destination.user.id if isinstance(destination, discord.Interaction) else None,
        )
        first_embed = Top10Embeds.player(entries[0], page_index=0, total_pages=len(entries))

        if isinstance(destination, discord.Interaction):
            if destination.response.is_done():
                await destination.followup.send(embed=first_embed, view=view, ephemeral=ephemeral)
            else:
                await destination.response.send_message(embed=first_embed, view=view, ephemeral=ephemeral)
        else:
            await destination.send(embed=first_embed, view=view)

    # ========================================================
    # /TOP10
    # ========================================================

    @app_commands.command(
        name="top10",
        description="Display the official PAG Top 10.",
    )
    @app_commands.guild_only()
    async def top10_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._send_ranking(destination=interaction)

    @commands.command(name="top10")
    @commands.guild_only()
    async def top10_prefix(self, ctx: commands.Context) -> None:
        await self._send_ranking(destination=ctx)

    # ========================================================
    # /TOP10-SET
    # ========================================================

    @app_commands.command(
        name="top10-set",
        description="Open the PAG Top 10 management panel.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_set_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=await self._management_embed(),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @commands.command(name="top10-set")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_set_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=await self._management_embed(),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
            ),
        )

    # ========================================================
    # /TOP10-EDIT
    # ========================================================

    @app_commands.command(
        name="top10-edit",
        description="Edit an existing Top 10 player.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_edit_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            Top10EditModal(
                service=self.service,
                logger=self.logger,
                updated_by=interaction.user.id,
            )
        )

    @commands.command(name="top10-edit")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_edit_prefix(self, ctx: commands.Context) -> None:
        # Prefix cannot open a modal directly, so it opens the same
        # admin panel used for all management actions.
        await ctx.send(
            embed=await self._management_embed(),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
            ),
        )

    # ========================================================
    # /TOP10-REMOVE
    # ========================================================

    @app_commands.command(
        name="top10-remove",
        description="Remove a Top 10 player.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_remove_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            Top10RemoveModal(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            )
        )

    @commands.command(name="top10-remove")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_remove_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=await self._management_embed(),
            view=Top10ManagementView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
            ),
        )

    # ========================================================
    # /TOP10-RESET
    # ========================================================

    @app_commands.command(
        name="top10-reset",
        description="Reset the entire Top 10.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def top10_reset_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=Top10Embeds.warning(
                "⚠️ Reset PAG Top 10?",
                "This will remove every player from the ranking.\n\nThis action cannot be undone.",
            ),
            view=Top10ResetConfirmView(
                service=self.service,
                logger=self.logger,
                author_id=interaction.user.id,
            ),
            ephemeral=True,
        )

    @commands.command(name="top10-reset")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def top10_reset_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(
            embed=Top10Embeds.warning(
                "⚠️ Reset PAG Top 10?",
                "This will remove every player from the ranking.\n\nThis action cannot be undone.",
            ),
            view=Top10ResetConfirmView(
                service=self.service,
                logger=self.logger,
                author_id=ctx.author.id,
            ),
        )

    # ========================================================
    # ERROR HANDLERS
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ You need **Administrator** permission to use this command."
        else:
            self.logger.exception("Top 10 slash command error.")
            message = "❌ An unexpected error occurred while processing this command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=Top10Embeds.error(
                    "❌ Missing Permissions",
                    "You need **Administrator** permission to use this command.",
                ),
                delete_after=8,
            )
            return

        if isinstance(error, commands.CommandNotFound):
            return

        self.logger.exception("Top 10 prefix command error.")
        await ctx.send(
            embed=Top10Embeds.error(
                "❌ Command Error",
                "An unexpected error occurred while processing the command.",
            ),
            delete_after=8,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(bot: commands.Bot) -> None:
    top10_service = Top10Service(
        database_path=bot.config.database_path,
        roblox_service=bot.roblox_service,
    )

    await bot.add_cog(
        Top10(
            bot,
            top10_service=top10_service,
            logger=bot.logger,
        ),
    )