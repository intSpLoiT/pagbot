from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Iterable

import discord

from core.database import Database
from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
    RobloxService,
)
from utils.errors import PAGError


# ============================================================
# ERRORS
# ============================================================


class BlacklistServiceError(PAGError):
    """
    Blacklist servisinde oluşan genel hata.
    """


class BlacklistNotFoundError(BlacklistServiceError):
    """
    Kayıt bulunamadığında oluşur.
    """


class BlacklistValidationError(BlacklistServiceError):
    """
    Girilen veri geçersiz olduğunda oluşur.
    """


class BlacklistConflictError(BlacklistServiceError):
    """
    Discord / Roblox eşleşmesinde çakışma olduğunda oluşur.
    """


class BlacklistLookupError(BlacklistServiceError):
    """
    Roblox / Discord hedefi çözümlenemediğinde oluşur.
    """


# ============================================================
# CONSTANTS
# ============================================================


BLACKLIST_TABLE_NAME = "blacklist"
MAX_REASON_LENGTH = 1000


# ============================================================
# DATA MODELS
# ============================================================


@dataclass(slots=True, frozen=True)
class BlacklistRecord:
    """
    Veritabanındaki blacklist satırının güçlü modeli.
    """

    id: int
    discord_id: int | None
    roblox_id: int | None
    roblox_username: str | None
    reason: str
    added_by: int
    created_at: str
    active: bool
    announcement_channel_id: int | None = None

    @classmethod
    def from_row(
        cls,
        row: Any,
    ) -> "BlacklistRecord":
        return cls(
            id=int(row["id"]),
            discord_id=(
                int(row["discord_id"])
                if row["discord_id"] is not None
                else None
            ),
            roblox_id=(
                int(row["roblox_id"])
                if row["roblox_id"] is not None
                else None
            ),
            roblox_username=(
                str(row["roblox_username"])
                if row["roblox_username"] is not None
                else None
            ),
            reason=str(row["reason"]),
            added_by=int(row["added_by"]),
            created_at=str(row["created_at"]),
            active=bool(row["active"]),
            announcement_channel_id=(
                int(row["announcement_channel_id"])
                if "announcement_channel_id" in row.keys()
                and row["announcement_channel_id"] is not None
                else None
            ),
        )


@dataclass(slots=True, frozen=True)
class BlacklistTarget:
    """
    Bir blacklist hedefi.
    """

    discord_id: int | None = None
    roblox_id: int | None = None
    roblox_username: str | None = None
    roblox_display_name: str | None = None
    avatar_url: str | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.discord_id is None
            and self.roblox_id is None
            and not self.roblox_username
        )


@dataclass(slots=True)
class BlacklistOperationResult:
    """
    Add / update / remove / enforcement sonucu.
    """

    success: bool
    action: str
    message: str
    record: BlacklistRecord | None = None
    target: BlacklistTarget | None = None
    kicked: bool = False
    kick_error: str | None = None
    announcement_channel_id: int | None = None
    public_embed: discord.Embed | None = None


# ============================================================
# SERVICE
# ============================================================


