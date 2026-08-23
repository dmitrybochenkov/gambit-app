from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import check_in as check_in_fmt
from app.bot.telegram.keyboards.admin import check_in as admin_check_in_kb
from app.bot.telegram.keyboards.superadmin import panel as superadmin_panel_kb
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    Tournament,
    TournamentPhoto,
    TournamentResult,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserRole, UserStatus
from app.services.access_policy import AdminAccessDeniedError
from app.services.player_reward_service import (
    PlayerRewardAlreadyRedeemedTodayError,
    PlayerRewardService,
)
from app.services.result_fields import ResultField
from app.services.result_service import ResultPlayerAlreadyAddedError, ResultService
from app.services.tournament_check_in_service import TournamentCheckInService
from app.services.user_access_service import UserAccessService


async def test_close_tournament_issues_prize_stack_bonuses_once(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "issue.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=200 + place if place <= 3 else None,
                display_name=f"Игрок {place}",
            )
            for place in range(1, 6)
        ]
        session.add_all([season, admin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="photo",
                telegram_file_unique_id="photo-unique",
                uploaded_by_user_id=admin.id,
                position=0,
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=admin.id,
                    place=index,
                )
                for index, player in enumerate(players, start=1)
            ]
        )
        tournament_id = tournament.id
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    closed = await service.close_tournament(100, tournament_id, 1000)

    assert [
        (reward.source_place, reward.chips_amount) for reward in closed.newly_issued_rewards
    ] == [
        (1, 40_000),
        (2, 30_000),
        (3, 20_000),
    ]
    assert [reward.telegram_id for reward in closed.newly_issued_rewards] == [201, 202, 203]
    assert {reward.source_tournament_name for reward in closed.newly_issued_rewards} == {"Классика"}

    async with session_factory() as session:
        rewards = (
            await session.execute(select(PlayerReward).order_by(PlayerReward.source_place))
        ).scalars()
        rows = list(rewards)

    assert [(reward.source_place, reward.chips_amount) for reward in rows] == [
        (1, 40_000),
        (2, 30_000),
        (3, 20_000),
    ]
    assert [reward.valid_through for reward in rows] == [date(2026, 8, 29)] * 3

    async with session_factory() as session:
        tournament = await session.get(Tournament, tournament_id)
        assert tournament is not None
        repeated = await PlayerRewardService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
        ).issue_prize_stack_bonuses_for_closed_tournament(
            session,
            tournament,
            issued_date=date(2026, 8, 22),
        )
        await session.commit()

        reward_count = len((await session.execute(select(PlayerReward))).scalars().all())

    assert repeated == ()
    assert reward_count == 3


async def test_closed_tournament_correction_reconciles_rewards_and_preserves_validity(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-correction.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=200 + index,
                display_name=f"Игрок {index}",
                status=UserStatus.ACTIVE,
            )
            for index in range(1, 6)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="photo",
                telegram_file_unique_id="photo-unique",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players, start=1)
            ]
        )
        tournament_id = tournament.id
        player_ids = [player.id for player in players]
        await session.commit()

    close_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await close_service.close_tournament(100, tournament_id, 1000)

    correction_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 23, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    snapshot = await correction_service.get_closed_tournament_result_snapshot(100, tournament_id)
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[0],
        ResultField.PLACE,
        2,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[3],
        ResultField.PLACE,
        3,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[4],
        ResultField.PLACE,
        1,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[1],
        ResultField.PLACE,
        4,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[2],
        ResultField.PLACE,
        5,
    )
    result = await correction_service.finish_closed_tournament_correction(
        100,
        tournament_id,
        snapshot,
    )

    assert [(change.display_name, len(change.fields)) for change in result.result_changes] == [
        ("Игрок 1", 1),
        ("Игрок 2", 1),
        ("Игрок 3", 1),
        ("Игрок 4", 1),
        ("Игрок 5", 1),
    ]
    assert {
        change.display_name: (change.old_chips_amount, change.new_chips_amount)
        for change in result.reward_changes
    } == {
        "Игрок 1": (40_000, 30_000),
        "Игрок 2": (30_000, None),
        "Игрок 3": (20_000, None),
        "Игрок 4": (None, 20_000),
        "Игрок 5": (None, 40_000),
    }
    assert {notification.telegram_id for notification in result.player_notifications} == {
        201,
        202,
        203,
        204,
        205,
    }
    assert {notification.valid_through for notification in result.player_notifications} == {
        date(2026, 8, 29)
    }

    repeat = await correction_service.finish_closed_tournament_correction(
        100,
        tournament_id,
        ResultService.snapshot_from_results(
            await correction_service.get_closed_tournament_results(100, tournament_id)
        ),
    )
    assert repeat.result_changes == ()
    assert repeat.reward_changes == ()
    assert repeat.player_notifications == ()

    async with session_factory() as session:
        rewards = (
            await session.execute(select(PlayerReward).order_by(PlayerReward.player_id))
        ).scalars()
        rows = list(rewards)
    assert [(reward.player_id, reward.source_place, reward.chips_amount) for reward in rows] == [
        (player_ids[0], 2, 30_000),
        (player_ids[3], 3, 20_000),
        (player_ids[4], 1, 40_000),
    ]
    assert {reward.valid_through for reward in rows} == {date(2026, 8, 29)}


