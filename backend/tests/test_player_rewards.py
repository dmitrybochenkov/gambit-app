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
from app.services.player_reward_service import (
    PlayerRewardAlreadyRedeemedTodayError,
    PlayerRewardService,
)
from app.services.result_service import ResultService
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
            build_player(telegram_id=None, display_name=f"Игрок {place}") for place in range(1, 6)
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

    await service.close_tournament(100, tournament_id, 1000)

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
        await PlayerRewardService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
        ).issue_prize_stack_bonuses_for_closed_tournament(
            session,
            tournament,
            issued_date=date(2026, 8, 22),
        )
        await session.commit()

        reward_count = len((await session.execute(select(PlayerReward))).scalars().all())

    assert reward_count == 3


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


async def _reward_session_factory(tmp_path: Path, filename: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / filename}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _inline_texts(markup: object) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def _reply_texts(markup: object) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]
