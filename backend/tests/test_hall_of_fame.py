from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import ACHIEVEMENT_TYPES, build_player, seed_achievement_types_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters.statistics import hall_of_fame as hall_fmt
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    HallOfFameAchievement,
    HallOfFamePhoto,
    ScoringConfig,
    Season,
)
from app.db.models.enums import HallOfFameAchievementKind, UserRole, UserStatus
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.statistics.hall_of_fame import (
    HallOfFameAchievementView,
    HallOfFameSeasonView,
)
from app.services.hall_of_fame_management_service import (
    HallOfFameAchievementNotFoundError,
    HallOfFameManagementService,
    HallOfFameSeasonNotFoundError,
)
from app.services.user_common import UserNotFoundError
from app.services.user_statistics_service import UserStatisticsService


async def test_hall_of_fame_uses_manual_entries_from_completed_seasons(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed_achievement_types_async(session)
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
                HallOfFameAchievement(
                    season_id=old_season.id,
                    player_id=low_id.id,
                    kind=HallOfFameAchievementKind.RATING_WINNER,
                    awarded_at=old_season.ends_at,
                ),
                HallOfFameAchievement(
                    season_id=old_season.id,
                    player_id=high_id.id,
                    kind=HallOfFameAchievementKind.KO_RATING_WINNER,
                    awarded_at=old_season.ends_at,
                ),
                HallOfFameAchievement(
                    season_id=new_season.id,
                    player_id=high_id.id,
                    kind=HallOfFameAchievementKind.RATING_WINNER,
                    awarded_at=new_season.ends_at,
                ),
                HallOfFameAchievement(
                    season_id=open_season.id,
                    player_id=high_id.id,
                    kind=HallOfFameAchievementKind.GRAND_MONTH,
                    awarded_at=open_season.starts_at,
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

        assert [season.season_name for season in seasons] == [
            "Открытый сезон",
            "Сезон 2026",
            "Сезон 2025",
        ]
        assert seasons[1].champion_display_name == "Петр"
        assert seasons[1].knockout_leader_display_name is None
        assert seasons[2].champion_display_name == "Иван"
        assert seasons[2].knockout_leader_display_name == "Петр"
        assert "Будущий финал" not in hall_fmt.message(seasons)
        assert hall_fmt.message(seasons) == (
            "🏆 Зал славы\n\n"
            "💍 - победитель рейтингового сезона\n"
            "💥 - лучший нокаутер сезона\n"
            "🏅 - победитель Grand Month"
        )
        assert hall_fmt.season_caption(seasons[0]) == ("Открытый сезон\n🏅 Петр (01.07.2026)")
        assert hall_fmt.season_caption(seasons[1]) == "Сезон 2026\n💍 Петр"
        assert hall_fmt.season_caption(seasons[2]) == "Сезон 2025\n💍 Иван\n💥 Петр"
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
    assert hall_fmt.message([]) == "🏆 Зал славы\n\nПока нет заполненных сезонов в Зале славы."


def test_hall_of_fame_formatter_preserves_occurrence_order_and_repetitions() -> None:
    achievements = tuple(
        HallOfFameAchievementView(
            id=index,
            player_id=index,
            display_name=name,
            kind=kind,
            awarded_at=awarded_at,
            title=ACHIEVEMENT_TYPES[kind][0],
            emoji=ACHIEVEMENT_TYPES[kind][1],
        )
        for index, (kind, name, awarded_at) in enumerate(
            (
                (
                    HallOfFameAchievementKind.GRAND_KNOCKOUT,
                    "KO new",
                    date(2026, 8, 20),
                ),
                (HallOfFameAchievementKind.GRAND_MONTH, "Month new", date(2026, 8, 1)),
                (HallOfFameAchievementKind.RATING_WINNER, "Rating", date(2026, 8, 31)),
                (HallOfFameAchievementKind.GRAND_SEASON, "Season", date(2026, 8, 31)),
                (HallOfFameAchievementKind.KO_RATING_WINNER, "KO", date(2026, 8, 31)),
                (HallOfFameAchievementKind.GRAND_MONTH, "Month old", date(2026, 7, 1)),
                (HallOfFameAchievementKind.GRAND_KNOCKOUT, "KO old", date(2026, 6, 20)),
            ),
            start=1,
        )
    )
    season = HallOfFameSeasonView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        champion_player_id=1,
        champion_display_name="Rating",
        knockout_leader_player_id=2,
        knockout_leader_display_name="KO",
        ends_at=date(2026, 8, 31),
        achievements=achievements,
    )

    assert hall_fmt.season_caption(season) == (
        "Лето 2026\n🥊 KO new (20.08.2026)\n🏅 Month new (01.08.2026)\n"
        "💍 Rating\n🏆 Season\n💥 KO\n🏅 Month old (01.07.2026)\n"
        "🥊 KO old (20.06.2026)"
    )

    legend = hall_fmt.message([season])
    assert legend == (
        "🏆 Зал славы\n\n"
        "💍 - победитель рейтингового сезона\n"
        "💥 - лучший нокаутер сезона\n"
        "🏆 - победитель Grand Season\n"
        "🏅 - победитель Grand Month\n"
        "🥊 - победитель Grand Knockout"
    )
    assert " — " not in legend
    assert achievements[3].title == "Победитель Grand Season"


async def test_hall_of_fame_management_crud_preserves_repeated_occurrences(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall_manage.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed_achievement_types_async(session)
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

    service = HallOfFameManagementService(
        session_factory,
        clock=FixedClock(datetime(2026, 9, 1, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        seasons = await service.list_seasons(100)
        assert [season.season_name for season in seasons] == ["Осень 2026", "Лето 2026"]
        assert any(season.season_id == current_id for season in seasons)

        with pytest.raises(AdminAccessDeniedError):
            await service.list_seasons(101)
        with pytest.raises(AdminAccessDeniedError):
            await service.add_achievement(
                101,
                completed_id,
                champion_id,
                HallOfFameAchievementKind.RATING_WINNER,
                date(2026, 8, 31),
            )
        with pytest.raises(HallOfFameSeasonNotFoundError):
            await service.add_achievement(
                100,
                999,
                champion_id,
                HallOfFameAchievementKind.RATING_WINNER,
                date(2026, 8, 31),
            )
        with pytest.raises(UserNotFoundError):
            await service.add_achievement(
                100,
                completed_id,
                999,
                HallOfFameAchievementKind.RATING_WINNER,
                date(2026, 8, 31),
            )

        candidates = await service.search_players(100, "Offline")
        assert [candidate.user.id for candidate in candidates] == [offline_id]

        for kind in (
            HallOfFameAchievementKind.RATING_WINNER,
            HallOfFameAchievementKind.KO_RATING_WINNER,
            HallOfFameAchievementKind.GRAND_SEASON,
        ):
            first = await service.set_achievement(
                100, completed_id, champion_id, kind, date(2026, 8, 31)
            )
            original = next(item for item in first.achievements if item.kind == kind)
            replaced = await service.set_achievement(
                100, completed_id, replacement_id, kind, date(2026, 9, 1)
            )
            matching = [item for item in replaced.achievements if item.kind == kind]
            assert len(matching) == 1
            assert matching[0].id == original.id
            assert matching[0].player.id == replacement_id
            assert matching[0].awarded_at == date(2026, 9, 1)

        repeated = await service.add_achievement(
            100,
            completed_id,
            champion_id,
            HallOfFameAchievementKind.GRAND_MONTH,
            date(2026, 7, 1),
        )
        repeated = await service.add_achievement(
            100,
            completed_id,
            champion_id,
            HallOfFameAchievementKind.GRAND_MONTH,
            date(2026, 8, 1),
        )
        grand_months = [
            item
            for item in repeated.achievements
            if item.kind == HallOfFameAchievementKind.GRAND_MONTH
        ]
        assert [item.awarded_at for item in grand_months] == [
            date(2026, 8, 1),
            date(2026, 7, 1),
        ]
        with pytest.raises(HallOfFameAchievementNotFoundError):
            await service.delete_achievement(100, current_id, grand_months[0].id)
        entry = await service.delete_achievement(100, completed_id, grand_months[0].id)
        remaining_grand_months = [
            item
            for item in entry.achievements
            if item.kind == HallOfFameAchievementKind.GRAND_MONTH
        ]
        assert [item.id for item in remaining_grand_months] == [grand_months[1].id]
        for kind in (
            HallOfFameAchievementKind.GRAND_KNOCKOUT,
            HallOfFameAchievementKind.GRAND_KNOCKOUT,
        ):
            entry = await service.add_achievement(
                100,
                completed_id,
                replacement_id,
                kind,
                date(2026, 8, 20),
            )
        grand_knockouts = [
            item
            for item in entry.achievements
            if item.kind == HallOfFameAchievementKind.GRAND_KNOCKOUT
        ]
        assert len(grand_knockouts) == 2
        assert len({item.id for item in grand_knockouts}) == 2

        open_entry = await service.add_achievement(
            100,
            current_id,
            champion_id,
            HallOfFameAchievementKind.GRAND_MONTH,
            date(2026, 9, 1),
        )
        assert open_entry.achievements[0].player.id == champion_id

        entry = await service.add_photo(
            100,
            completed_id,
            telegram_file_id="champion-file-1",
            telegram_file_unique_id="champion-unique-1",
        )
        entry = await service.add_photo(
            100,
            completed_id,
            telegram_file_id="champion-file-2",
            telegram_file_unique_id="champion-unique-2",
        )
        entry = await service.add_photo(
            100,
            completed_id,
            telegram_file_id="knockout-file",
            telegram_file_unique_id="knockout-unique",
        )
        assert [photo.telegram_file_id for photo in entry.photos] == [
            "champion-file-1",
            "champion-file-2",
            "knockout-file",
        ]
        entry = await service.delete_all_photos(100, completed_id)
        assert entry.photos == ()

        async with session_factory() as session:
            assert (await session.execute(select(HallOfFamePhoto))).scalars().all() == []
    finally:
        await engine.dispose()