async def test_closed_tournament_correction_warns_about_redeemed_reward(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-correction-redeemed.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=210 + index,
                display_name=f"Игрок {index}",
                status=UserStatus.ACTIVE,
            )
            for index in range(1, 6)
        ]
        redemption_tournament = Tournament(
            season_id=1,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 23),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([season, superadmin, *players])
        await session.flush()
        redemption_tournament.season_id = season.id
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([tournament, redemption_tournament])
        await session.flush()
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="photo",
                telegram_file_unique_id="photo-unique",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players, start=1)
            ]
        )
        tournament_id = tournament.id
        redemption_tournament_id = redemption_tournament.id
        player_ids = [player.id for player in players]
        await session.commit()

    close_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await close_service.close_tournament(100, tournament_id, 1000)

    async with session_factory() as session:
        reward = (
            await session.execute(
                select(PlayerReward).where(PlayerReward.player_id == player_ids[0])
            )
        ).scalar_one()
        reward.redeemed_at = datetime(2026, 8, 23, 12, tzinfo=ZoneInfo("Europe/Moscow"))
        reward.redeemed_tournament_id = redemption_tournament_id
        reward.redeemed_by_user_id = player_ids[0]
        reward.redeemed_tournament_day = date(2026, 8, 23)
        await session.commit()

    correction_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 23, 13, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    snapshot = await correction_service.get_closed_tournament_result_snapshot(100, tournament_id)
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[0],
        ResultField.PLACE,
        2,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[4],
        ResultField.PLACE,
        1,
    )
    await correction_service.update_closed_tournament_result_field(
        100,
        tournament_id,
        player_ids[1],
        ResultField.PLACE,
        5,
    )
    result = await correction_service.finish_closed_tournament_correction(
        100,
        tournament_id,
        snapshot,
    )

    assert [
        (warning.player_id, warning.old_chips_amount, warning.new_chips_amount)
        for warning in result.used_reward_warnings
    ] == [(player_ids[0], 40_000, 30_000)]


async def test_closed_tournament_correction_requires_superadmin(tmp_path: Path) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-correction-access.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(
            telegram_id=200,
            display_name="Player",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentResult(
                tournament_id=tournament.id,
                player_id=player.id,
                source=TournamentResultSource.WALK_IN_EXISTING,
                checked_in_by_user_id=admin.id,
                place=1,
            )
        )
        tournament_id = tournament.id
        player_id = player.id
        await session.commit()

    service = ResultService(session_factory)

    with pytest.raises(AdminAccessDeniedError):
        await service.get_closed_tournament_results(100, tournament_id)
    with pytest.raises(AdminAccessDeniedError):
        await service.update_closed_tournament_result_field(
            100,
            tournament_id,
            player_id,
            ResultField.PLACE,
            2,
        )


async def test_closed_tournament_correction_replaces_player_and_preserves_result_data(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-replace-player.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        wrong = build_player(telegram_id=None, display_name="Wrong", status=UserStatus.ACTIVE)
        duplicate = build_player(
            telegram_id=None,
            display_name="Duplicate",
            status=UserStatus.ACTIVE,
        )
        correct = build_player(telegram_id=None, display_name="Correct", status=UserStatus.ACTIVE)
        session.add_all([season, superadmin, wrong, duplicate, correct])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=wrong.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=1,
                    knockouts_count=7,
                    big_knockouts_count=2,
                    bonus_points=5,
                    tournament_points=400,
                    knockout_points=90,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=duplicate.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=2,
                ),
            ]
        )
        tournament_id = tournament.id
        wrong_id = wrong.id
        duplicate_id = duplicate.id
        correct_id = correct.id
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 23, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    with pytest.raises(ResultPlayerAlreadyAddedError):
        await service.replace_closed_tournament_result_player(
            100,
            tournament_id,
            wrong_id,
            duplicate_id,
        )

    results = await service.replace_closed_tournament_result_player(
        100,
        tournament_id,
        wrong_id,
        correct_id,
    )
    replaced = ResultService.find_result_player(results, correct_id)
    assert replaced is not None
    assert replaced.place == 1
    assert replaced.knockouts_count == 7
    assert replaced.big_knockouts_count == 2
    assert replaced.bonus_points == 5
    assert ResultService.find_result_player(results, wrong_id) is None


async def test_closed_tournament_correction_player_replacement_moves_top_reward(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-replace-reward.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=200 + index,
                display_name=f"Игрок {index}",
                status=UserStatus.ACTIVE,
            )
            for index in range(1, 7)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 22),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="photo",
                telegram_file_unique_id="photo-unique",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players[:5], start=1)
            ]
        )
        tournament_id = tournament.id
        player_ids = [player.id for player in players]
        await session.commit()

    close_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await close_service.close_tournament(100, tournament_id, 1000)
    correction_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    snapshot = await correction_service.get_closed_tournament_result_snapshot(100, tournament_id)
    await correction_service.replace_closed_tournament_result_player(
        100,
        tournament_id,
        player_ids[0],
        player_ids[5],
    )

    result = await correction_service.finish_closed_tournament_correction(
        100,
        tournament_id,
        snapshot,
    )

    assert [
        (change.display_name, [(field.label, field.before, field.after) for field in change.fields])
        for change in result.result_changes
    ] == [("Игрок 6", [("Игрок", "Игрок 1", "Игрок 6")])]
    assert {
        change.display_name: (change.old_chips_amount, change.new_chips_amount)
        for change in result.reward_changes
    } == {
        "Игрок 1": (40_000, None),
        "Игрок 6": (None, 40_000),
    }

    async with session_factory() as session:
        rewards = (
            await session.execute(select(PlayerReward).order_by(PlayerReward.player_id))
        ).scalars()
        rows = list(rewards)
    assert [reward.player_id for reward in rows] == [
        player_ids[1],
        player_ids[2],
        player_ids[5],
    ]
    replacement_reward = next(reward for reward in rows if reward.player_id == player_ids[5])
    assert replacement_reward.source_place == 1
    assert replacement_reward.chips_amount == 40_000
    assert replacement_reward.valid_through == date(2026, 8, 29)


async def test_closed_tournament_correction_restores_original_lifecycle_without_rewards(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "closed-reward-lifecycle.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=None,
                display_name=f"Игрок {index}",
                status=UserStatus.ACTIVE,
            )
            for index in range(1, 7)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players[:5], start=1)
            ]
        )
        tournament_id = tournament.id
        player_ids = [player.id for player in players]
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    snapshot = await service.get_closed_tournament_result_snapshot(100, tournament_id)
    await service.replace_closed_tournament_result_player(
        100,
        tournament_id,
        player_ids[0],
        player_ids[5],
    )
    result = await service.finish_closed_tournament_correction(100, tournament_id, snapshot)

    assert {notification.valid_through for notification in result.player_notifications} == {
        date(2026, 8, 17)
    }
    async with session_factory() as session:
        rewards = (await session.execute(select(PlayerReward))).scalars().all()

    assert {reward.valid_through for reward in rewards} == {date(2026, 8, 17)}
    assert {reward.issued_at.date() for reward in rewards} == {date(2026, 8, 10)}
    assert all(
        reward.issued_at != datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Europe/Moscow"))
        for reward in rewards
    )


