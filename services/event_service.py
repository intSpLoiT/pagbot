from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from core.database import Database
from utils.errors import PAGError


# ============================================================
# ERRORS
# ============================================================


class EventServiceError(PAGError):
    """
    Event Service temel hata sınıfı.
    """


class EventNotFoundError(EventServiceError):
    """
    Event bulunamadığında oluşur.
    """


class EventAlreadyExistsError(EventServiceError):
    """
    Aynı event tekrar oluşturulmaya çalışıldığında oluşur.
    """


class EventClosedError(EventServiceError):
    """
    Kapalı event üzerinde işlem yapılmaya çalışıldığında oluşur.
    """


class EventFullError(EventServiceError):
    """
    Event maksimum katılımcı sayısına ulaştığında oluşur.
    """


class AlreadyRegisteredError(EventServiceError):
    """
    Kullanıcı zaten event'e kayıtlıysa oluşur.
    """


class NotRegisteredError(EventServiceError):
    """
    Kullanıcı event'e kayıtlı değilse oluşur.
    """


# ============================================================
# ENUMS
# ============================================================


class EventStatus(StrEnum):
    """
    Event durumları.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    """
    Event türleri.

    Yeni event türleri daha sonra eklenebilir.
    """

    TRYOUT = "tryout"
    TOURNAMENT = "tournament"
    CHALLENGE = "challenge"
    COMMUNITY = "community"
    CUSTOM = "custom"


# ============================================================
# DATA MODEL
# ============================================================


@dataclass(slots=True, frozen=True)
class Event:
    """
    Event veri modeli.

    Görsel alanlar özellikle event mesajlarının
    daha etkileyici olabilmesi için tutulur.
    """

    id: int
    name: str
    description: str
    event_type: EventType
    status: EventStatus
    created_by: int

    start_time: datetime | None
    end_time: datetime | None

    max_participants: int | None

    image_url: str | None
    thumbnail_url: str | None

    created_at: datetime


@dataclass(slots=True, frozen=True)
class EventParticipant:
    """
    Event katılımcısı.
    """

    event_id: int
    user_id: int
    registered_at: datetime


# ============================================================
# EVENT SERVICE
# ============================================================


class EventService:
    """
    PAG Bot Event Service.

    Sorumlulukları:

    - Event oluşturmak
    - Event bulmak
    - Event listelemek
    - Event durumunu yönetmek
    - Katılımcı eklemek
    - Katılımcı çıkarmak
    - Katılımcıları listelemek
    - Event kapasitesini kontrol etmek

    Event'in Discord mesajını oluşturmaz.
    Event'in görselini kendi başına üretmez.

    Bunlar Cog / Embed katmanının sorumluluğudur.
    """

    def __init__(
        self,
        database: Database,
        logger: logging.Logger | None = None,
    ) -> None:

        self.database = database
        self.logger = logger

    # ========================================================
    # CREATE
    # ========================================================

    async def create_event(
        self,
        *,
        name: str,
        description: str,
        event_type: EventType,
        created_by: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_participants: int | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
    ) -> int:
        """
        Yeni event oluşturur.

        Event başlangıçta ACTIVE olarak oluşturulur.
        """

        name = name.strip()

        if not name:
            raise ValueError(
                "Event name cannot be empty."
            )

        if created_by <= 0:
            raise ValueError(
                "created_by must be a valid Discord ID."
            )

        if max_participants is not None:
            if max_participants <= 0:
                raise ValueError(
                    "max_participants must be positive."
                )

        now = self._utc_now()

        result = await self.database.execute(
            """
            INSERT INTO events (
                name,
                description,
                event_type,
                status,
                created_by,
                start_time,
                end_time,
                max_participants,
                image_url,
                thumbnail_url,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                event_type.value,
                EventStatus.ACTIVE.value,
                created_by,
                self._datetime_to_string(
                    start_time,
                ),
                self._datetime_to_string(
                    end_time,
                ),
                max_participants,
                image_url,
                thumbnail_url,
                self._datetime_to_string(
                    now,
                ),
            ),
        )

        await self.database.commit()

        event_id = int(
            result.lastrowid
        )

        self._log(
            logging.INFO,
            "Event created: %s (%s)",
            event_id,
            name,
        )

        return event_id

    # ========================================================
    # GET
    # ========================================================

    async def get_event(
        self,
        event_id: int,
    ) -> Event | None:
        """
        ID ile event getirir.
        """

        row = await self.database.fetchone(
            """
            SELECT
                id,
                name,
                description,
                event_type,
                status,
                created_by,
                start_time,
                end_time,
                max_participants,
                image_url,
                thumbnail_url,
                created_at
            FROM events
            WHERE id = ?
            """,
            (
                event_id,
            ),
        )

        if row is None:
            return None

        return self._row_to_event(
            row,
        )

    # ========================================================
    # REQUIRE EVENT
    # ========================================================

    async def require_event(
        self,
        event_id: int,
    ) -> Event:
        """
        Event bulunamazsa hata verir.
        """

        event = await self.get_event(
            event_id,
        )

        if event is None:
            raise EventNotFoundError(
                f"Event not found: {event_id}"
            )

        return event

    # ========================================================
    # ACTIVE EVENTS
    # ========================================================

    async def get_active_events(
        self,
        *,
        limit: int = 50,
    ) -> list[Event]:
        """
        Aktif eventleri getirir.
        """

        if limit <= 0:
            raise ValueError(
                "limit must be positive."
            )

        rows = await self.database.fetchall(
            """
            SELECT
                id,
                name,
                description,
                event_type,
                status,
                created_by,
                start_time,
                end_time,
                max_participants,
                image_url,
                thumbnail_url,
                created_at
            FROM events
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (
                EventStatus.ACTIVE.value,
                limit,
            ),
        )

        return [
            self._row_to_event(row)
            for row in rows
        ]

    # ========================================================
    # CHANGE STATUS
    # ========================================================

    async def set_status(
        self,
        event_id: int,
        status: EventStatus,
    ) -> None:
        """
        Event durumunu değiştirir.
        """

        await self.require_event(
            event_id,
        )

        await self.database.execute(
            """
            UPDATE events
            SET status = ?
            WHERE id = ?
            """,
            (
                status.value,
                event_id,
            ),
        )

        await self.database.commit()

        self._log(
            logging.INFO,
            "Event %s status changed to %s.",
            event_id,
            status.value,
        )

    # ========================================================
    # REGISTER
    # ========================================================

    async def register_user(
        self,
        event_id: int,
        user_id: int,
    ) -> None:
        """
        Kullanıcıyı event'e kaydeder.
        """

        event = await self.require_event(
            event_id,
        )

        if event.status != EventStatus.ACTIVE:
            raise EventClosedError(
                "This event is not active."
            )

        existing = await self.database.fetchone(
            """
            SELECT 1
            FROM event_participants
            WHERE event_id = ?
              AND user_id = ?
            LIMIT 1
            """,
            (
                event_id,
                user_id,
            ),
        )

        if existing is not None:
            raise AlreadyRegisteredError(
                "User is already registered."
            )

        if event.max_participants is not None:

            count_row = await self.database.fetchone(
                """
                SELECT COUNT(*)
                FROM event_participants
                WHERE event_id = ?
                """,
                (
                    event_id,
                ),
            )

            participant_count = int(
                count_row[0]
            )

            if (
                participant_count
                >= event.max_participants
            ):
                raise EventFullError(
                    "This event is full."
                )

        await self.database.execute(
            """
            INSERT INTO event_participants (
                event_id,
                user_id,
                registered_at
            )
            VALUES (?, ?, ?)
            """,
            (
                event_id,
                user_id,
                self._datetime_to_string(
                    self._utc_now(),
                ),
            ),
        )

        await self.database.commit()

        self._log(
            logging.INFO,
            "User %s registered for event %s.",
            user_id,
            event_id,
        )

    # ========================================================
    # UNREGISTER
    # ========================================================

    async def unregister_user(
        self,
        event_id: int,
        user_id: int,
    ) -> None:
        """
        Kullanıcıyı event'ten çıkarır.
        """

        result = await self.database.execute(
            """
            DELETE FROM event_participants
            WHERE event_id = ?
              AND user_id = ?
            """,
            (
                event_id,
                user_id,
            ),
        )

        await self.database.commit()

        if result.rowcount == 0:
            raise NotRegisteredError(
                "User is not registered for this event."
            )

        self._log(
            logging.INFO,
            "User %s left event %s.",
            user_id,
            event_id,
        )

    # ========================================================
    # PARTICIPANTS
    # ========================================================

    async def get_participants(
        self,
        event_id: int,
    ) -> list[EventParticipant]:
        """
        Event katılımcılarını getirir.
        """

        await self.require_event(
            event_id,
        )

        rows = await self.database.fetchall(
            """
            SELECT
                event_id,
                user_id,
                registered_at
            FROM event_participants
            WHERE event_id = ?
            ORDER BY registered_at ASC
            """,
            (
                event_id,
            ),
        )

        return [
            EventParticipant(
                event_id=int(
                    row[0]
                ),
                user_id=int(
                    row[1]
                ),
                registered_at=self._string_to_datetime(
                    row[2],
                ),
            )
            for row in rows
        ]

    # ========================================================
    # PARTICIPANT COUNT
    # ========================================================

    async def get_participant_count(
        self,
        event_id: int,
    ) -> int:
        """
        Katılımcı sayısını hızlıca getirir.
        """

        row = await self.database.fetchone(
            """
            SELECT COUNT(*)
            FROM event_participants
            WHERE event_id = ?
            """,
            (
                event_id,
            ),
        )

        return int(
            row[0]
        )

    # ========================================================
    # DELETE
    # ========================================================

    async def delete_event(
        self,
        event_id: int,
    ) -> None:
        """
        Event'i siler.

        Katılımcılar foreign key cascade ile
        otomatik temizlenebilir.
        """

        result = await self.database.execute(
            """
            DELETE FROM events
            WHERE id = ?
            """,
            (
                event_id,
            ),
        )

        await self.database.commit()

        if result.rowcount == 0:
            raise EventNotFoundError(
                f"Event not found: {event_id}"
            )

        self._log(
            logging.INFO,
            "Event deleted: %s",
            event_id,
        )

    # ========================================================
    # ROW PARSER
    # ========================================================

    @staticmethod
    def _row_to_event(
        row: Any,
    ) -> Event:
        """
        Database satırını Event modeline çevirir.
        """

        return Event(
            id=int(
                row[0]
            ),
            name=str(
                row[1]
            ),
            description=str(
                row[2]
            ),
            event_type=EventType(
                row[3]
            ),
            status=EventStatus(
                row[4]
            ),
            created_by=int(
                row[5]
            ),
            start_time=EventService._string_to_datetime(
                row[6],
            ),
            end_time=EventService._string_to_datetime(
                row[7],
            ),
            max_participants=(
                int(row[8])
                if row[8] is not None
                else None
            ),
            image_url=row[9],
            thumbnail_url=row[10],
            created_at=EventService._string_to_datetime(
                row[11],
            ),
        )

    # ========================================================
    # DATETIME
    # ========================================================

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(
            timezone.utc,
        )

    @staticmethod
    def _datetime_to_string(
        value: datetime | None,
    ) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            value = value.replace(
                tzinfo=timezone.utc,
            )

        return value.isoformat()

    @staticmethod
    def _string_to_datetime(
        value: str | None,
    ) -> datetime | None:
        if value is None:
            return None

        return datetime.fromisoformat(
            value,
        )

    # ========================================================
    # LOGGER
    # ========================================================

    def _log(
        self,
        level: int,
        message: str,
        *args: object,
    ) -> None:

        if self.logger is not None:
            self.logger.log(
                level,
                message,
                *args,
            )