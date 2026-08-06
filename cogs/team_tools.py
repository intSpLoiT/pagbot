from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ==========================================================
# Optional package bootstrap
# ==========================================================

def _ensure_package(module_name: str, pip_name: str | None = None) -> None:
    try:
        importlib.import_module(module_name)
    except Exception:
        pkg = pip_name or module_name
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        except Exception:
            # Import sırasında gerçek hatayı görmemek için sessiz geçiyoruz.
            pass


_ensure_package("discord", "discord.py")

import discord
from discord import app_commands
from discord.ext import commands

# ==========================================================
# Paths / constants
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "team_tools.sqlite3"

LOGGER = logging.getLogger("PAG.TeamTools")

PANEL_KEYS = ("train", "tryout", "spar", "teamer_help")

# ==========================================================
# Small helpers
# ==========================================================


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_text(value: str, limit: int = 1024) -> str:
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 3] + "..."


def split_pipe(text: str, expected: int, defaults: tuple[str, ...]) -> list[str]:
    parts = [part.strip() for part in (text or "").split("|")]
    while len(parts) < expected:
        idx = len(parts)
        parts.append(defaults[idx] if idx < len(defaults) else "")
    return parts[:expected]


def human_bool(v: bool) -> str:
    return "Evet" if v else "Hayır"


def role_mention(guild: discord.Guild, role_id: Optional[int]) -> str:
    if not role_id:
        return "Ayar yok"
    role = guild.get_role(role_id)
    return role.mention if role else f"`{role_id}`"


def resolve_role(guild: discord.Guild, value: str) -> Optional[discord.Role]:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("<@&") and raw.endswith(">"):
        raw = raw[3:-1]
    if raw.isdigit():
        return guild.get_role(int(raw))
    lowered = raw.lower()
    for role in guild.roles:
        if role.name.lower() == lowered:
            return role
    for role in guild.roles:
        if lowered in role.name.lower():
            return role
    return None