async def test_reward_expiration_is_inclusive_and_redemption_is_one_per_tournament_day(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "redeem.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(telegram_id=200, display_name="Player")
        session.add_all([season, admin, player])
        await session.flush()
        first_source = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 19),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        second_source = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        today = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 26),
            status=TournamentStatus.ACTIVE,
        )
        tomorrow = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 27),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([first_source, second_source, today, tomorrow])
        await session.flush()
        first = PlayerReward(
            player_id=player.id,
            chips_amount=40_000,
            source_tournament_id=first_source.id,
            source_place=1,
            issued_at=datetime(2026, 8, 19, 12, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 8, 26),
        )
        second = PlayerReward(
            player_id=player.id,
            chips_amount=30_000,
            source_tournament_id=second_source.id,
            source_place=2,
            issued_at=datetime(2026, 8, 20, 12, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 8, 27),
        )
        session.add_all([first, second])
        await session.flush()
        player_id = player.id
        first_id = first.id
        second_id = second.id
        today_id = today.id
        tomorrow_id = tomorrow.id
        await session.commit()

    service = PlayerRewardService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    active = await service.list_active_rewards_for_player(
        player_id=player_id,
        business_date=date(2026, 8, 26),
    )
    assert [reward.reward_id for reward in active] == [first_id, second_id]

    await service.redeem_reward(
        admin_telegram_id=100,
        tournament_id=today_id,
        reward_id=first_id,
    )
    active_after_first_redeem = await service.list_active_rewards_for_player(
        player_id=player_id,
        business_date=date(2026, 8, 26),
    )
    assert [reward.reward_id for reward in active_after_first_redeem] == [second_id]
    with pytest.raises(PlayerRewardAlreadyRedeemedTodayError):
        await service.redeem_reward(
            admin_telegram_id=100,
            tournament_id=today_id,
            reward_id=second_id,
        )

    next_day_service = PlayerRewardService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 27, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await next_day_service.redeem_reward(
        admin_telegram_id=100,
        tournament_id=tomorrow_id,
        reward_id=second_id,
    )

    expired = await next_day_service.list_active_rewards_for_player(
        player_id=player_id,
        business_date=date(2026, 8, 28),
    )
    assert expired == ()


async def test_check_in_returns_reward_without_redeeming_it(tmp_path: Path) -> None:
    session_factory = await _reward_session_factory(tmp_path, "check-in.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(telegram_id=200, display_name="Player")
        session.add_all([season, admin, player])
        await session.flush()
        source = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 19),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        today = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 26),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([source, today])
        await session.flush()
        reward = PlayerReward(
            player_id=player.id,
            chips_amount=40_000,
            source_tournament_id=source.id,
            source_place=1,
            issued_at=datetime(2026, 8, 19, 12, tzinfo=ZoneInfo("Europe/Moscow")),
            valid_through=date(2026, 8, 26),
        )
        session.add(reward)
        await session.flush()
        reward_id = reward.id
        today_id = today.id
        player_id = player.id
        await session.commit()

    result = await TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    ).check_in_existing_user(
        admin_telegram_id=100,
        tournament_id=today_id,
        user_id=player_id,
    )

    assert [reward.reward_id for reward in result.active_rewards] == [reward_id]
    async with session_factory() as session:
        stored_reward = await session.get(PlayerReward, reward_id)
        assert stored_reward is not None
        assert stored_reward.redeemed_at is None
        assert stored_reward.redeemed_tournament_id is None


def test_check_in_reward_decision_uses_reward_buttons() -> None:
    reward = SimpleNamespace(
        reward_id=11,
        chips_amount=40_000,
        valid_through=date(2026, 8, 29),
    )
    result = SimpleNamespace(
        user=SimpleNamespace(display_name="Дима"),
        active_rewards=(reward,),
    )

    text = check_in_fmt.reward_selection(result)
    keyboard = admin_check_in_kb.admin_check_in_reward_selection_keyboard(
        tournament_id=10,
        player_id=20,
        rewards=result.active_rewards,
    )

    assert "🎁 У игрока есть бонус:" in text
    assert "+40 000 фишек к первому стеку" in text
    assert _inline_texts(keyboard) == ["🎁 +40 000 · до 29.08", "Не использовать"]


