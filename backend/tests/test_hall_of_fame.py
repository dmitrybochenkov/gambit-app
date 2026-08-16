from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import build_player
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters.statistics import hall_of_fame as hall_fmt
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import ScoringConfig, Season, SeasonHallOfFame
from app.db.models.enums import UserRole, UserStatus
from app.services.access_policy import AdminAccessDeniedError
from app.services.hall_of_fame_management_service import (
    HallOfFameManagementService,
    HallOfFamePhotoRole,
)
from app.services.user_statistics_service import UserStatisticsService


async def test_hall_of_fame_uses_manual_entries_from_completed_seasons(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        old_season = Season(
            name="Сезон 2025",
            scoring_config_id=config.id,
            starts_at=date(2025, 1, 1),
            ends_at=date(2025, 12, 31),
        )
        new_season = Season(
            name="Сезон 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        open_season = Season(
            name="Открытый сезон",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        future_ended_season = Season(
            name="Будущий финал",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        low_id = build_player(telegram_id=101, display_name="Иван")
        high_id = build_player(telegram_id=102, display_name="Петр")
        session.add_all(
            [old_season, new_season, open_season, future_ended_season, viewer, low_id, high_id]
        )
        await session.flush()
        session.add_all(
            [
                SeasonHallOfFame(
                    season_id=old_season.id,
                    champion_player_id=low_id.id,
                    knockout_player_id=high_id.id,
                    updated_by_user_id=viewer.id,
                ),
                SeasonHallOfFame(
                    season_id=new_season.id,
                    champion_player_id=high_id.id,
                    knockout_player_id=None,
                    updated_by_user_id=viewer.id,
                ),
                SeasonHallOfFame(
                    season_id=open_season.id,
                    champion_player_id=high_id.id,
                    knockout_player_id=high_id.id,
                    updated_by_user_id=viewer.id,
                ),
                SeasonHallOfFame(
                    season_id=future_ended_season.id,
                    champion_player_id=high_id.id,
                    knockout_player_id=high_id.id,
                    updated_by_user_id=viewer.id,
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        seasons = await service.get_hall_of_fame(100)

        assert [season.season_name for season in seasons] == ["Сезон 2026", "Сезон 2025"]
        assert seasons[0].champion_display_name == "Петр"
        assert seasons[0].knockout_leader_display_name is None
        assert seasons[1].champion_display_name == "Иван"
        assert seasons[1].knockout_leader_display_name == "Петр"
        assert "Открытый сезон" not in hall_fmt.message(seasons)
        assert "Будущий финал" not in hall_fmt.message(seasons)
        assert hall_fmt.message(seasons) == (
            "🏆 Зал славы\n\n💍 — победитель сезона\n💥 — лучший нокаутер сезона"
        )
        assert hall_fmt.season_caption(seasons[0]) == "Сезон 2026\n\n💍 Петр"
        assert hall_fmt.season_caption(seasons[1]) == "Сезон 2025\n\n💍 Иван\n💥 Петр"
    finally:
        await engine.dispose()


async def test_hall_of_fame_ignores_mathematical_winners_without_manual_entry(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall_math.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        completed = Season(
            name="Сезон без ручного ЗС",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        session.add_all([completed, viewer])
        await session.commit()

    service = UserStatisticsService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        assert await service.get_hall_of_fame(100) == []
    finally:
        await engine.dispose()


def test_hall_of_fame_empty_state() -> None:
    assert hall_fmt.message([]) == (
        "🏆 Зал славы\n\n"
        "💍 — победитель сезона\n"
        "💥 — лучший нокаутер сезона\n\n"
        "Пока нет заполненных сезонов в Зале славы."
    )


async def test_hall_of_fame_management_upserts_and_overwrites(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall_manage.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        completed = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 6, 1),
            ends_at=date(2026, 8, 31),
        )
        current = Season(
            name="Осень 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
            ends_at=None,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        admin = build_player(
            telegram_id=101,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        offline = build_player(telegram_id=102, display_name="Offline Player")
        offline.telegram_id = None
        champion = build_player(telegram_id=103, display_name="Champion")
        replacement = build_player(telegram_id=104, display_name="Replacement")
        session.add_all([completed, current, superadmin, admin, offline, champion, replacement])
        await session.commit()
        completed_id = completed.id
        current_id = current.id
        offline_id = offline.id
        champion_id = champion.id
        replacement_id = replacement.id
        superadmin_id = superadmin.id

    service = HallOfFameManagementService(
        session_factory,
        clock=FixedClock(datetime(2026, 9, 1, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        seasons = await service.list_completed_seasons(100)
        assert [season.season_name for season in seasons] == ["Лето 2026"]
        assert all(season.season_id != current_id for season in seasons)

        with pytest.raises(AdminAccessDeniedError):
            await service.list_completed_seasons(101)

        candidates = await service.search_players(100, "Offline")
        assert [candidate.user.id for candidate in candidates] == [offline_id]

        entry = await service.set_champion(100, completed_id, champion_id)
        assert entry.champion is not None
        assert entry.champion.id == champion_id
        assert entry.knockout_leader is None

        entry = await service.set_champion(100, completed_id, replacement_id)
        assert entry.champion is not None
        assert entry.champion.id == replacement_id

        entry = await service.set_knockout_player(100, completed_id, replacement_id)
        assert entry.champion is not None
        assert entry.knockout_leader is not None
        assert entry.champion.id == entry.knockout_leader.id == replacement_id

        entry = await service.set_photo(
            100,
            completed_id,
            role=HallOfFamePhotoRole.CHAMPION,
            telegram_file_id="champion-file-1",
            telegram_file_unique_id="champion-unique-1",
        )
        assert entry.champion_photo_file_id == "champion-file-1"
        assert entry.champion_photo_file_unique_id == "champion-unique-1"
        entry = await service.set_photo(
            100,
            completed_id,
            role=HallOfFamePhotoRole.CHAMPION,
            telegram_file_id="champion-file-2",
            telegram_file_unique_id="champion-unique-2",
        )
        assert entry.champion_photo_file_id == "champion-file-2"
        assert entry.champion_photo_file_unique_id == "champion-unique-2"
        entry = await service.set_photo(
            100,
            completed_id,
            role=HallOfFamePhotoRole.KNOCKOUT,
            telegram_file_id="knockout-file",
            telegram_file_unique_id="knockout-unique",
        )
        assert entry.knockout_photo_file_id == "knockout-file"
        assert entry.knockout_photo_file_unique_id == "knockout-unique"

        async with session_factory() as session:
            stored = await session.get(SeasonHallOfFame, 1)
            assert stored is not None
            assert stored.updated_by_user_id == superadmin_id
            assert stored.champion_photo_file_id == "champion-file-2"
            assert stored.champion_photo_file_unique_id == "champion-unique-2"
            assert stored.knockout_photo_file_id == "knockout-file"
            assert stored.knockout_photo_file_unique_id == "knockout-unique"
    finally:
        await engine.dispose()
