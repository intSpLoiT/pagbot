import asyncio
import tempfile
from pathlib import Path

from core.database import Database
from core.migrations import MigrationManager
from services.event_service import (
    EventService,
    EventType,
)


async def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:

        database_path = (
            Path(temp_dir)
            / "test.db"
        )

        database = Database(
            database_path,
        )

        await database.connect()

        migrations = MigrationManager(
            database,
        )

        await migrations.run()

        event_service = EventService(
            database,
        )

        event_id = (
            await event_service.create_event(
                name="PAG Test Tryout",
                description=(
                    "Database test event."
                ),
                event_type=EventType.TRYOUT,
                created_by=123456789,
                max_participants=10,
                image_url=(
                    "https://example.com/image.png"
                ),
            )
        )

        print(
            "Created event:",
            event_id,
        )

        event = (
            await event_service.get_event(
                event_id,
            )
        )

        assert event is not None

        print(
            "Event found:",
            event.name,
        )

        await event_service.register_user(
            event_id,
            987654321,
        )

        print(
            "User registered.",
        )

        count = (
            await event_service
            .get_participant_count(
                event_id,
            )
        )

        assert count == 1

        print(
            "Participant count:",
            count,
        )

        participants = (
            await event_service
            .get_participants(
                event_id,
            )
        )

        assert len(
            participants
        ) == 1

        print(
            "Participants loaded.",
        )

        await event_service.unregister_user(
            event_id,
            987654321,
        )

        print(
            "User unregistered.",
        )

        await event_service.delete_event(
            event_id,
        )

        deleted_event = (
            await event_service.get_event(
                event_id,
            )
        )

        assert deleted_event is None

        print(
            "Event deleted.",
        )

        await database.close()

        print(
            "\nALL TESTS PASSED"
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )