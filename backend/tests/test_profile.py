from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters.statistics import profile as profile_fmt
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.dto.rewards import PlayerRewardView
from app.services.dto.statistics.profile import PlayerProfileHonourView, PlayerProfileView
from app.services.profile_service import ProfileFutureSeasonError, ProfileKind, ProfileService


def profile_view(**overrides: object) -> PlayerProfileView:
    data = {
        "display_name": "Дима Боченков",
        "total_points": Decimal("0"),
        "knockouts_count": 0,
        "big_knockouts_count": 0,
        "tournaments_count": 0,
        "first_places_count": 0,
        "second_places_count": 0,
        "third_places_count": 0,
        "fourth_places_count": 0,
        "fifth_places_count": 0,
        "rating_position": None,
        "rating_participants_count": 0,
        "prize_percent": None,
        "honours": (),
    }
    data.update(overrides)
    return PlayerProfileView(**data)


def test_profile_formats_only_non_zero_prize_places() -> None:
    message = profile_fmt.message(
        "Твой профиль — за всё время",
        profile_view(
            first_places_count=3,
            third_places_count=5,
            fifth_places_count=4,
        ),
    )

    assert message == (
        "Твой профиль — за всё время\n"
        "⭐ - количество очков\n"
        "🎯 - процент попадания в пятерку лидеров\n"
        "🥊 - количество нокаутов\n"
        "🎲 - количество турниров\n\n"
        "Дима Боченков\n"
        "⭐ 0 | 🎯 — | 🥊 0 | 🎲 0\n\n"
        "Под кнопкой «Подробнее» можно посмотреть историю своих достижений\n\n"
        "Количество призовых мест:\n"
        "🥇 x3\n"
        "🥉 x5\n"
        "5️⃣ x4"
    )


def test_profile_formats_season_honours() -> None:
    message = profile_fmt.message(
        "Твой профиль — за всё время",
        profile_view(
            display_name="Дима",
            honours=(
                PlayerProfileHonourView(
                    season_name="Весна 2026",
                    season_starts_at=date(2026, 4, 1),
                    kind="champion",
                ),
                PlayerProfileHonourView(
                    season_name="Лето 2026",
                    season_starts_at=date(2026, 7, 1),
                    kind="knockout",
                ),
            ),
        ),
    )

    assert "Чемпионские титулы: 💍" in message
    assert "Лучший нокаутер: 💥" in message
    assert "Достижения:" not in message
    assert "💍 Победитель сезона «Весна 2026»" in message
    assert "💥 Лучший нокаутер сезона «Лето 2026»" in message


def test_profile_formats_champion_and_knockout_titles_separately() -> None:
    message = profile_fmt.message(
        "Твой профиль — за всё время",
        profile_view(
            display_name="Дима",
            knockouts_count=17,
            honours=(
                PlayerProfileHonourView(
                    season_name="Зима 2026",
                    season_starts_at=date(2026, 1, 1),
                    kind="champion",
                ),
                PlayerProfileHonourView(
                    season_name="Весна 2026",
                    season_starts_at=date(2026, 4, 1),
                    kind="knockout",
                ),
                PlayerProfileHonourView(
                    season_name="Лето 2026",
                    season_starts_at=date(2026, 7, 1),
                    kind="champion",
                ),
                PlayerProfileHonourView(
                    season_name="Осень 2026",
                    season_starts_at=date(2026, 10, 1),
                    kind="knockout",
                ),
            ),
        ),
    )

    assert "Чемпионские титулы: 💍💍" in message
    assert "Лучший нокаутер: 💥💥" in message
    assert "Достижения:" not in message
    assert "💍💥💍💥" not in message
    assert "🥊 17" in message


def test_profile_formats_points_as_rounded_integer() -> None:
    message = profile_fmt.message(
        "Твой профиль — за всё время",
        profile_view(
            display_name="Дима",
            total_points=Decimal("1347.5"),
            tournaments_count=1,
        ),
    )

    assert "⭐ 1348 | 🎯 — | 🥊 0 | 🎲 1" in message
    assert "1347.5" not in message


def test_profile_formats_active_prize_stack_rewards() -> None:
    message = profile_fmt.message(
        "Твой профиль — за всё время",
        profile_view(
            active_rewards=(
                PlayerRewardView(
                    reward_id=1,
                    player_id=10,
                    chips_amount=40_000,
                    source_place=1,
                    source_tournament_id=20,
                    source_tournament_date=date(2026, 8, 22),
                    source_tournament_name="Баунти турнир",
                    valid_through=date(2026, 8, 29),
                ),
            ),
        ),
    )

    assert "🎁 +40 000 фишек к первому стеку" in message
    assert "За 1 место — Баунти турнир, 22 августа 2026" in message
    assert "Действует до 29 августа 2026" in message