def is_manage_privileged(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild


# ==========================================================
# Database
# ==========================================================


class TeamToolsDB:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS panel_settings (
                    guild_id INTEGER PRIMARY KEY,
                    train_role_id INTEGER,
                    tryout_role_id INTEGER,
                    spar_role_id INTEGER,
                    teamer_help_role_id INTEGER,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spar_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    requester_id INTEGER NOT NULL,
                    opponent_name TEXT NOT NULL,
                    date_text TEXT NOT NULL,
                    time_text TEXT NOT NULL,
                    format_text TEXT NOT NULL,
                    note_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    accepted_by INTEGER,
                    message_id INTEGER,
                    channel_id INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS train_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    time_text TEXT NOT NULL,
                    note_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    message_id INTEGER,
                    channel_id INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS train_attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(event_id, user_id),
                    FOREIGN KEY(event_id) REFERENCES train_events(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def _execute_sync(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _fetchone_sync(self, sql: str, params: tuple[Any, ...]) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchone()

    def _fetchall_sync(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        await self._run(self._execute_sync, sql, params)

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        return await self._run(self._fetchone_sync, sql, params)

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return await self._run(self._fetchall_sync, sql, params)

    async def add_audit(self, guild_id: int, actor_id: int, action: str, details: str) -> None:
        await self.execute(
            "INSERT INTO audit_log (guild_id, actor_id, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, actor_id, action, details, utc_now()),
        )

    async def get_panel(self, guild_id: int) -> dict[str, Optional[int]]:
        row = await self.fetchone("SELECT * FROM panel_settings WHERE guild_id=?", (guild_id,))
        if not row:
            return {key: None for key in PANEL_KEYS}
        return {
            "train": row["train_role_id"],
            "tryout": row["tryout_role_id"],
            "spar": row["spar_role_id"],
            "teamer_help": row["teamer_help_role_id"],
        }

    async def upsert_panel(self, guild_id: int, values: dict[str, Optional[int]]) -> None:
        await self.execute(
            """
            INSERT INTO panel_settings (
                guild_id, train_role_id, tryout_role_id, spar_role_id, teamer_help_role_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                train_role_id=excluded.train_role_id,
                tryout_role_id=excluded.tryout_role_id,
                spar_role_id=excluded.spar_role_id,
                teamer_help_role_id=excluded.teamer_help_role_id,
                updated_at=excluded.updated_at
            """,
            (
                guild_id,
                values.get("train"),
                values.get("tryout"),
                values.get("spar"),
                values.get("teamer_help"),
                utc_now(),
            ),
        )

    async def create_spar_request(
        self,
        guild_id: int,
        requester_id: int,
        opponent_name: str,
        date_text: str,
        time_text: str,
        format_text: str,
        note_text: str,
    ) -> int:
        def _sync() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO spar_requests (
                        guild_id, requester_id, opponent_name, date_text, time_text,
                        format_text, note_text, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        guild_id,
                        requester_id,
                        opponent_name,
                        date_text,
                        time_text,
                        format_text,
                        note_text,
                        utc_now(),
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)

        return await self._run(_sync)

    async def get_spar_request(self, request_id: int) -> Optional[dict[str, Any]]:
        row = await self.fetchone("SELECT * FROM spar_requests WHERE id=?", (request_id,))
        return dict(row) if row else None

    async def list_open_spars(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT * FROM spar_requests WHERE guild_id=? AND status='open' ORDER BY id DESC",
            (guild_id,),
        )
        return [dict(r) for r in rows]

    async def set_spar_meta(self, request_id: int, message_id: int, channel_id: int) -> None:
        await self.execute(
            "UPDATE spar_requests SET message_id=?, channel_id=? WHERE id=?",
            (message_id, channel_id, request_id),
        )

    async def set_spar_status(self, request_id: int, status: str, accepted_by: Optional[int] = None) -> None:
        await self.execute(
            "UPDATE spar_requests SET status=?, accepted_by=? WHERE id=?",
            (status, accepted_by, request_id),
        )

    async def cancel_spar(self, request_id: int) -> None:
        await self.execute("UPDATE spar_requests SET status='cancelled' WHERE id=?", (request_id,))

    async def create_train_event(
        self,
        guild_id: int,
        host_id: int,
        topic: str,
        time_text: str,
        note_text: str,
    ) -> int:
        def _sync() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO train_events (
                        guild_id, host_id, topic, time_text, note_text, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (guild_id, host_id, topic, time_text, note_text, utc_now()),
                )
                conn.commit()
                return int(cur.lastrowid)

        return await self._run(_sync)

    async def set_train_meta(self, event_id: int, message_id: int, channel_id: int) -> None:
        await self.execute(
            "UPDATE train_events SET message_id=?, channel_id=? WHERE id=?",
            (message_id, channel_id, event_id),
        )

    async def get_train_event(self, event_id: int) -> Optional[dict[str, Any]]:
        row = await self.fetchone("SELECT * FROM train_events WHERE id=?", (event_id,))
        return dict(row) if row else None

    async def set_train_status(self, event_id: int, status: str) -> None:
        await self.execute("UPDATE train_events SET status=? WHERE id=?", (status, event_id))

    async def set_train_attendance(self, event_id: int, guild_id: int, user_id: int, status: str) -> None:
        await self.execute(
            """
            INSERT INTO train_attendance (event_id, guild_id, user_id, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id, user_id) DO UPDATE SET
                status=excluded.status,
                created_at=excluded.created_at
            """,
            (event_id, guild_id, user_id, status, utc_now()),
        )

    async def get_train_counts(self, event_id: int) -> tuple[int, int]:
        yes = await self.fetchone(
            "SELECT COUNT(*) AS c FROM train_attendance WHERE event_id=? AND status='yes'",
            (event_id,),
        )
        no = await self.fetchone(
            "SELECT COUNT(*) AS c FROM train_attendance WHERE event_id=? AND status='no'",
            (event_id,),
        )
        return int(yes["c"] if yes else 0), int(no["c"] if no else 0)

    async def get_user_train_status(self, event_id: int, user_id: int) -> Optional[str]:
        row = await self.fetchone(
            "SELECT status FROM train_attendance WHERE event_id=? AND user_id=?",
            (event_id, user_id),
        )
        return str(row["status"]) if row else None


# ==========================================================
# Views / modals
# ==========================================================


class RoleInputModal(discord.ui.Modal):
    def __init__(self, cog: "TeamToolsCog", key: str):
        super().__init__(title=f"{key.replace('_', ' ').title()} rolü ayarla")
        self.cog = cog
        self.key = key
        self.role_input = discord.ui.TextInput(
            label="Rol ID / rol etiketi / rol adı",
            placeholder="1234567890 veya @RolAdı",
            max_length=200,
        )
        self.add_item(self.role_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)

        if not is_manage_privileged(interaction.user):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)

        role = resolve_role(interaction.guild, str(self.role_input.value))
        if not role:
            return await interaction.response.send_message("Rol bulunamadı.", ephemeral=True)

        panel = await self.cog.db.get_panel(interaction.guild.id)
        panel[self.key] = role.id
        await self.cog.db.upsert_panel(interaction.guild.id, panel)
        await self.cog.db.add_audit(interaction.guild.id, interaction.user.id, f"panel_{self.key}", f"role_id={role.id}")

        await interaction.response.send_message(f"{self.key.replace('_', ' ').title()} rolü ayarlandı: {role.mention}", ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self, cog: "TeamToolsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    async def _open_modal(self, interaction: discord.Interaction, key: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)
        if not is_manage_privileged(interaction.user):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)
        await interaction.response.send_modal(RoleInputModal(self.cog, key))

    @discord.ui.button(label="Train Rol", style=discord.ButtonStyle.primary, emoji="🎯")
    async def train(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, "train")

    @discord.ui.button(label="Tryout Rol", style=discord.ButtonStyle.primary, emoji="🧪")
    async def tryout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, "tryout")

    @discord.ui.button(label="Spar Rol", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def spar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, "spar")

    @discord.ui.button(label="Teamer Help Rol", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def teamer_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, "teamer_help")


class TrainAttendanceView(discord.ui.View):
    def __init__(self, cog: "TeamToolsCog", event_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id

    async def _update(self, interaction: discord.Interaction, status: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sunucu içinde kullanılmalı.", ephemeral=True)

        event = await self.cog.db.get_train_event(self.event_id)
        if not event or event["status"] != "open":
            return await interaction.response.send_message("Bu train kapatılmış.", ephemeral=True)

        await self.cog.db.set_train_attendance(self.event_id, interaction.guild.id, interaction.user.id, status)
        await self.cog.db.add_audit(interaction.guild.id, interaction.user.id, f"train_{status}", f"event_id={self.event_id}")

        await self.cog.refresh_train_message(interaction.guild, self.event_id)
        text = "Katılımın işaretlendi." if status == "yes" else "Gelemem olarak işaretlendi."
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Katılıyorum", style=discord.ButtonStyle.success, emoji="✅")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._update(interaction, "yes")

    @discord.ui.button(label="Gelemem", style=discord.ButtonStyle.danger, emoji="❌")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._update(interaction, "no")


class SparDecisionView(discord.ui.View):
    def __init__(self, cog: "TeamToolsCog", request_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id

    async def _authorize(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        panel = await self.cog.db.get_panel(interaction.guild.id)
        role_id = panel.get("spar")
        if role_id is None:
            return is_manage_privileged(interaction.user)
        return is_manage_privileged(interaction.user) or any(r.id == role_id for r in interaction.user.roles)

    @discord.ui.button(label="Spar Kabul", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)
        await self.cog.accept_spar(interaction, self.request_id)

    @discord.ui.button(label="Spar Reddet", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)
        await self.cog.reject_spar(interaction, self.request_id)


# ==========================================================
# Cog
# ==========================================================


class TeamToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = TeamToolsDB(DB_PATH)

    # ------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------

    def _embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="PAG Team Tools")
        return embed

    async def _panel_role_mention(self, guild: discord.Guild, key: str) -> str:
        panel = await self.db.get_panel(guild.id)
        return role_mention(guild, panel.get(key))

    async def _can_manage(self, guild: discord.Guild, member: discord.Member, key: str) -> bool:
        if is_manage_privileged(member):
            return True
        panel = await self.db.get_panel(guild.id)
        role_id = panel.get(key)
        if not role_id:
            return False
        return any(r.id == role_id for r in member.roles)

    async def _send_panel_embed(self, ctx: commands.Context) -> None:
        assert ctx.guild
        panel = await self.db.get_panel(ctx.guild.id)
        embed = self._embed(
            "Etk Panel",
            (
                "Rolleri buradan seçersin. Sonradan tekrar açıp değiştirebilirsin.\n\n"
                f"• Train: {role_mention(ctx.guild, panel['train'])}\n"
                f"• Tryout: {role_mention(ctx.guild, panel['tryout'])}\n"
                f"• Spar: {role_mention(ctx.guild, panel['spar'])}\n"
                f"• Teamer Help: {role_mention(ctx.guild, panel['teamer_help'])}\n\n"
                "Butonlardan birine basıp rol ID, rol etiketi ya da rol adını yazman yeterli."
            ),
            discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=PanelView(self))

    def _natural_train_text(self, topic: str, time_text: str, note_text: str) -> str:
        options = [
            f"Bugün {time_text} tarafında train açıyoruz. Bu sefer odak {topic}. Çok uzatmadan gireceğiz, düzenli gelen gelsin.",
            f"Train zamanı: {time_text}. Konu {topic}. Herkes hazır olsun, akışı bozmayalım.",
            f"Toplanma {time_text}. Train içeriği {topic}. Kısa, net, tempolu ilerleyeceğiz.",
        ]
        base = options[hash(topic + time_text) % len(options)]
        if note_text.strip():
            base += f"\n\nEk not: {note_text.strip()}"
        return base

    def _train_embed(self, event_id: int, topic: str, time_text: str, note_text: str, host: discord.Member, yes_count: int, no_count: int) -> discord.Embed:
        embed = self._embed(
            f"Train Duyurusu #{event_id}",
            self._natural_train_text(topic, time_text, note_text),
            discord.Color.orange(),
        )
        embed.add_field(name="Konu", value=clamp_text(topic, 256), inline=True)
        embed.add_field(name="Saat", value=clamp_text(time_text, 256), inline=True)
        embed.add_field(name="Host", value=host.mention, inline=True)
        embed.add_field(name="Katılım", value=f"✅ {yes_count} / ❌ {no_count}", inline=True)
        if note_text.strip():
            embed.add_field(name="Not", value=clamp_text(note_text), inline=False)
        embed.set_author(name=host.display_name, icon_url=host.display_avatar.url)
        return embed

    def _tryout_embed(self, link: str, hoster: str, note_text: str) -> discord.Embed:
        embed = self._embed(
            "Tryout Duyurusu",
            (
                "Tryout süreci başladı. Link üzerinden giriliyor, hoster tek tek test ediyor.\n\n"
                f"Hoster: {hoster}\n"
                f"Not: {note_text or 'Yok'}"
            ),
            discord.Color.purple(),
        )
        embed.add_field(name="Tryout Link", value=clamp_text(link, 1024), inline=False)
        embed.add_field(name="Akış", value="Link → Hoster testi → Sonuç", inline=False)
        return embed

    def _spar_embed(self, request: dict[str, Any]) -> discord.Embed:
        embed = self._embed(
            f"Spar İsteği #{request['id']}",
            (
                f"**İsteyen:** <@{request['requester_id']}>\n"
                f"**Rakip:** {request['opponent_name']}\n"
                f"**Format:** {request['format_text']}\n"
                f"**Tarih:** {request['date_text']}\n"
                f"**Saat:** {request['time_text']}\n"
                f"**Not:** {request['note_text'] or '-'}"
            ),
            discord.Color.gold(),
        )
        embed.set_footer(text=f"Durum: {request['status']}")
        return embed

    # ------------------------------------------------------
    # Panel command
    # ------------------------------------------------------

    @commands.command(name="etkpanel")
    @commands.has_permissions(manage_guild=True)
    async def etkpanel(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        await self._send_panel_embed(ctx)

    @app_commands.command(name="etkpanel", description="TSB/klan rol panelini açar.")
    async def etkpanel_slash(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)
        if not is_manage_privileged(interaction.user):
            return await interaction.response.send_message("Bu işlem için yetkin yok.", ephemeral=True)

        panel = await self.db.get_panel(interaction.guild.id)
        embed = self._embed(
            "Etk Panel",
            (
                "Rolleri buradan seçersin.\n\n"
                f"• Train: {role_mention(interaction.guild, panel['train'])}\n"
                f"• Tryout: {role_mention(interaction.guild, panel['tryout'])}\n"
                f"• Spar: {role_mention(interaction.guild, panel['spar'])}\n"
                f"• Teamer Help: {role_mention(interaction.guild, panel['teamer_help'])}"
            ),
            discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=PanelView(self), ephemeral=True)

    # ------------------------------------------------------
    # Help command
    # ------------------------------------------------------

    @commands.command(name="teamer", aliases=["teamer-help"])
    async def teamer(self, ctx: commands.Context) -> None:
        embed = self._embed(
            "Teamer Help",
            (
                "Kısa yardım menüsü:\n\n"
                "• `!spar-istek Rakip | Tarih | Saat | Not`\n"
                "• `!spar-kabul <id>`\n"
                "• `!spar-reddet <id>`\n"
                "• `!spar-liste`\n"
                "• `!spar-iptal <id>`\n\n"
                "Train ve tryout duyuruları için paneldeki roller kullanılır."
            ),
            discord.Color.green(),
        )
        await ctx.send(embed=embed)

    @app_commands.command(name="teamer_help", description="Teamer yardım menüsünü gösterir.")
    async def teamer_help_slash(self, interaction: discord.Interaction) -> None:
        embed = self._embed(
            "Teamer Help",
            "Prefix sürümü: `!teamer` / `!teamer-help`",
            discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------
    # Train announcement
    # ------------------------------------------------------

    @commands.command(name="train-announcement")
    async def train_announcement(self, ctx: commands.Context, *, args: str = "") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self._can_manage(ctx.guild, ctx.author, "train"):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        topic, time_text, note_text = split_pipe(args, 3, ("genel çalışma", "akşam", ""))
        event_id = await self.db.create_train_event(ctx.guild.id, ctx.author.id, topic, time_text, note_text)
        await self.db.add_audit(ctx.guild.id, ctx.author.id, "train_create", f"event_id={event_id}; topic={topic}")

        yes_count, no_count = await self.db.get_train_counts(event_id)
        embed = self._train_embed(event_id, topic, time_text, note_text, ctx.author, yes_count, no_count)
        mention = await self._panel_role_mention(ctx.guild, "train")
        msg = await ctx.send(content=mention if mention != "Ayar yok" else None, embed=embed, view=TrainAttendanceView(self, event_id))
        await self.db.set_train_meta(event_id, msg.id, msg.channel.id)

    @app_commands.command(name="train_announcement", description="Train duyurusu oluşturur.")
    async def train_announcement_slash(self, interaction: discord.Interaction, konu: str, saat: str, notlar: str = "") -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)
        if not await self._can_manage(interaction.guild, interaction.user, "train"):
            return await interaction.response.send_message("Bu komut için yetkin yok.", ephemeral=True)

        event_id = await self.db.create_train_event(interaction.guild.id, interaction.user.id, konu, saat, notlar)
        yes_count, no_count = await self.db.get_train_counts(event_id)
        embed = self._train_embed(event_id, konu, saat, notlar, interaction.user, yes_count, no_count)
        view = TrainAttendanceView(self, event_id)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        await self.db.set_train_meta(event_id, msg.id, msg.channel.id)

    async def refresh_train_message(self, guild: discord.Guild, event_id: int) -> None:
        event = await self.db.get_train_event(event_id)
        if not event or not event.get("message_id") or not event.get("channel_id"):
            return

        channel = guild.get_channel(int(event["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(int(event["message_id"]))
        except Exception:
            return

        yes_count, no_count = await self.db.get_train_counts(event_id)
        host = guild.get_member(int(event["host_id"])) if guild else None
        if not host:
            host = guild.me if guild.me else None
        if not isinstance(host, discord.Member):
            host = guild.members[0] if guild.members else None  # type: ignore[assignment]
        if not isinstance(host, discord.Member):
            return

        embed = self._train_embed(event_id, event["topic"], event["time_text"], event["note_text"], host, yes_count, no_count)
        await message.edit(embed=embed, view=TrainAttendanceView(self, event_id))

    # ------------------------------------------------------
    # Tryout announcement
    # ------------------------------------------------------

    @commands.command(name="tryout-announcement")
    async def tryout_announcement(self, ctx: commands.Context, *, args: str = "") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self._can_manage(ctx.guild, ctx.author, "tryout"):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        link, hoster, note_text = split_pipe(args, 3, ("", "hoster", ""))
        if not link:
            return await ctx.reply("Link gerekli. Kullanım: `!tryout-announcement link | hoster | not`", mention_author=False)

        embed = self._tryout_embed(link, hoster, note_text)
        mention = await self._panel_role_mention(ctx.guild, "tryout")
        await ctx.send(content=mention if mention != "Ayar yok" else None, embed=embed)

    @app_commands.command(name="tryout_announcement", description="Tryout duyurusu oluşturur.")
    async def tryout_announcement_slash(self, interaction: discord.Interaction, link: str, hoster: str, notlar: str = "") -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)
        if not await self._can_manage(interaction.guild, interaction.user, "tryout"):
            return await interaction.response.send_message("Bu komut için yetkin yok.", ephemeral=True)

        embed = self._tryout_embed(link, hoster, notlar)
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------
    # Spar request / accept / reject
    # ------------------------------------------------------

    @commands.command(name="spar-istek")
    async def spar_istek(self, ctx: commands.Context, *, args: str = "") -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return

        opponent, date_text, time_text, fmt_text, note_text = split_pipe(
            args,
            5,
            ("Rakip takım", "tarih", "saat", "3v3", ""),
        )
        if not opponent.strip():
            return await ctx.reply("Rakip adı gerekli. Kullanım: `!spar-istek Rakip | Tarih | Saat | Format | Not`", mention_author=False)

        request_id = await self.db.create_spar_request(
            ctx.guild.id,
            ctx.author.id,
            opponent,
            date_text,
            time_text,
            fmt_text,
            note_text,
        )
        await self.db.add_audit(ctx.guild.id, ctx.author.id, "spar_create", f"request_id={request_id}; opponent={opponent}")

        request = await self.db.get_spar_request(request_id)
        if not request:
            return await ctx.reply("Spar isteği oluşturulamadı.", mention_author=False)

        embed = self._spar_embed(request)
        msg = await ctx.send(embed=embed, view=SparDecisionView(self, request_id))
        await self.db.set_spar_meta(request_id, msg.id, msg.channel.id)

    @app_commands.command(name="spar_istek", description="Spar isteği açar.")
    async def spar_istek_slash(
        self,
        interaction: discord.Interaction,
        rakip: str,
        tarih: str,
        saat: str,
        format: str,
        notlar: str = "",
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Sadece sunucuda kullanılabilir.", ephemeral=True)

        request_id = await self.db.create_spar_request(
            interaction.guild.id,
            interaction.user.id,
            rakip,
            tarih,
            saat,
            format,
            notlar,
        )
        request = await self.db.get_spar_request(request_id)
        if not request:
            return await interaction.response.send_message("Spar isteği oluşturulamadı.", ephemeral=True)

        embed = self._spar_embed(request)
        await interaction.response.send_message(embed=embed, view=SparDecisionView(self, request_id))
        msg = await interaction.original_response()
        await self.db.set_spar_meta(request_id, msg.id, msg.channel.id)

    async def accept_spar(self, interaction: discord.Interaction, request_id: int) -> None:
        request = await self.db.get_spar_request(request_id)
        if not request:
            return await interaction.response.send_message("Spar isteği bulunamadı.", ephemeral=True)
        if request["status"] != "open":
            return await interaction.response.send_message("Bu spar zaten kapalı.", ephemeral=True)

        await self.db.set_spar_status(request_id, "accepted", interaction.user.id)
        await self.db.add_audit(interaction.guild.id, interaction.user.id, "spar_accept", f"request_id={request_id}")
        await interaction.response.send_message(f"Spar isteği #{request_id} kabul edildi.", ephemeral=True)
        await self._refresh_spar_message(interaction.guild, request_id, accepted=True)

    async def reject_spar(self, interaction: discord.Interaction, request_id: int) -> None:
        request = await self.db.get_spar_request(request_id)
        if not request:
            return await interaction.response.send_message("Spar isteği bulunamadı.", ephemeral=True)
        if request["status"] != "open":
            return await interaction.response.send_message("Bu spar zaten kapalı.", ephemeral=True)

        await self.db.set_spar_status(request_id, "rejected", interaction.user.id)
        await self.db.add_audit(interaction.guild.id, interaction.user.id, "spar_reject", f"request_id={request_id}")
        await interaction.response.send_message(f"Spar isteği #{request_id} reddedildi.", ephemeral=True)
        await self._refresh_spar_message(interaction.guild, request_id, accepted=False)

    async def _refresh_spar_message(self, guild: discord.Guild, request_id: int, accepted: bool) -> None:
        request = await self.db.get_spar_request(request_id)
        if not request or not request.get("channel_id") or not request.get("message_id"):
            return
        channel = guild.get_channel(int(request["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(request["message_id"]))
        except Exception:
            return

        color = discord.Color.green() if accepted else discord.Color.red()
        embed = self._embed(
            f"Spar { 'Kabul' if accepted else 'Reddet' } #{request_id}",
            (
                f"**İsteyen:** <@{request['requester_id']}>\n"
                f"**Rakip:** {request['opponent_name']}\n"
                f"**Format:** {request['format_text']}\n"
                f"**Tarih:** {request['date_text']}\n"
                f"**Saat:** {request['time_text']}\n"
                f"**Not:** {request['note_text'] or '-'}"
            ),
            color,
        )
        await message.edit(embed=embed, view=None)

    @commands.command(name="spar-kabul")
    async def spar_kabul(self, ctx: commands.Context, request_id: int) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self._can_manage(ctx.guild, ctx.author, "spar"):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        request = await self.db.get_spar_request(request_id)
        if not request:
            return await ctx.reply("Spar isteği bulunamadı.", mention_author=False)
        if request["status"] != "open":
            return await ctx.reply("Bu spar zaten kapalı.", mention_author=False)

        await self.db.set_spar_status(request_id, "accepted", ctx.author.id)
        await self.db.add_audit(ctx.guild.id, ctx.author.id, "spar_accept_cmd", f"request_id={request_id}")
        await ctx.reply(f"Spar isteği #{request_id} kabul edildi.", mention_author=False)
        await self._refresh_spar_message(ctx.guild, request_id, accepted=True)

    @commands.command(name="spar-reddet")
    async def spar_reddet(self, ctx: commands.Context, request_id: int) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        if not await self._can_manage(ctx.guild, ctx.author, "spar"):
            return await ctx.reply("Bu komut için yetkin yok.", mention_author=False)

        request = await self.db.get_spar_request(request_id)
        if not request:
            return await ctx.reply("Spar isteği bulunamadı.", mention_author=False)
        if request["status"] != "open":
            return await ctx.reply("Bu spar zaten kapalı.", mention_author=False)

        await self.db.set_spar_status(request_id, "rejected", ctx.author.id)
        await self.db.add_audit(ctx.guild.id, ctx.author.id, "spar_reject_cmd", f"request_id={request_id}")
        await ctx.reply(f"Spar isteği #{request_id} reddedildi.", mention_author=False)
        await self._refresh_spar_message(ctx.guild, request_id, accepted=False)

    @commands.command(name="spar-liste")
    async def spar_liste(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return
        rows = await self.db.list_open_spars(ctx.guild.id)
        if not rows:
            return await ctx.reply("Açık spar isteği yok.", mention_author=False)

        lines = []
        for row in rows[:10]:
            lines.append(
                f"`#{row['id']}` | {row['opponent_name']} | {row['date_text']} {row['time_text']} | {row['format_text']} | <@{row['requester_id']}>"
            )
        embed = self._embed("Açık Spar İstekleri", "\n".join(lines), discord.Color.gold())
        await ctx.send(embed=embed)

    @commands.command(name="spar-iptal")
    async def spar_iptal(self, ctx: commands.Context, request_id: int) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return
        request = await self.db.get_spar_request(request_id)
        if not request:
            return await ctx.reply("Spar isteği bulunamadı.", mention_author=False)
        if request["requester_id"] != ctx.author.id and not await self._can_manage(ctx.guild, ctx.author, "spar"):
            return await ctx.reply("Bu isteği iptal etme yetkin yok.", mention_author=False)

        await self.db.cancel_spar(request_id)
        await self.db.add_audit(ctx.guild.id, ctx.author.id, "spar_cancel", f"request_id={request_id}")
        await ctx.reply(f"Spar isteği #{request_id} iptal edildi.", mention_author=False)

    # ------------------------------------------------------
    # Tryout helper
    # ------------------------------------------------------

    @commands.command(name="tryout-help")
    async def tryout_help(self, ctx: commands.Context) -> None:
        embed = self._embed(
            "Tryout Akışı",
            (
                "1) Tryout duyurusu atılır.\n"
                "2) Link paylaşılır.\n"
                "3) Hoster adayları tek tek test eder.\n"
                "4) Sonuçlar kaydedilir."
            ),
            discord.Color.purple(),
        )
        await ctx.send(embed=embed)

    @app_commands.command(name="tryout_help", description="Tryout akışını gösterir.")
    async def tryout_help_slash(self, interaction: discord.Interaction) -> None:
        embed = self._embed("Tryout Akışı", "Prefix sürümü: `!tryout-help`", discord.Color.purple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------
    # Event / lifecycle
    # ------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        LOGGER.info("TeamToolsCog hazır.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamToolsCog(bot))
