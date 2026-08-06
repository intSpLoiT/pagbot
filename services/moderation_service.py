
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, cast

from core.database import Database
from utils.errors import PAGError


# ============================================================
# GIF CONSTANTS
# ============================================================

DEFAULT_GIF_KEY = "default"

GIF_KEYS = {
    "warn",
    "timeout",
    "kick",
    "ban",
    "purge",
    "lock",
    "unlock",
    "slowmode",
    DEFAULT_GIF_KEY,
}

# ============================================================
# GIF MODELS
# ============================================================

DEFAULT_GIF_KEY = "default"


@dataclass(slots=True, frozen=True)
class ModerationGIFRecord:
    """
    Moderation GIF ayar kaydı.
    """

    guild_id: int
    gif_key: str
    gif_url: str
    updated_by: int | None
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "ModerationGIFRecord":
        return cls(
            guild_id=int(row["guild_id"]),
            gif_key=str(row["gif_key"]),
            gif_url=str(row["gif_url"]),
            updated_by=int(row["updated_by"])
            if _row_has_key(row, "updated_by") and row["updated_by"] is not None
            else None,
            updated_at=str(row["updated_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "gif_key": self.gif_key,
            "gif_url": self.gif_url,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


# ============================================================
# ERRORS
# ============================================================


class ModerationServiceError(PAGError):
    """
    Moderation Service için temel hata sınıfı.
    """


class ModerationNotFoundError(ModerationServiceError):
    """
    Kayıt bulunamadığında oluşur.
    """


class ModerationValidationError(ModerationServiceError):
    """
    Girilen veri geçersiz olduğunda oluşur.
    """


class ModerationConflictError(ModerationServiceError):
    """
    Aynı hedef için çakışan kayıt bulunduğunda oluşur.
    """


class ModerationStateError(ModerationServiceError):
    """
    Kanal / kullanıcı durum işlemlerinde oluşur.
    """


# ============================================================
# CONSTANTS
# ============================================================


WARNINGS_TABLE = "warnings"
NOTES_TABLE = "notes"
MUTES_TABLE = "mutes"
CHANNEL_STATES_TABLE = "channel_states"
AUDIT_LOGS_TABLE = "moderation_audit_logs"

MAX_REASON_LENGTH = 1000
MAX_NOTE_LENGTH = 2000
MAX_PAYLOAD_LENGTH = 8000


# ============================================================
# HELPERS
# ============================================================


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _positive_int(value: int | None, field_name: str) -> int:
    if value is None:
        raise ModerationValidationError(f"{field_name} is required.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ModerationValidationError(f"{field_name} must be an integer.") from error
    if result <= 0:
        raise ModerationValidationError(f"{field_name} must be positive.")
    return result


def _coerce_optional_positive_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    result = _positive_int(value, field_name)
    return result


def _normalize_text(value: str | None, *, default: str, max_length: int) -> str:
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _serialize_payload(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    try:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ModerationValidationError("Payload is not JSON serializable.") from error
    if len(text) > MAX_PAYLOAD_LENGTH:
        raise ModerationValidationError("Payload is too large.")
    return text


def _deserialize_payload(payload_json: str | None) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _row_has_key(row: Any, key: str) -> bool:
    try:
        return key in row.keys()
    except Exception:
        return False


# ============================================================
# DATA MODELS
# ============================================================


@dataclass(slots=True, frozen=True)
class ModerationWarningRecord:
    """
    Warn kaydı.
    """

    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str
    created_at: str
    active: bool

    note: str | None = None
    expires_at: str | None = None
    cleared_by: int | None = None
    cleared_at: str | None = None
    source: str = "discord"
    roblox_id: int | None = None
    roblox_username: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ModerationWarningRecord":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            moderator_id=int(row["moderator_id"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
            active=bool(row["active"]),
            note=str(row["note"]) if _row_has_key(row, "note") and row["note"] is not None else None,
            expires_at=str(row["expires_at"]) if _row_has_key(row, "expires_at") and row["expires_at"] is not None else None,
            cleared_by=int(row["cleared_by"]) if _row_has_key(row, "cleared_by") and row["cleared_by"] is not None else None,
            cleared_at=str(row["cleared_at"]) if _row_has_key(row, "cleared_at") and row["cleared_at"] is not None else None,
            source=str(row["source"]) if _row_has_key(row, "source") and row["source"] is not None else "discord",
            roblox_id=int(row["roblox_id"]) if _row_has_key(row, "roblox_id") and row["roblox_id"] is not None else None,
            roblox_username=str(row["roblox_username"]) if _row_has_key(row, "roblox_username") and row["roblox_username"] is not None else None,
            metadata=_deserialize_payload(str(row["metadata_json"])) if _row_has_key(row, "metadata_json") and row["metadata_json"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "moderator_id": self.moderator_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "active": self.active,
            "note": self.note,
            "expires_at": self.expires_at,
            "cleared_by": self.cleared_by,
            "cleared_at": self.cleared_at,
            "source": self.source,
            "roblox_id": self.roblox_id,
            "roblox_username": self.roblox_username,
            "metadata": self.metadata,
        }


@dataclass(slots=True, frozen=True)
class ModerationNoteRecord:
    """
    Moderatör notu.
    """

    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    note: str
    created_at: str
    active: bool

    deleted_by: int | None = None
    deleted_at: str | None = None
    source: str = "discord"
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ModerationNoteRecord":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            moderator_id=int(row["moderator_id"]),
            note=str(row["note"]),
            created_at=str(row["created_at"]),
            active=bool(row["active"]),
            deleted_by=int(row["deleted_by"]) if _row_has_key(row, "deleted_by") and row["deleted_by"] is not None else None,
            deleted_at=str(row["deleted_at"]) if _row_has_key(row, "deleted_at") and row["deleted_at"] is not None else None,
            source=str(row["source"]) if _row_has_key(row, "source") and row["source"] is not None else "discord",
            metadata=_deserialize_payload(str(row["metadata_json"])) if _row_has_key(row, "metadata_json") and row["metadata_json"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "moderator_id": self.moderator_id,
            "note": self.note,
            "created_at": self.created_at,
            "active": self.active,
            "deleted_by": self.deleted_by,
            "deleted_at": self.deleted_at,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass(slots=True, frozen=True)
class ModerationMuteRecord:
    """
    Mute / timeout kaydı.
    """

    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    reason: str
    created_at: str
    active: bool

    expires_at: str | None = None
    cleared_by: int | None = None
    cleared_at: str | None = None
    source: str = "discord"
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ModerationMuteRecord":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            moderator_id=int(row["moderator_id"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
            active=bool(row["active"]),
            expires_at=str(row["expires_at"]) if _row_has_key(row, "expires_at") and row["expires_at"] is not None else None,
            cleared_by=int(row["cleared_by"]) if _row_has_key(row, "cleared_by") and row["cleared_by"] is not None else None,
            cleared_at=str(row["cleared_at"]) if _row_has_key(row, "cleared_at") and row["cleared_at"] is not None else None,
            source=str(row["source"]) if _row_has_key(row, "source") and row["source"] is not None else "discord",
            metadata=_deserialize_payload(str(row["metadata_json"])) if _row_has_key(row, "metadata_json") and row["metadata_json"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "moderator_id": self.moderator_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "active": self.active,
            "expires_at": self.expires_at,
            "cleared_by": self.cleared_by,
            "cleared_at": self.cleared_at,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass(slots=True, frozen=True)
class ModerationChannelStateRecord:
    """
    Kanal kilidi / slowmode gibi durumlar.
    """

    guild_id: int
    channel_id: int
    locked: bool
    slowmode_seconds: int
    moderator_id: int | None
    reason: str | None
    updated_at: str
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ModerationChannelStateRecord":
        return cls(
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            locked=bool(row["locked"]),
            slowmode_seconds=int(row["slowmode_seconds"]),
            moderator_id=int(row["moderator_id"]) if _row_has_key(row, "moderator_id") and row["moderator_id"] is not None else None,
            reason=str(row["reason"]) if _row_has_key(row, "reason") and row["reason"] is not None else None,
            updated_at=str(row["updated_at"]),
            metadata=_deserialize_payload(str(row["metadata_json"])) if _row_has_key(row, "metadata_json") and row["metadata_json"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "locked": self.locked,
            "slowmode_seconds": self.slowmode_seconds,
            "moderator_id": self.moderator_id,
            "reason": self.reason,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass(slots=True, frozen=True)
class ModerationAuditRecord:
    """
    Genel audit kaydı.
    """

    id: int
    guild_id: int | None
    action: str
    moderator_id: int | None
    target_user_id: int | None
    target_channel_id: int | None
    reason: str | None
    created_at: str
    source: str
    payload: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ModerationAuditRecord":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]) if _row_has_key(row, "guild_id") and row["guild_id"] is not None else None,
            action=str(row["action"]),
            moderator_id=int(row["moderator_id"]) if _row_has_key(row, "moderator_id") and row["moderator_id"] is not None else None,
            target_user_id=int(row["target_user_id"]) if _row_has_key(row, "target_user_id") and row["target_user_id"] is not None else None,
            target_channel_id=int(row["target_channel_id"]) if _row_has_key(row, "target_channel_id") and row["target_channel_id"] is not None else None,
            reason=str(row["reason"]) if _row_has_key(row, "reason") and row["reason"] is not None else None,
            created_at=str(row["created_at"]),
            source=str(row["source"]) if _row_has_key(row, "source") and row["source"] is not None else "discord",
            payload=_deserialize_payload(str(row["payload_json"])) if _row_has_key(row, "payload_json") and row["payload_json"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "action": self.action,
            "moderator_id": self.moderator_id,
            "target_user_id": self.target_user_id,
            "target_channel_id": self.target_channel_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "source": self.source,
            "payload": self.payload,
        }


@dataclass(slots=True, frozen=True)
class ModerationUserHistory:
    """
    Bir kullanıcının moderasyon geçmişinin özeti.
    """

    guild_id: int
    user_id: int
    warnings: list[ModerationWarningRecord]
    notes: list[ModerationNoteRecord]
    mutes: list[ModerationMuteRecord]
    audits: list[ModerationAuditRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "warnings": [item.to_dict() for item in self.warnings],
            "notes": [item.to_dict() for item in self.notes],
            "mutes": [item.to_dict() for item in self.mutes],
            "audits": [item.to_dict() for item in self.audits],
        }


# ============================================================
# SERVICE
# ============================================================


class ModerationService:
    """
    PAG moderasyon verisi için merkez servis.

    Tasarım hedefleri:
        - core.database.Database ile uyumlu
        - web panelinden çağrılabilir
        - Discord nesnesine bağımlı değil
        - mevcut kayıtları bozmaz
        - audit trail üretir
        - ileride cog / web / API katmanı tarafından ortak kullanılabilir
    """

    def __init__(
        self,
        database: Database,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.logger = logger

        self._initialized = False
        self._lock = asyncio.Lock()

    # ========================================================
    # INITIALIZATION
    # ========================================================

    async def initialize(self) -> None:
        """
        Gerekli tabloları hazırlar.

        Bu metod:
            - var olan kayıtları silmez
            - eksik kolonları ekler
            - indexleri oluşturur
        """

        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            await self._create_tables()
            await self._ensure_schema()
            self._initialized = True

            self._log(logging.INFO, "Moderation service initialized.")

    async def _create_tables(self) -> None:
        """
        Tabloları create if not exists olarak kurar.
        """

        await self.database.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {WARNINGS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT,
                cleared_by INTEGER,
                cleared_at TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                roblox_id INTEGER,
                roblox_username TEXT,
                metadata_json TEXT
            )
            """
        )

        await self.database.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {NOTES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                deleted_by INTEGER,
                deleted_at TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                metadata_json TEXT
            )
            """
        )

        await self.database.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MUTES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT,
                cleared_by INTEGER,
                cleared_at TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                metadata_json TEXT
            )
            """
        )

        await self.database.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHANNEL_STATES_TABLE} (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                locked INTEGER NOT NULL DEFAULT 0,
                slowmode_seconds INTEGER NOT NULL DEFAULT 0,
                moderator_id INTEGER,
                reason TEXT,
                updated_at TEXT NOT NULL,
                metadata_json TEXT,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )

        await self.database.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {AUDIT_LOGS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                action TEXT NOT NULL,
                moderator_id INTEGER,
                target_user_id INTEGER,
                target_channel_id INTEGER,
                reason TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'discord'
            )
            """
        )

    async def _ensure_schema(self) -> None:
        """
        Eski sürümlerden gelen eksik kolonları tamamlar.
        """

        # Warnings
        await self._ensure_column(WARNINGS_TABLE, "note", "TEXT")
        await self._ensure_column(WARNINGS_TABLE, "expires_at", "TEXT")
        await self._ensure_column(WARNINGS_TABLE, "cleared_by", "INTEGER")
        await self._ensure_column(WARNINGS_TABLE, "cleared_at", "TEXT")
        await self._ensure_column(WARNINGS_TABLE, "source", "TEXT")
        await self._ensure_column(WARNINGS_TABLE, "roblox_id", "INTEGER")
        await self._ensure_column(WARNINGS_TABLE, "roblox_username", "TEXT")
        await self._ensure_column(WARNINGS_TABLE, "metadata_json", "TEXT")

        # Notes
        await self._ensure_column(NOTES_TABLE, "deleted_by", "INTEGER")
        await self._ensure_column(NOTES_TABLE, "deleted_at", "TEXT")
        await self._ensure_column(NOTES_TABLE, "source", "TEXT")
        await self._ensure_column(NOTES_TABLE, "metadata_json", "TEXT")

        # Mutes
        await self._ensure_column(MUTES_TABLE, "expires_at", "TEXT")
        await self._ensure_column(MUTES_TABLE, "cleared_by", "INTEGER")
        await self._ensure_column(MUTES_TABLE, "cleared_at", "TEXT")
        await self._ensure_column(MUTES_TABLE, "source", "TEXT")
        await self._ensure_column(MUTES_TABLE, "metadata_json", "TEXT")

        # Channel states
        await self._ensure_column(CHANNEL_STATES_TABLE, "moderator_id", "INTEGER")
        await self._ensure_column(CHANNEL_STATES_TABLE, "reason", "TEXT")
        await self._ensure_column(CHANNEL_STATES_TABLE, "metadata_json", "TEXT")

        # Audit
        await self._ensure_column(AUDIT_LOGS_TABLE, "source", "TEXT")

        # Indexes
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{WARNINGS_TABLE}_guild_user_active
            ON {WARNINGS_TABLE}(guild_id, user_id, active)
            """
        )
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{WARNINGS_TABLE}_created_at
            ON {WARNINGS_TABLE}(created_at)
            """
        )
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{NOTES_TABLE}_guild_user_active
            ON {NOTES_TABLE}(guild_id, user_id, active)
            """
        )
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{MUTES_TABLE}_guild_user_active
            ON {MUTES_TABLE}(guild_id, user_id, active)
            """
        )
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{AUDIT_LOGS_TABLE}_guild_created
            ON {AUDIT_LOGS_TABLE}(guild_id, created_at)
            """
        )
        await self.database.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{AUDIT_LOGS_TABLE}_user_created
            ON {AUDIT_LOGS_TABLE}(target_user_id, created_at)
            """
        )

    async def _ensure_column(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        """
        Tabloda eksik kolon varsa ekler.
        """

        rows = await self.database.fetchall(
            f"PRAGMA table_info({table_name})",
            (),
        )
        columns = {str(row["name"]) for row in rows}

        if column_name in columns:
            return

        try:
            await self.database.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )
        except Exception as error:
            self._log(
                logging.WARNING,
                "Could not add column %s.%s: %s",
                table_name,
                column_name,
                error,
            )

    # ========================================================
    # GENERAL AUDIT
    # ========================================================

    async def record_audit(
        self,
        *,
        action: str,
        guild_id: int | None = None,
        moderator_id: int | None = None,
        target_user_id: int | None = None,
        target_channel_id: int | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "discord",
    ) -> int:
        """
        Genel moderasyon audit kaydı.
        """

        await self.initialize()

        action = action.strip()
        if not action:
            raise ModerationValidationError("Action cannot be empty.")

        payload_json = _serialize_payload(payload)

        cursor = await self.database.execute(
            f"""
            INSERT INTO {AUDIT_LOGS_TABLE} (
                guild_id,
                action,
                moderator_id,
                target_user_id,
                target_channel_id,
                reason,
                payload_json,
                created_at,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                action,
                moderator_id,
                target_user_id,
                target_channel_id,
                _normalize_optional_text(reason, max_length=MAX_REASON_LENGTH),
                payload_json,
                _utc_now(),
                source,
            ),
        )

        return int(cursor.lastrowid)
    async def get_statistics(
        self,
        guild_id: int,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Moderation cog ile uyumluluk için istatistik döndürür."""

        if user_id is not None:
            return {
                "warnings": await self.count_warnings(
                    guild_id=guild_id,
                    user_id=user_id,
                    active_only=False,
                ),
                "active_warnings": await self.count_warnings(
                    guild_id=guild_id,
                    user_id=user_id,
                    active_only=True,
                ),
                "notes": await self.count_notes(
                    guild_id=guild_id,
                    user_id=user_id,
                    active_only=False,
                ),
                "mutes": await self.count_mutes(
                    guild_id=guild_id,
                    user_id=user_id,
                    active_only=False,
                ),
            }

        summary = await self.get_guild_summary(guild_id=guild_id)

        return {
            "warnings": summary["warnings_total"],
            "active_warnings": summary["warnings_active"],
            "notes": summary["notes_active"],
            "mutes": summary["mutes_active"],
        }


    async def record_case(
        self,
        guild_id: int,
        moderator_id: int,
        target_user_id: int,
        action: str,
        *,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Moderation cog ile uyumluluk için vaka kaydı oluşturur."""

        audit_id = await self.record_audit(
            guild_id=guild_id,
            action=action,
            moderator_id=moderator_id,
            target_user_id=target_user_id,
            reason=reason,
            payload=details,
        )

        return {
            "id": audit_id,
            "guild_id": guild_id,
            "action": action,
            "moderator_id": moderator_id,
            "target_user_id": target_user_id,
            "reason": reason,
            "details": details,
        }
    async def list_audit_logs(
        self,
        *,
        guild_id: int | None = None,
        target_user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModerationAuditRecord]:
        await self.initialize()

        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        clauses: list[str] = []
        params: list[Any] = []

        if guild_id is not None:
            clauses.append("guild_id = ?")
            params.append(guild_id)
        if target_user_id is not None:
            clauses.append("target_user_id = ?")
            params.append(target_user_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {AUDIT_LOGS_TABLE}
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )

        return [ModerationAuditRecord.from_row(row) for row in rows]

    # ========================================================
    # WARNINGS
    # ========================================================

    async def create_warning(
        self,
        *,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        reason: str,
        note: str | None = None,
        expires_at: datetime | str | None = None,
        roblox_id: int | None = None,
        roblox_username: str | None = None,
        source: str = "discord",
        metadata: dict[str, Any] | None = None,
    ) -> ModerationWarningRecord:
        """
        Yeni warn oluşturur.
        """

        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        moderator_id = _positive_int(moderator_id, "moderator_id")

        reason = _normalize_text(reason, default="", max_length=MAX_REASON_LENGTH)
        if not reason:
            raise ModerationValidationError("Reason cannot be empty.")

        note = _normalize_optional_text(note, max_length=MAX_NOTE_LENGTH)
        expires_at_text = self._coerce_datetime(expires_at)

        cursor = await self.database.execute(
            f"""
            INSERT INTO {WARNINGS_TABLE} (
                guild_id,
                user_id,
                moderator_id,
                reason,
                note,
                created_at,
                active,
                expires_at,
                source,
                roblox_id,
                roblox_username,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                moderator_id,
                reason,
                note,
                _utc_now(),
                expires_at_text,
                source,
                roblox_id,
                _normalize_optional_text(roblox_username, max_length=100),
                _serialize_payload(metadata),
            ),
        )

        warning_id = int(cursor.lastrowid)
        record = await self.get_warning(warning_id)
        if record is None:
            raise ModerationServiceError("Warning record could not be reloaded.")

        await self._safe_audit(
            action="warning_created",
            guild_id=guild_id,
            moderator_id=moderator_id,
            target_user_id=user_id,
            reason=reason,
            payload=record.to_dict(),
            source=source,
        )

        return record

    async def get_warning(self, warning_id: int) -> ModerationWarningRecord | None:
        await self.initialize()

        warning_id = _positive_int(warning_id, "warning_id")

        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {WARNINGS_TABLE}
            WHERE id = ?
            LIMIT 1
            """,
            (warning_id,),
        )
        return ModerationWarningRecord.from_row(row) if row else None

    async def list_warnings(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModerationWarningRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {WARNINGS_TABLE}
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )

        return [ModerationWarningRecord.from_row(row) for row in rows]

    async def count_warnings(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
    ) -> int:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        row = await self.database.fetchone(
            f"""
            SELECT COUNT(*) AS c
            FROM {WARNINGS_TABLE}
            WHERE {' AND '.join(clauses)}
            """,
            tuple(params),
        )
        return int(row["c"]) if row else 0

    async def clear_warning(
        self,
        warning_id: int,
        *,
        cleared_by: int,
        note: str | None = None,
    ) -> ModerationWarningRecord:
        await self.initialize()

        warning_id = _positive_int(warning_id, "warning_id")
        cleared_by = _positive_int(cleared_by, "cleared_by")

        warning = await self.get_warning(warning_id)
        if warning is None:
            raise ModerationNotFoundError(f"Warning not found: {warning_id}")

        if not warning.active:
            return warning

        await self.database.execute(
            f"""
            UPDATE {WARNINGS_TABLE}
            SET
                active = 0,
                cleared_by = ?,
                cleared_at = ?,
                note = COALESCE(?, note)
            WHERE id = ?
            """,
            (
                cleared_by,
                _utc_now(),
                _normalize_optional_text(note, max_length=MAX_NOTE_LENGTH),
                warning_id,
            ),
        )

        updated = await self.get_warning(warning_id)
        if updated is None:
            raise ModerationServiceError("Cleared warning could not be reloaded.")

        await self._safe_audit(
            action="warning_cleared",
            guild_id=warning.guild_id,
            moderator_id=cleared_by,
            target_user_id=warning.user_id,
            reason=note or warning.reason,
            payload=updated.to_dict(),
        )

        return updated

    async def clear_warnings_for_user(
        self,
        *,
        guild_id: int,
        user_id: int,
        cleared_by: int,
        note: str | None = None,
    ) -> list[ModerationWarningRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        cleared_by = _positive_int(cleared_by, "cleared_by")

        warnings = await self.list_warnings(
            guild_id=guild_id,
            user_id=user_id,
            active_only=True,
            limit=500,
            offset=0,
        )

        if not warnings:
            return []

        now = _utc_now()
        queries: list[tuple[str, Iterable[Any]]] = []

        for warning in warnings:
            queries.append(
                (
                    f"""
                    UPDATE {WARNINGS_TABLE}
                    SET
                        active = 0,
                        cleared_by = ?,
                        cleared_at = ?,
                        note = COALESCE(?, note)
                    WHERE id = ?
                    """,
                    (
                        cleared_by,
                        now,
                        _normalize_optional_text(note, max_length=MAX_NOTE_LENGTH),
                        warning.id,
                    ),
                )
            )

        await self.database.transaction(queries)

        updated = await self.list_warnings(
            guild_id=guild_id,
            user_id=user_id,
            active_only=False,
            limit=500,
            offset=0,
        )

        await self._safe_audit(
            action="warnings_cleared_bulk",
            guild_id=guild_id,
            moderator_id=cleared_by,
            target_user_id=user_id,
            reason=note,
            payload={
                "cleared_count": len(warnings),
                "warning_ids": [item.id for item in warnings],
            },
        )

        return updated

    async def has_active_warnings(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> bool:
        return (await self.count_warnings(guild_id=guild_id, user_id=user_id, active_only=True)) > 0

    # ========================================================
    # NOTES
    # ========================================================

    async def create_note(
        self,
        *,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        note: str,
        source: str = "discord",
        metadata: dict[str, Any] | None = None,
    ) -> ModerationNoteRecord:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        moderator_id = _positive_int(moderator_id, "moderator_id")

        note = _normalize_text(note, default="", max_length=MAX_NOTE_LENGTH)
        if not note:
            raise ModerationValidationError("Note cannot be empty.")

        cursor = await self.database.execute(
            f"""
            INSERT INTO {NOTES_TABLE} (
                guild_id,
                user_id,
                moderator_id,
                note,
                created_at,
                active,
                source,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                guild_id,
                user_id,
                moderator_id,
                note,
                _utc_now(),
                source,
                _serialize_payload(metadata),
            ),
        )

        note_id = int(cursor.lastrowid)
        record = await self.get_note(note_id)
        if record is None:
            raise ModerationServiceError("Note record could not be reloaded.")

        await self._safe_audit(
            action="note_created",
            guild_id=guild_id,
            moderator_id=moderator_id,
            target_user_id=user_id,
            reason=note,
            payload=record.to_dict(),
            source=source,
        )

        return record

    async def get_note(self, note_id: int) -> ModerationNoteRecord | None:
        await self.initialize()

        note_id = _positive_int(note_id, "note_id")

        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {NOTES_TABLE}
            WHERE id = ?
            LIMIT 1
            """,
            (note_id,),
        )
        return ModerationNoteRecord.from_row(row) if row else None

    async def list_notes(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModerationNoteRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {NOTES_TABLE}
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )

        return [ModerationNoteRecord.from_row(row) for row in rows]

    async def count_notes(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
    ) -> int:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        row = await self.database.fetchone(
            f"""
            SELECT COUNT(*) AS c
            FROM {NOTES_TABLE}
            WHERE {' AND '.join(clauses)}
            """,
            tuple(params),
        )
        return int(row["c"]) if row else 0

    async def delete_note(
        self,
        note_id: int,
        *,
        deleted_by: int,
    ) -> ModerationNoteRecord:
        await self.initialize()

        note_id = _positive_int(note_id, "note_id")
        deleted_by = _positive_int(deleted_by, "deleted_by")

        note = await self.get_note(note_id)
        if note is None:
            raise ModerationNotFoundError(f"Note not found: {note_id}")

        if not note.active:
            return note

        await self.database.execute(
            f"""
            UPDATE {NOTES_TABLE}
            SET
                active = 0,
                deleted_by = ?,
                deleted_at = ?
            WHERE id = ?
            """,
            (
                deleted_by,
                _utc_now(),
                note_id,
            ),
        )

        updated = await self.get_note(note_id)
        if updated is None:
            raise ModerationServiceError("Deleted note could not be reloaded.")

        await self._safe_audit(
            action="note_deleted",
            guild_id=note.guild_id,
            moderator_id=deleted_by,
            target_user_id=note.user_id,
            reason=note.note,
            payload=updated.to_dict(),
        )

        return updated

    async def clear_notes_for_user(
        self,
        *,
        guild_id: int,
        user_id: int,
        deleted_by: int,
    ) -> list[ModerationNoteRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        deleted_by = _positive_int(deleted_by, "deleted_by")

        notes = await self.list_notes(
            guild_id=guild_id,
            user_id=user_id,
            active_only=True,
            limit=500,
            offset=0,
        )

        if not notes:
            return []

        now = _utc_now()
        queries: list[tuple[str, Iterable[Any]]] = []
        for note in notes:
            queries.append(
                (
                    f"""
                    UPDATE {NOTES_TABLE}
                    SET
                        active = 0,
                        deleted_by = ?,
                        deleted_at = ?
                    WHERE id = ?
                    """,
                    (deleted_by, now, note.id),
                )
            )

        await self.database.transaction(queries)

        await self._safe_audit(
            action="notes_cleared_bulk",
            guild_id=guild_id,
            moderator_id=deleted_by,
            target_user_id=user_id,
            payload={"note_ids": [item.id for item in notes]},
        )

        return await self.list_notes(
            guild_id=guild_id,
            user_id=user_id,
            active_only=False,
            limit=500,
            offset=0,
        )

    # ========================================================
    # MUTES
    # ========================================================

    async def create_mute(
        self,
        *,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        reason: str,
        expires_at: datetime | str | None = None,
        source: str = "discord",
        metadata: dict[str, Any] | None = None,
    ) -> ModerationMuteRecord:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        moderator_id = _positive_int(moderator_id, "moderator_id")

        reason = _normalize_text(reason, default="", max_length=MAX_REASON_LENGTH)
        if not reason:
            raise ModerationValidationError("Reason cannot be empty.")

        cursor = await self.database.execute(
            f"""
            INSERT INTO {MUTES_TABLE} (
                guild_id,
                user_id,
                moderator_id,
                reason,
                created_at,
                active,
                expires_at,
                source,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                moderator_id,
                reason,
                _utc_now(),
                self._coerce_datetime(expires_at),
                source,
                _serialize_payload(metadata),
            ),
        )

        mute_id = int(cursor.lastrowid)
        record = await self.get_mute(mute_id)
        if record is None:
            raise ModerationServiceError("Mute record could not be reloaded.")

        await self._safe_audit(
            action="mute_created",
            guild_id=guild_id,
            moderator_id=moderator_id,
            target_user_id=user_id,
            reason=reason,
            payload=record.to_dict(),
            source=source,
        )

        return record

    async def get_mute(self, mute_id: int) -> ModerationMuteRecord | None:
        await self.initialize()

        mute_id = _positive_int(mute_id, "mute_id")

        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {MUTES_TABLE}
            WHERE id = ?
            LIMIT 1
            """,
            (mute_id,),
        )
        return ModerationMuteRecord.from_row(row) if row else None

    async def list_mutes(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModerationMuteRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {MUTES_TABLE}
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )
        return [ModerationMuteRecord.from_row(row) for row in rows]

    async def count_mutes(
        self,
        *,
        guild_id: int,
        user_id: int | None = None,
        active_only: bool = True,
    ) -> int:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        clauses = ["guild_id = ?"]
        params: list[Any] = [guild_id]

        if user_id is not None:
            params.append(_positive_int(user_id, "user_id"))
            clauses.append("user_id = ?")

        if active_only:
            clauses.append("active = 1")

        row = await self.database.fetchone(
            f"""
            SELECT COUNT(*) AS c
            FROM {MUTES_TABLE}
            WHERE {' AND '.join(clauses)}
            """,
            tuple(params),
        )
        return int(row["c"]) if row else 0

    async def clear_mute(
        self,
        mute_id: int,
        *,
        cleared_by: int,
    ) -> ModerationMuteRecord:
        await self.initialize()

        mute_id = _positive_int(mute_id, "mute_id")
        cleared_by = _positive_int(cleared_by, "cleared_by")

        mute = await self.get_mute(mute_id)
        if mute is None:
            raise ModerationNotFoundError(f"Mute not found: {mute_id}")

        if not mute.active:
            return mute

        await self.database.execute(
            f"""
            UPDATE {MUTES_TABLE}
            SET
                active = 0,
                cleared_by = ?,
                cleared_at = ?
            WHERE id = ?
            """,
            (
                cleared_by,
                _utc_now(),
                mute_id,
            ),
        )

        updated = await self.get_mute(mute_id)
        if updated is None:
            raise ModerationServiceError("Cleared mute could not be reloaded.")

        await self._safe_audit(
            action="mute_cleared",
            guild_id=mute.guild_id,
            moderator_id=cleared_by,
            target_user_id=mute.user_id,
            reason=mute.reason,
            payload=updated.to_dict(),
        )

        return updated

    async def is_muted(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> bool:
        return (await self.count_mutes(guild_id=guild_id, user_id=user_id, active_only=True)) > 0

    # ========================================================
    # CHANNEL STATES
    # ========================================================

    async def set_channel_lock(
        self,
        *,
        guild_id: int,
        channel_id: int,
        locked: bool,
        moderator_id: int | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModerationChannelStateRecord:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        channel_id = _positive_int(channel_id, "channel_id")
        moderator_id = _coerce_optional_positive_int(moderator_id, "moderator_id")

        existing = await self.get_channel_state(
            guild_id=guild_id,
            channel_id=channel_id,
        )

        now = _utc_now()
        if existing is None:
            await self.database.execute(
                f"""
                INSERT INTO {CHANNEL_STATES_TABLE} (
                    guild_id,
                    channel_id,
                    locked,
                    slowmode_seconds,
                    moderator_id,
                    reason,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    1 if locked else 0,
                    0,
                    moderator_id,
                    _normalize_optional_text(reason, max_length=MAX_REASON_LENGTH),
                    now,
                    _serialize_payload(metadata),
                ),
            )
        else:
            await self.database.execute(
                f"""
                UPDATE {CHANNEL_STATES_TABLE}
                SET
                    locked = ?,
                    moderator_id = ?,
                    reason = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE guild_id = ? AND channel_id = ?
                """,
                (
                    1 if locked else 0,
                    moderator_id,
                    _normalize_optional_text(reason, max_length=MAX_REASON_LENGTH),
                    now,
                    _serialize_payload(metadata),
                    guild_id,
                    channel_id,
                ),
            )

        record = await self.get_channel_state(guild_id=guild_id, channel_id=channel_id)
        if record is None:
            raise ModerationServiceError("Channel state could not be reloaded.")

        await self._safe_audit(
            action="channel_locked" if locked else "channel_unlocked",
            guild_id=guild_id,
            moderator_id=moderator_id,
            target_channel_id=channel_id,
            reason=reason,
            payload=record.to_dict(),
        )

        return record

    async def set_channel_slowmode(
        self,
        *,
        guild_id: int,
        channel_id: int,
        slowmode_seconds: int,
        moderator_id: int | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModerationChannelStateRecord:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        channel_id = _positive_int(channel_id, "channel_id")
        slowmode_seconds = int(slowmode_seconds)
        if slowmode_seconds < 0:
            raise ModerationValidationError("slowmode_seconds cannot be negative.")

        moderator_id = _coerce_optional_positive_int(moderator_id, "moderator_id")

        existing = await self.get_channel_state(
            guild_id=guild_id,
            channel_id=channel_id,
        )

        now = _utc_now()
        if existing is None:
            await self.database.execute(
                f"""
                INSERT INTO {CHANNEL_STATES_TABLE} (
                    guild_id,
                    channel_id,
                    locked,
                    slowmode_seconds,
                    moderator_id,
                    reason,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    slowmode_seconds,
                    moderator_id,
                    _normalize_optional_text(reason, max_length=MAX_REASON_LENGTH),
                    now,
                    _serialize_payload(metadata),
                ),
            )
        else:
            await self.database.execute(
                f"""
                UPDATE {CHANNEL_STATES_TABLE}
                SET
                    slowmode_seconds = ?,
                    moderator_id = ?,
                    reason = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE guild_id = ? AND channel_id = ?
                """,
                (
                    slowmode_seconds,
                    moderator_id,
                    _normalize_optional_text(reason, max_length=MAX_REASON_LENGTH),
                    now,
                    _serialize_payload(metadata),
                    guild_id,
                    channel_id,
                ),
            )

        record = await self.get_channel_state(guild_id=guild_id, channel_id=channel_id)
        if record is None:
            raise ModerationServiceError("Channel state could not be reloaded.")

        await self._safe_audit(
            action="slowmode_set",
            guild_id=guild_id,
            moderator_id=moderator_id,
            target_channel_id=channel_id,
            reason=reason,
            payload=record.to_dict(),
        )

        return record

    async def get_channel_state(
        self,
        *,
        guild_id: int,
        channel_id: int,
    ) -> ModerationChannelStateRecord | None:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        channel_id = _positive_int(channel_id, "channel_id")

        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {CHANNEL_STATES_TABLE}
            WHERE guild_id = ? AND channel_id = ?
            LIMIT 1
            """,
            (guild_id, channel_id),
        )
        return ModerationChannelStateRecord.from_row(row) if row else None

    async def list_channel_states(
        self,
        *,
        guild_id: int,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ModerationChannelStateRecord]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {CHANNEL_STATES_TABLE}
            WHERE guild_id = ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )
        return [ModerationChannelStateRecord.from_row(row) for row in rows]

    # ========================================================
    # HISTORY / SUMMARY
    # ========================================================

    async def get_user_history(
        self,
        *,
        guild_id: int,
        user_id: int,
        limit: int = 50,
    ) -> ModerationUserHistory:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        user_id = _positive_int(user_id, "user_id")
        limit = max(1, min(int(limit), 100))

        warnings = await self.list_warnings(
            guild_id=guild_id,
            user_id=user_id,
            active_only=False,
            limit=limit,
            offset=0,
        )

        notes = await self.list_notes(
            guild_id=guild_id,
            user_id=user_id,
            active_only=False,
            limit=limit,
            offset=0,
        )

        mutes = await self.list_mutes(
            guild_id=guild_id,
            user_id=user_id,
            active_only=False,
            limit=limit,
            offset=0,
        )

        audits = await self.list_audit_logs(
            guild_id=guild_id,
            target_user_id=user_id,
            limit=limit,
            offset=0,
        )

        return ModerationUserHistory(
            guild_id=guild_id,
            user_id=user_id,
            warnings=warnings,
            notes=notes,
            mutes=mutes,
            audits=audits,
        )

    async def get_guild_summary(
        self,
        *,
        guild_id: int,
    ) -> dict[str, Any]:
        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")

        warnings_active = await self.count_warnings(guild_id=guild_id, active_only=True)
        warnings_all = await self.count_warnings(guild_id=guild_id, active_only=False)
        notes_active = await self.count_notes(guild_id=guild_id, active_only=True)
        mutes_active = await self.count_mutes(guild_id=guild_id, active_only=True)
        channels = await self.list_channel_states(guild_id=guild_id, limit=500, offset=0)

        return {
            "guild_id": guild_id,
            "warnings_active": warnings_active,
            "warnings_total": warnings_all,
            "notes_active": notes_active,
            "mutes_active": mutes_active,
            "channel_states": [item.to_dict() for item in channels],
        }

    # ========================================================
    # WEB PANEL FRIENDLY HELPERS
    # ========================================================

    async def search_user_records(
        self,
        *,
        guild_id: int,
        query: str,
        limit: int = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Web panel için düz arama çıktısı.
        """

        await self.initialize()

        guild_id = _positive_int(guild_id, "guild_id")
        query = query.strip()
        if not query:
            return {"warnings": [], "notes": [], "mutes": [], "audits": []}

        like = f"%{query}%"
        rows_warnings = await self.database.fetchall(
            f"""
            SELECT *
            FROM {WARNINGS_TABLE}
            WHERE guild_id = ?
              AND (
                CAST(user_id AS TEXT) LIKE ?
                OR CAST(moderator_id AS TEXT) LIKE ?
                OR LOWER(reason) LIKE LOWER(?)
                OR LOWER(COALESCE(note, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(roblox_username, '')) LIKE LOWER(?)
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, like, like, like, like, like, limit),
        )
        rows_notes = await self.database.fetchall(
            f"""
            SELECT *
            FROM {NOTES_TABLE}
            WHERE guild_id = ?
              AND (
                CAST(user_id AS TEXT) LIKE ?
                OR CAST(moderator_id AS TEXT) LIKE ?
                OR LOWER(note) LIKE LOWER(?)
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, like, like, like, limit),
        )
        rows_mutes = await self.database.fetchall(
            f"""
            SELECT *
            FROM {MUTES_TABLE}
            WHERE guild_id = ?
              AND (
                CAST(user_id AS TEXT) LIKE ?
                OR CAST(moderator_id AS TEXT) LIKE ?
                OR LOWER(reason) LIKE LOWER(?)
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, like, like, like, limit),
        )
        rows_audits = await self.database.fetchall(
            f"""
            SELECT *
            FROM {AUDIT_LOGS_TABLE}
            WHERE guild_id = ?
              AND (
                LOWER(action) LIKE LOWER(?)
                OR CAST(target_user_id AS TEXT) LIKE ?
                OR CAST(target_channel_id AS TEXT) LIKE ?
                OR LOWER(COALESCE(reason, '')) LIKE LOWER(?)
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, like, like, like, like, limit),
        )

        return {
            "warnings": [ModerationWarningRecord.from_row(row).to_dict() for row in rows_warnings],
            "notes": [ModerationNoteRecord.from_row(row).to_dict() for row in rows_notes],
            "mutes": [ModerationMuteRecord.from_row(row).to_dict() for row in rows_mutes],
            "audits": [ModerationAuditRecord.from_row(row).to_dict() for row in rows_audits],
        }

    # ========================================================
    # INTERNALS
    # ========================================================

    def _coerce_datetime(
        self,
        value: datetime | str | None,
    ) -> str | None:
        if value is None:
            return None

        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc).isoformat()

    async def _safe_audit(
        self,
        *,
        action: str,
        guild_id: int | None = None,
        moderator_id: int | None = None,
        target_user_id: int | None = None,
        target_channel_id: int | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "discord",
    ) -> None:
        try:
            await self.record_audit(
                action=action,
                guild_id=guild_id,
                moderator_id=moderator_id,
                target_user_id=target_user_id,
                target_channel_id=target_channel_id,
                reason=reason,
                payload=payload,
                source=source,
            )
        except Exception as error:
            self._log(
                logging.WARNING,
                "Audit record failed for action %s: %s",
                action,
                error,
            )

    def _log(
        self,
        level: int,
        message: str,
        *args: Any,
    ) -> None:
        if self.logger is not None:
            self.logger.log(level, message, *args)