async def test_superadmin_panel_counts_active_users_with_telegram_id(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "active-count.db")
    async with session_factory() as session:
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        active_admin = build_player(
            telegram_id=101,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        active_player = build_player(
            telegram_id=102,
            display_name="Player",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
        )
        no_telegram = build_player(
            telegram_id=None,
            display_name="No Telegram",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
        )
        blocked = build_player(
            telegram_id=103,
            display_name="Blocked",
            status=UserStatus.BLOCKED,
            role=UserRole.PLAYER,
        )
        session.add_all([superadmin, active_admin, active_player, no_telegram, blocked])
        await session.commit()

    panel = await UserAccessService(session_factory).get_superadmin_panel_for_superadmin(100)
    keyboard = superadmin_panel_kb.superadmin_panel_keyboard(panel.active_telegram_users_count)

    assert panel.active_telegram_users_count == 3
    assert _reply_texts(keyboard)[0] == "📝 Регистрации · 👤 3"


async def test_expiration_reminder_due_window_grouping_and_sent_mark(
    tmp_path: Path,
) -> None:
    session_factory = await _reward_session_factory(tmp_path, "reminders.db")
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 8, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        player = build_player(telegram_id=200, display_name="Player")
        other = build_player(telegram_id=201, display_name="Other")
        historical = build_player(telegram_id=None, display_name="Historical")
        session.add_all([season, player, other, historical])
        await session.flush()
        sources = [
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 8, 1 + index),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            for index in range(6)
        ]
        session.add_all(sources)
        await session.flush()
        rewards = [
            PlayerReward(
                player_id=player.id,
                chips_amount=40_000,
                source_tournament_id=sources[0].id,
                source_place=1,
                issued_at=datetime(2026, 8, 1, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 15),
            ),
            PlayerReward(
                player_id=player.id,
                chips_amount=20_000,
                source_tournament_id=sources[1].id,
                source_place=3,
                issued_at=datetime(2026, 8, 2, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 14),
            ),
            PlayerReward(
                player_id=other.id,
                chips_amount=30_000,
                source_tournament_id=sources[2].id,
                source_place=2,
                issued_at=datetime(2026, 8, 3, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 16),
            ),
            PlayerReward(
                player_id=other.id,
                chips_amount=40_000,
                source_tournament_id=sources[3].id,
                source_place=1,
                issued_at=datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 17),
            ),
            PlayerReward(
                player_id=historical.id,
                chips_amount=40_000,
                source_tournament_id=sources[4].id,
                source_place=1,
                issued_at=datetime(2026, 8, 5, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 15),
            ),
            PlayerReward(
                player_id=player.id,
                chips_amount=30_000,
                source_tournament_id=sources[5].id,
                source_place=2,
                issued_at=datetime(2026, 8, 6, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                valid_through=date(2026, 8, 10),
                redeemed_at=datetime(2026, 8, 7, 12, tzinfo=ZoneInfo("Europe/Moscow")),
                redeemed_tournament_id=sources[5].id,
                redeemed_by_user_id=player.id,
                redeemed_tournament_day=date(2026, 8, 7),
            ),
        ]
        session.add_all(rewards)
        await session.flush()
        player_id = player.id
        player_due_ids = (rewards[1].id, rewards[0].id)
        future_ids = (rewards[2].id, rewards[3].id)
        await session.commit()

    service = PlayerRewardService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 11, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    groups = await service.list_due_expiration_reminder_groups(business_date=date(2026, 8, 11))

    assert [(group.player_id, group.telegram_id) for group in groups] == [(player_id, 200)]
    assert [reward.reward_id for reward in groups[0].rewards] == list(player_due_ids)

    marked = await service.mark_expiration_reminders_sent(
        reward_ids=player_due_ids,
        business_date=date(2026, 8, 11),
    )

    assert marked == 2
    assert (
        await service.list_due_expiration_reminder_groups(business_date=date(2026, 8, 11))
    ) == ()
    catch_up = await service.list_due_expiration_reminder_groups(business_date=date(2026, 8, 13))
    assert [reward.reward_id for reward in catch_up[0].rewards] == list(future_ids)
    assert (
        await service.list_due_expiration_reminder_groups(business_date=date(2026, 8, 18))
    ) == ()


async def _reward_session_factory(tmp_path: Path, filename: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / filename}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _inline_texts(markup: object) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def _reply_texts(markup: object) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]