async def test_profile_filters_current_season_and_all_time(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        current_season = Season(
            name="Current season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        previous_season = Season(
            name="Previous season",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        player_without_results = build_player(
            telegram_id=200,
            display_name="King",
            status=UserStatus.ACTIVE,
        )
        session.add_all(
            [
                current_season,
                previous_season,
                player,
                player_without_results,
            ]
        )
        await session.flush()
        current_tournament = Tournament(
            season_id=current_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 8),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        previous_tournament = Tournament(
            season_id=previous_season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 6, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        active_tournament = Tournament(
            season_id=current_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                current_tournament,
                previous_tournament,
                active_tournament,
            ]
        )
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=player.id,
                    place=2,
                    knockouts_count=2,
                    big_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=10,
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("50"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=active_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=99,
                    big_knockouts_count=99,
                    tournament_points=Decimal("999"),
                    knockout_points=Decimal("999"),
                    bonus_points=999,
                ),
            ]
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        current_title, current_stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
        )
        all_time_title, all_time_stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.ALL_TIME,
        )
        _, empty_stats = await service.get_profile_for_player(
            telegram_id=200,
            kind=ProfileKind.CURRENT_SEASON,
        )

        assert current_title == "Твой профиль — текущий сезон"
        assert current_stats is not None
        assert current_stats.display_name == "Игрок Первый"
        assert current_stats.total_points == Decimal("100")
        assert current_stats.total_knockouts_count == 3
        assert current_stats.tournaments_count == 1
        assert current_stats.first_places_count == 0
        assert current_stats.second_places_count == 1

        assert all_time_title == "Твой профиль — за всё время"
        assert all_time_stats is not None
        assert all_time_stats.total_points == Decimal("150")
        assert all_time_stats.total_knockouts_count == 6
        assert all_time_stats.tournaments_count == 2
        assert all_time_stats.first_places_count == 1
        assert all_time_stats.second_places_count == 1

        assert empty_stats is not None
        assert empty_stats.display_name == "King"
        assert empty_stats.total_points == Decimal("0")
        assert empty_stats.tournaments_count == 0
        all_time_message = profile_fmt.message(
            all_time_title,
            all_time_stats,
        )
        empty_message = profile_fmt.message("Твой профиль — текущий сезон", empty_stats)
        assert "Количество призовых мест:" in all_time_message
        assert "🥇 x1" in all_time_message
        assert "🥈 x1" in all_time_message
        assert "🥉" not in all_time_message
        assert "4️⃣" not in all_time_message
        assert "5️⃣" not in all_time_message
        assert "Количество призовых мест:" not in empty_message
    finally:
        await engine.dispose()


async def test_profile_rating_position_and_prize_percent_use_scope(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile_position.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        target = build_player(telegram_id=100, display_name="Target", status=UserStatus.ACTIVE)
        leader = build_player(telegram_id=101, display_name="Leader", status=UserStatus.ACTIVE)
        zero = build_player(telegram_id=102, display_name="Zero", status=UserStatus.ACTIVE)
        session.add_all([season, target, leader, zero])
        await session.flush()
        tournaments = [
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 7, day),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            for day in range(1, 9)
        ]
        session.add_all(tournaments)
        await session.flush()
        session.add(
            TournamentResult(
                tournament_id=tournaments[0].id,
                player_id=leader.id,
                tournament_points=Decimal("200"),
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=target.id,
                    place=1 if index == 0 else None,
                    tournament_points=Decimal("10"),
                )
                for index, tournament in enumerate(tournaments)
            ]
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        _title, stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
            today=date(2026, 7, 10),
        )
        _zero_title, zero_stats = await service.get_profile_for_player(
            telegram_id=102,
            kind=ProfileKind.CURRENT_SEASON,
            today=date(2026, 7, 10),
        )

        assert stats is not None
        assert stats.rating_position == 2
        assert stats.rating_participants_count == 2
        assert stats.prize_percent == 13
        assert zero_stats is not None
        assert zero_stats.rating_position is None
        assert zero_stats.rating_participants_count == 2
        assert zero_stats.prize_percent is None
    finally:
        await engine.dispose()


async def test_profile_prize_tournaments_scope_order_and_labels(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile_prizes.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        current = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        previous = Season(
            name="Весна 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=date(2026, 6, 30),
        )
        player = build_player(telegram_id=100, display_name="Player", status=UserStatus.ACTIVE)
        other = build_player(telegram_id=101, display_name="Other", status=UserStatus.ACTIVE)
        session.add_all([current, previous, player, other])
        await session.flush()
        current_old = Tournament(
            season_id=current.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 3),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        current_new = Tournament(
            season_id=current.id,
            tournament_type_id=tournament_type_id("double_double"),
            date=date(2026, 7, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        active_prize = Tournament(
            season_id=current.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 11),
            status=TournamentStatus.ACTIVE,
        )
        previous_prize = Tournament(
            season_id=previous.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 6, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([current_old, current_new, active_prize, previous_prize])
        await session.flush()
        session.add_all(
            [
                TournamentResult(tournament_id=current_old.id, player_id=player.id, place=5),
                TournamentResult(tournament_id=current_new.id, player_id=player.id, place=1),
                TournamentResult(tournament_id=active_prize.id, player_id=player.id, place=2),
                TournamentResult(tournament_id=previous_prize.id, player_id=player.id, place=3),
                TournamentResult(tournament_id=current_new.id, player_id=other.id, place=2),
                TournamentResult(tournament_id=previous_prize.id, player_id=other.id),
            ]
        )
        await session.commit()
        previous_id = previous.id

    service = ProfileService(session_factory)
    try:
        current_prizes = await service.list_prize_tournaments_for_player(
            100,
            ProfileKind.CURRENT_SEASON,
            today=date(2026, 7, 15),
        )
        previous_prizes = await service.list_prize_tournaments_for_player(
            100,
            ProfileKind.SELECTED_SEASON,
            season_id=previous_id,
            today=date(2026, 7, 15),
        )
        all_time_prizes = await service.list_prize_tournaments_for_player(
            100,
            ProfileKind.ALL_TIME,
            today=date(2026, 7, 15),
        )

        assert [(item.date, item.display_name, item.place) for item in current_prizes] == [
            (date(2026, 7, 10), "Double", 1),
            (date(2026, 7, 3), "Classic", 5),
        ]
        assert [(item.date, item.display_name, item.place) for item in previous_prizes] == [
            (date(2026, 6, 20), "Bounty", 3)
        ]
        assert [item.date for item in all_time_prizes] == [
            date(2026, 7, 10),
            date(2026, 7, 3),
            date(2026, 6, 20),
        ]
    finally:
        await engine.dispose()


async def test_active_superadmin_can_open_profile_after_new_session(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_profile.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            build_player(
                telegram_id=100,
                display_name="Дима Боченков",
                status=UserStatus.ACTIVE,
                role=UserRole.SUPERADMIN,
            )
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        title, stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.ALL_TIME,
        )

        assert title == "Твой профиль — за всё время"
        assert stats is not None
        assert stats.display_name == "Дима Боченков"
        assert stats.tournaments_count == 0
    finally:
        await engine.dispose()


async def test_profile_current_season_switches_on_transition_date(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile_transition.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        old_season = Season(
            name="Old season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 8, 9),
        )
        future_season = Season(
            name="Future season",
            scoring_config_id=config.id,
            starts_at=date(2026, 8, 10),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        session.add_all([old_season, future_season, player])
        await session.flush()
        old_tournament = Tournament(
            season_id=old_season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 9),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        future_tournament = Tournament(
            season_id=future_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([old_tournament, future_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=old_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=1,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=future_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=0,
                    tournament_points=Decimal("200"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
            ]
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        _title, before_transition = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
            today=date(2026, 8, 9),
        )
        _title, on_transition = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
            today=date(2026, 8, 10),
        )

        assert before_transition is not None
        assert on_transition is not None
        assert before_transition.total_points == Decimal("100")
        assert on_transition.total_points == Decimal("200")
    finally:
        await engine.dispose()


async def test_profile_current_season_returns_empty_profile_without_current_season(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile_no_season.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            build_player(
                telegram_id=100,
                display_name="Игрок Первый",
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        title, stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
            today=date(2026, 8, 9),
        )

        assert title == "Твой профиль — текущий сезон"
        assert stats is not None
        assert stats.display_name == "Игрок Первый"
        assert stats.total_points == Decimal("0")
        assert stats.tournaments_count == 0
    finally:
        await engine.dispose()


async def test_profile_selected_season_and_picker_exclude_future(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile_selected.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        hidden = Season(
            name="Сезон 1",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 3, 31),
            is_statistics_visible=False,
        )
        completed = Season(
            name="Весна 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=date(2026, 6, 30),
        )
        current = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 8, 31),
        )
        future = Season(
            name="Осень 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
            ends_at=None,
        )
        player = build_player(telegram_id=100, display_name="Игрок")
        session.add_all([hidden, completed, current, future, player])
        await session.flush()
        hidden_tournament = Tournament(
            season_id=hidden.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 1, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        completed_tournament = Tournament(
            season_id=completed.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 4, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        current_tournament = Tournament(
            season_id=current.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([hidden_tournament, completed_tournament, current_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=hidden_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("50"),
                ),
                TournamentResult(
                    tournament_id=completed_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("100"),
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("200"),
                ),
            ]
        )
        await session.commit()
        completed_id = completed.id
        future_id = future.id

    service = ProfileService(session_factory)
    try:
        seasons = await service.list_profile_seasons(100, today=date(2026, 8, 10))
        title, stats = await service.get_profile_for_player(
            100,
            ProfileKind.SELECTED_SEASON,
            season_id=completed_id,
            today=date(2026, 8, 10),
        )
        _all_time_title, all_time_stats = await service.get_profile_for_player(
            100,
            ProfileKind.ALL_TIME,
            today=date(2026, 8, 10),
        )

        assert [season.name for season in seasons] == ["Лето 2026", "Весна 2026"]
        assert title == "Твой профиль — Весна 2026"
        assert stats is not None
        assert stats.total_points == Decimal("100")
        assert all_time_stats is not None
        assert all_time_stats.total_points == Decimal("350")
        with pytest.raises(ProfileFutureSeasonError):
            await service.get_profile_for_player(
                100,
                ProfileKind.SELECTED_SEASON,
                season_id=future_id,
                today=date(2026, 8, 10),
            )
    finally:
        await engine.dispose()