class BlacklistService:
    """
    Blacklist iş mantığı burada yaşar.

    Bu servis:
        - mevcut blacklist kayıtlarını bozmadan çalışır
        - yeni satır ekler
        - var olan satırı update eder
        - pasif kayıtları re-activate eder
        - Roblox hedefini çözümler
        - Discord join kontrolü yapar
        - announcement embed üretir
        - eski veriyi silmeden şema genişletir
    """

    def __init__(
        self,
        database: Database,
        *,
        roblox_service: RobloxService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.roblox_service = roblox_service
        self.logger = logger

        self._initialized = False
        self._lock = asyncio.Lock()

    # ========================================================
    # INITIALIZE
    # ========================================================

    async def initialize(self) -> None:
        """
        Şemayı güvenli şekilde hazırlar.

        Önemli:
        - tabloyu silmez
        - mevcut kayıtları silmez
        - sadece eksik kolonları ekler
        - index oluşturur
        """

        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            await self.database.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {BLACKLIST_TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id INTEGER UNIQUE,
                    roblox_id INTEGER UNIQUE,
                    roblox_username TEXT,
                    reason TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    announcement_channel_id INTEGER
                )
                """
            )

            await self._ensure_column(
                "announcement_channel_id",
                "INTEGER",
            )

            await self.database.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{BLACKLIST_TABLE_NAME}_active
                ON {BLACKLIST_TABLE_NAME}(active)
                """
            )

            await self.database.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{BLACKLIST_TABLE_NAME}_discord
                ON {BLACKLIST_TABLE_NAME}(discord_id)
                """
            )

            await self.database.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{BLACKLIST_TABLE_NAME}_roblox
                ON {BLACKLIST_TABLE_NAME}(roblox_id)
                """
            )

            await self.database.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{BLACKLIST_TABLE_NAME}_created
                ON {BLACKLIST_TABLE_NAME}(created_at)
                """
            )

            self._initialized = True

            self._log(
                logging.INFO,
                "Blacklist service initialized.",
            )

    async def _ensure_column(
        self,
        column_name: str,
        column_type: str,
    ) -> None:
        """
        Eski veriyi bozmadan kolon ekler.
        """

        rows = await self.database.fetchall(
            f"PRAGMA table_info({BLACKLIST_TABLE_NAME})",
            (),
        )
        existing_columns = {row["name"] for row in rows}

        if column_name in existing_columns:
            return

        try:
            await self.database.execute(
                f"""
                ALTER TABLE {BLACKLIST_TABLE_NAME}
                ADD COLUMN {column_name} {column_type}
                """
            )
        except Exception as error:
            self._log(
                logging.WARNING,
                "Could not add blacklist column %s: %s",
                column_name,
                error,
            )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    def normalize_reason(self, reason: str | None) -> str:
        if not reason:
            return "Sebep belirtilmedi."

        value = reason.strip()
        if not value:
            return "Sebep belirtilmedi."

        if len(value) > MAX_REASON_LENGTH:
            value = value[:MAX_REASON_LENGTH]

        return value

    def _parse_discord_id(self, value: str) -> int | None:
        raw = value.strip()
        if not raw:
            return None

        mention = re.fullmatch(r"<@!?(\d+)>", raw)
        if mention:
            return int(mention.group(1))

        if raw.isdigit():
            return int(raw)

        return None

    def _parse_roblox_username(self, value: str) -> str | None:
        raw = value.strip()
        if not raw:
            return None

        lowered = raw.lower()
        if lowered.startswith(("roblox:", "rbx:", "username:")):
            raw = raw.split(":", 1)[1].strip()

        if not raw:
            return None

        return raw

    # ========================================================
    # ROBLOX RESOLUTION
    # ========================================================

    async def resolve_roblox_target(
        self,
        username: str,
    ) -> BlacklistTarget:
        """
        Roblox username'dan kullanıcı bilgisi çözer.

        Bu metod:
            - Roblox user bulunmazsa hata verir
            - avatar başarısız olursa kullanıcıyı yine döndürür
        """

        if self.roblox_service is None:
            raise BlacklistLookupError(
                "RobloxService is not configured."
            )

        cleaned = username.strip()
        if not cleaned:
            raise BlacklistValidationError(
                "Roblox username cannot be empty."
            )

        try:
            user = await self.roblox_service.get_user_by_username(cleaned)
        except RobloxNotFoundError as error:
            raise BlacklistNotFoundError(
                f"Roblox user not found: {cleaned}"
            ) from error
        except RobloxAPIError as error:
            raise BlacklistLookupError(
                "Roblox API error while resolving username."
            ) from error

        avatar_url: str | None = None
        try:
            avatar = await self.roblox_service.get_avatar(user.id)
            avatar_url = avatar.image_url
        except (RobloxNotFoundError, RobloxAPIError):
            avatar_url = None
        except Exception as error:
            self._log(
                logging.WARNING,
                "Avatar lookup failed for Roblox user %s: %s",
                user.id,
                error,
            )

        return BlacklistTarget(
            roblox_id=user.id,
            roblox_username=user.name,
            roblox_display_name=user.display_name,
            avatar_url=avatar_url,
        )

    # ========================================================
    # ROW HELPERS
    # ========================================================

    @staticmethod
    def _row_is_active(row: Any) -> bool:
        return bool(row["active"])

    def _row_to_record(self, row: Any) -> BlacklistRecord:
        return BlacklistRecord.from_row(row)

    # ========================================================
    # LOOKUPS
    # ========================================================

    async def get_by_id(
        self,
        record_id: int,
    ) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE id = ?
            LIMIT 1
            """,
            (record_id,),
        )

        return self._row_to_record(row) if row else None

    async def get_active_by_discord_id(
        self,
        discord_id: int,
    ) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE discord_id = ? AND active = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (discord_id,),
        )

        return self._row_to_record(row) if row else None

    async def get_active_by_roblox_id(
        self,
        roblox_id: int,
    ) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE roblox_id = ? AND active = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (roblox_id,),
        )

        return self._row_to_record(row) if row else None

    async def get_active_by_roblox_username(
        self,
        roblox_username: str,
    ) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE roblox_username = ? AND active = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (roblox_username.strip(),),
        )

        return self._row_to_record(row) if row else None

    async def is_blacklisted(
        self,
        *,
        discord_id: int | None = None,
        roblox_id: int | None = None,
        roblox_username: str | None = None,
    ) -> bool:
        if discord_id is not None:
            record = await self.get_active_by_discord_id(discord_id)
            if record is not None:
                return True

        if roblox_id is not None:
            record = await self.get_active_by_roblox_id(roblox_id)
            if record is not None:
                return True

        if roblox_username:
            record = await self.get_active_by_roblox_username(roblox_username)
            if record is not None:
                return True

        return False

    async def list_active(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BlacklistRecord]:
        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE active = 1
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

        return [self._row_to_record(row) for row in rows]

    async def list_recent(
        self,
        *,
        limit: int = 20,
    ) -> list[BlacklistRecord]:
        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return [self._row_to_record(row) for row in rows]

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[BlacklistRecord]:
        """
        Discord ID, Roblox adı veya sebep içinde arama yapar.
        """

        q = query.strip()
        if not q:
            return []

        like = f"%{q}%"
        rows = await self.database.fetchall(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            WHERE
                CAST(discord_id AS TEXT) LIKE ?
                OR CAST(roblox_id AS TEXT) LIKE ?
                OR LOWER(COALESCE(roblox_username, '')) LIKE LOWER(?)
                OR LOWER(reason) LIKE LOWER(?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        )

        return [self._row_to_record(row) for row in rows]

    async def count_active(self) -> int:
        row = await self.database.fetchone(
            f"""
            SELECT COUNT(*) AS c
            FROM {BLACKLIST_TABLE_NAME}
            WHERE active = 1
            """,
            (),
        )

        return int(row["c"]) if row else 0

    # ========================================================
    # UPSERT
    # ========================================================

    async def upsert(
        self,
        *,
        added_by: int,
        reason: str,
        discord_id: int | None = None,
        roblox_id: int | None = None,
        roblox_username: str | None = None,
        announcement_channel_id: int | None = None,
        force_active: bool = True,
    ) -> BlacklistOperationResult:
        """
        Blacklist kaydı ekler veya mevcut kaydı günceller.

        Bu metod:
            - mevcut aktif satırı bozmadan update eder
            - pasif satır varsa re-activate eder
            - yoksa yeni satır açar
        """

        await self.initialize()

        clean_reason = self.normalize_reason(reason)
        if not clean_reason:
            raise BlacklistValidationError(
                "Reason cannot be empty."
            )

        if discord_id is None and roblox_id is None and not roblox_username:
            raise BlacklistValidationError(
                "At least one target must be provided."
            )

        normalized_username = (
            roblox_username.strip()
            if roblox_username
            else None
        )

        async with self._lock:
            active_record = await self._find_matching_active_record(
                discord_id=discord_id,
                roblox_id=roblox_id,
                roblox_username=normalized_username,
            )

            inactive_record = None
            if active_record is None:
                inactive_record = await self._find_matching_inactive_record(
                    discord_id=discord_id,
                    roblox_id=roblox_id,
                    roblox_username=normalized_username,
                )

            now = self._now()

            if active_record is not None:
                await self.database.execute(
                    f"""
                    UPDATE {BLACKLIST_TABLE_NAME}
                    SET
                        discord_id = ?,
                        roblox_id = ?,
                        roblox_username = ?,
                        reason = ?,
                        added_by = ?,
                        created_at = ?,
                        active = ?,
                        announcement_channel_id = ?
                    WHERE id = ?
                    """,
                    (
                        discord_id,
                        roblox_id,
                        normalized_username,
                        clean_reason,
                        added_by,
                        now,
                        1 if force_active else 0,
                        announcement_channel_id,
                        active_record.id,
                    ),
                )

                updated = await self.get_by_id(active_record.id)
                assert updated is not None

                return BlacklistOperationResult(
                    success=True,
                    action="updated",
                    message="✅ Blacklist kaydı güncellendi.",
                    record=updated,
                    target=BlacklistTarget(
                        discord_id=discord_id,
                        roblox_id=roblox_id,
                        roblox_username=normalized_username,
                    ),
                    announcement_channel_id=announcement_channel_id,
                )

            if inactive_record is not None:
                await self.database.execute(
                    f"""
                    UPDATE {BLACKLIST_TABLE_NAME}
                    SET
                        discord_id = ?,
                        roblox_id = ?,
                        roblox_username = ?,
                        reason = ?,
                        added_by = ?,
                        created_at = ?,
                        active = ?,
                        announcement_channel_id = ?
                    WHERE id = ?
                    """,
                    (
                        discord_id,
                        roblox_id,
                        normalized_username,
                        clean_reason,
                        added_by,
                        now,
                        1 if force_active else 0,
                        announcement_channel_id,
                        inactive_record.id,
                    ),
                )

                updated = await self.get_by_id(inactive_record.id)
                assert updated is not None

                return BlacklistOperationResult(
                    success=True,
                    action="reactivated" if force_active else "updated",
                    message="✅ Blacklist kaydı yeniden etkinleştirildi.",
                    record=updated,
                    target=BlacklistTarget(
                        discord_id=discord_id,
                        roblox_id=roblox_id,
                        roblox_username=normalized_username,
                    ),
                    announcement_channel_id=announcement_channel_id,
                )

            await self.database.execute(
                f"""
                INSERT INTO {BLACKLIST_TABLE_NAME} (
                    discord_id,
                    roblox_id,
                    roblox_username,
                    reason,
                    added_by,
                    created_at,
                    active,
                    announcement_channel_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discord_id,
                    roblox_id,
                    normalized_username,
                    clean_reason,
                    added_by,
                    now,
                    1 if force_active else 0,
                    announcement_channel_id,
                ),
            )

            created = await self._get_last_inserted_record()
            assert created is not None

            return BlacklistOperationResult(
                success=True,
                action="inserted",
                message="✅ Blacklist kaydı oluşturuldu.",
                record=created,
                target=BlacklistTarget(
                    discord_id=discord_id,
                    roblox_id=roblox_id,
                    roblox_username=normalized_username,
                ),
                announcement_channel_id=announcement_channel_id,
            )

    async def _find_matching_active_record(
        self,
        *,
        discord_id: int | None,
        roblox_id: int | None,
        roblox_username: str | None,
    ) -> BlacklistRecord | None:
        """
        Aynı hedefe ait aktif kayıt varsa onu döndürür.
        """

        candidates: list[BlacklistRecord] = []

        if discord_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE discord_id = ? AND active = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (discord_id,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if roblox_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE roblox_id = ? AND active = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (roblox_id,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if roblox_username is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE roblox_username = ? AND active = 1
                ORDER BY id DESC
                LIMIT 1
                """,
                (roblox_username,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if not candidates:
            return None

        # Aynı kayıt ise tamam; farklı kayıtlar varsa çakışma.
        unique_ids = {record.id for record in candidates}
        if len(unique_ids) > 1:
            raise BlacklistConflictError(
                "Conflicting active blacklist records found."
            )

        return candidates[0]

    async def _find_matching_inactive_record(
        self,
        *,
        discord_id: int | None,
        roblox_id: int | None,
        roblox_username: str | None,
    ) -> BlacklistRecord | None:
        candidates: list[BlacklistRecord] = []

        if discord_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE discord_id = ? AND active = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (discord_id,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if roblox_id is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE roblox_id = ? AND active = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (roblox_id,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if roblox_username is not None:
            row = await self.database.fetchone(
                f"""
                SELECT *
                FROM {BLACKLIST_TABLE_NAME}
                WHERE roblox_username = ? AND active = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (roblox_username,),
            )
            if row:
                candidates.append(self._row_to_record(row))

        if not candidates:
            return None

        unique_ids = {record.id for record in candidates}
        if len(unique_ids) > 1:
            raise BlacklistConflictError(
                "Conflicting inactive blacklist records found."
            )

        return candidates[0]

    async def _get_last_inserted_record(self) -> BlacklistRecord | None:
        row = await self.database.fetchone(
            f"""
            SELECT *
            FROM {BLACKLIST_TABLE_NAME}
            ORDER BY id DESC
            LIMIT 1
            """,
            (),
        )
        return self._row_to_record(row) if row else None

    # ========================================================
    # REMOVAL
    # ========================================================

    async def remove_by_id(
        self,
        record_id: int,
    ) -> BlacklistOperationResult:
        await self.initialize()

        record = await self.get_by_id(record_id)
        if record is None:
            raise BlacklistNotFoundError(
                f"Blacklist record not found: {record_id}"
            )

        if not record.active:
            return BlacklistOperationResult(
                success=True,
                action="already_inactive",
                message="✅ Kayıt zaten pasif.",
                record=record,
            )

        await self.database.execute(
            f"""
            UPDATE {BLACKLIST_TABLE_NAME}
            SET active = 0
            WHERE id = ?
            """,
            (record_id,),
        )

        updated = await self.get_by_id(record_id)
        assert updated is not None

        return BlacklistOperationResult(
            success=True,
            action="deactivated",
            message="✅ Blacklist kaydı kaldırıldı.",
            record=updated,
        )

    async def remove_by_text(
        self,
        target_text: str,
    ) -> BlacklistOperationResult:
        """
        Discord mention / ID / Roblox username ile siler.
        """

        raw = target_text.strip()
        if not raw:
            raise BlacklistValidationError(
                "Target text cannot be empty."
            )

        discord_id = self._parse_discord_id(raw)
        if discord_id is not None:
            record = await self.get_active_by_discord_id(discord_id)
            if record is None:
                raise BlacklistNotFoundError(
                    f"No active blacklist record found for Discord ID {discord_id}."
                )
            return await self.remove_by_id(record.id)

        roblox_username = self._parse_roblox_username(raw)
        if roblox_username:
            record = await self.get_active_by_roblox_username(roblox_username)
            if record is None:
                raise BlacklistNotFoundError(
                    f"No active blacklist record found for Roblox username {roblox_username}."
                )
            return await self.remove_by_id(record.id)

        raise BlacklistValidationError(
            "Target text could not be parsed."
        )

    async def deactivate_member_if_blacklisted(
        self,
        member: discord.Member,
        *,
        reason_prefix: str = "Blacklist",
    ) -> BlacklistOperationResult | None:
        """
        Discord üyeyi sunucudan join anında ya da manuel kontrolde çıkarır.

        Bu metod kayıt bulursa:
            - kick atar
            - mevcut kaydı bozmadan audit benzeri bir sonuç döndürür
        """

        await self.initialize()

        record = await self.get_active_by_discord_id(member.id)
        if record is None:
            return None

        kick_reason = f"{reason_prefix}: {record.reason[:450]}"

        try:
            await member.kick(reason=kick_reason)
        except discord.Forbidden as error:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Blacklist kaydı var ama kick yetkisi yok.",
                record=record,
                kicked=False,
                kick_error="Missing kick permissions.",
            ) from error
        except discord.HTTPException as error:
            return BlacklistOperationResult(
                success=False,
                action="kick_failed",
                message="❌ Kick işlemi sırasında Discord API hatası oluştu.",
                record=record,
                kicked=False,
                kick_error="Discord API error.",
            ) from error

        return BlacklistOperationResult(
            success=True,
            action="kicked",
            message="✅ Blacklisted kullanıcı sunucudan çıkarıldı.",
            record=record,
            kicked=True,
        )

    # ========================================================
    # ENFORCEMENT / JOIN CHECK
    # ========================================================

    async def should_kick_member(
        self,
        member: discord.Member,
    ) -> bool:
        record = await self.get_active_by_discord_id(member.id)
        return record is not None

    async def enforce_member_join(
        self,
        member: discord.Member,
    ) -> BlacklistOperationResult | None:
        """
        on_member_join içinde çağrılır.

        Kayıt varsa:
            - kick atar
            - sonuç döndürür
        """

        result = await self.deactivate_member_if_blacklisted(member)
        return result

    # ========================================================
    # EMBEDS
    # ========================================================

    def build_announcement_embed(
        self,
        record: BlacklistRecord,
        *,
        moderator_id: int,
        action: str,
        kicked: bool = False,
        kick_error: str | None = None,
    ) -> discord.Embed:
        """
        İşlem yapılan kanala gönderilecek duyuru embed'i.
        """

        action_title = {
            "inserted": "🚫 BLACKLIST UYGULANDI",
            "reactivated": "🚫 BLACKLIST YENİDEN ETKİN",
            "updated": "🚫 BLACKLIST GÜNCELLENDİ",
            "deactivated": "✅ BLACKLIST KALDIRILDI",
            "kicked": "🚫 BLACKLIST • OTO KICK",
        }.get(action, "🚫 BLACKLIST")

        embed = discord.Embed(
            title=action_title,
            description=(
                "Bu kullanıcı PAG blacklist sistemine işlendi."
                if record.active
                else "Bu kullanıcı blacklist sisteminden çıkarıldı."
            ),
            color=discord.Color.red() if record.active else discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

        if record.discord_id is not None:
            embed.add_field(
                name="Discord",
                value=f"<@{record.discord_id}>\n`{record.discord_id}`",
                inline=True,
            )

        if record.roblox_username is not None:
            embed.add_field(
                name="Roblox",
                value=(
                    f"**{record.roblox_username}**"
                    + (f"\n`{record.roblox_id}`" if record.roblox_id is not None else "")
                ),
                inline=True,
            )

        embed.add_field(
            name="Sebep",
            value=self._trim_embed_text(record.reason),
            inline=False,
        )

        embed.add_field(
            name="Admin",
            value=f"<@{moderator_id}>",
            inline=True,
        )

        embed.add_field(
            name="Durum",
            value="Aktif" if record.active else "Pasif",
            inline=True,
        )

        embed.add_field(
            name="Kayıt ID",
            value=f"`{record.id}`",
            inline=True,
        )

        if kicked:
            embed.add_field(
                name="Kick",
                value="Başarılı",
                inline=True,
            )

        if kick_error:
            embed.add_field(
                name="Kick Notu",
                value=self._trim_embed_text(kick_error),
                inline=False,
            )

        if record.announcement_channel_id is not None:
            embed.set_footer(
                text=f"İşlem kanalı: #{record.announcement_channel_id}",
            )

        return embed

    def build_join_notice_embed(
        self,
        record: BlacklistRecord,
        *,
        member_mention: str,
        guild_id: int,
    ) -> discord.Embed:
        """
        Join sırasında atılan kullanıcı için duyuru.
        """

        embed = discord.Embed(
            title="🚫 BLACKLIST • OTO KICK",
            description=(
                f"{member_mention} blacklist listesinde olduğu için sunucudan çıkarıldı."
            ),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Sebep",
            value=self._trim_embed_text(record.reason),
            inline=False,
        )

        embed.add_field(
            name="Kayıt ID",
            value=f"`{record.id}`",
            inline=True,
        )

        embed.add_field(
            name="Sunucu",
            value=f"`{guild_id}`",
            inline=True,
        )

        if record.announcement_channel_id is not None:
            embed.set_footer(
                text=f"İşlem kanalı: #{record.announcement_channel_id}",
            )

        return embed

    @staticmethod
    def _trim_embed_text(text: str, limit: int = 1024) -> str:
        value = text.strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    # ========================================================
    # PUBLIC CHANNEL HELPERS
    # ========================================================

    async def send_to_channel(
        self,
        channel_id: int | None,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> None:
        """
        Log / duyuru kanalına mesaj gönderir.
        Kanal yoksa sessizce geçer.
        """

        if channel_id is None:
            return

        channel = None

        try:
            channel = self._get_channel(channel_id)
        except Exception:
            channel = None

        if channel is None:
            return

        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=True,
                    roles=False,
                    replied_user=False,
                ),
            )
        except Exception as error:
            self._log(
                logging.WARNING,
                "Failed to send blacklist announcement to channel %s: %s",
                channel_id,
                error,
            )

    def _get_channel(
        self,
        channel_id: int,
    ) -> discord.abc.Messageable | None:
        if hasattr(self, "bot") and self.bot is not None:
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                return channel  # type: ignore[return-value]
        return None

    # ========================================================
    # UTILITIES
    # ========================================================

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _log(self, level: int, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.log(level, message, *args)