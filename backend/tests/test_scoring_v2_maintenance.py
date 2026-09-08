import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import (
    build_player,
    seed_tournament_configs_async,
    seed_tournament_rules_async,
    seed_tournament_types_async,
    tournament_type_id,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import PlayerRewardType, TournamentStatus, UserRole, UserStatus

CREATE_WEEK_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / ("create_september_2026_tournaments.py")
)
create_week_spec = importlib.util.spec_from_file_location(
    "create_week_maintenance", CREATE_WEEK_SCRIPT
)
assert create_week_spec is not None
assert create_week_spec.loader is not None
create_week = importlib.util.module_from_spec(create_week_spec)
sys.modules[create_week_spec.name] = create_week
create_week_spec.loader.exec_module(create_week)

RECALC_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / ("recalculate_september_2026_points.py")
)
recalc_spec = importlib.util.spec_from_file_location("recalc_points_maintenance", RECALC_SCRIPT)
assert recalc_spec is not None
assert recalc_spec.loader is not None
recalc_points = importlib.util.module_from_spec(recalc_spec)
sys.modules[recalc_spec.name] = recalc_points
recalc_spec.loader.exec_module(recalc_points)


async def create_session_factory(database_path: Path) -> tuple[async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def seed_scoring_v2_data(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        v1 = ScoringConfig()
        v2 = ScoringConfig(
            place_1_coefficient=Decimal("0.45"),
            place_2_coefficient=Decimal("0.30"),
            place_3_coefficient=Decimal("0.20"),
            place_4_coefficient=Decimal("0.15"),
            place_5_coefficient=Decimal("0.10"),
            knockout_small_points=15,
            knockout_big_points=60,
            knockout_main_points=30,
            knockout_main_final_points=100,
        )
        session.add_all([v1, v2])
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        await seed_tournament_rules_async(session)
        session.add(
            Season(
                name="Осень 2026",
                scoring_config_id=v2.id,
                starts_at=date(2026, 9, 1),
                ends_at=None,
            )
        )
        session.add(
            build_player(
                telegram_id=100,
                display_name="Superadmin",
                status=UserStatus.ACTIVE,
                role=UserRole.SUPERADMIN,
            )
        )
        session.add(
            build_player(
                telegram_id=200,
                display_name="Player",
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()


async def test_create_week_dry_run_does_not_create_tournaments(tmp_path: Path) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "week-dry-run.db")
    try:
        await seed_scoring_v2_data(session_factory)
        async with session_factory() as session:
            plan = await create_week.build_plan(session)
            assert [item.action for item in plan] == ["create"] * 5

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())
        assert tournaments == []
    finally:
        await engine.dispose()


async def test_create_week_apply_is_idempotent_and_uses_season_scoring_config(
    tmp_path: Path,
) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "week-apply.db")
    try:
        await seed_scoring_v2_data(session_factory)
        async with session_factory() as session:
            plan = await create_week.build_plan(session)
            await create_week.apply_plan(session, plan)
            await session.commit()

        async with session_factory() as session:
            tournaments = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
            assert [
                (item.date, item.tournament_type_id, item.tournament_fund) for item in tournaments
            ] == [
                (date(2026, 9, 9), tournament_type_id("bounty_v3"), None),
                (date(2026, 9, 10), tournament_type_id("classic_v3"), None),
                (date(2026, 9, 11), tournament_type_id("deep_stack_v2"), None),
                (date(2026, 9, 12), tournament_type_id("freezeout_v2"), 2000),
                (date(2026, 9, 13), tournament_type_id("main_ko"), None),
            ]
            season = (await session.execute(select(Season))).scalar_one()
            assert {item.scoring_config_id for item in tournaments} == {season.scoring_config_id}

        async with session_factory() as session:
            second_plan = await create_week.build_plan(session)
            assert [item.action for item in second_plan] == ["unchanged"] * 5
    finally:
        await engine.dispose()


async def test_create_week_conflict_blocks_apply_without_partial_rows(tmp_path: Path) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "week-conflict.db")
    try:
        await seed_scoring_v2_data(session_factory)
        async with session_factory() as session:
            season = (await session.execute(select(Season))).scalar_one()
            session.add(
                Tournament(
                    season_id=season.id,
                    scoring_config_id=season.scoring_config_id,
                    tournament_type_id=tournament_type_id("classic_v3"),
                    date=date(2026, 9, 9),
                    status=TournamentStatus.ACTIVE,
                    registration_open=False,
                )
            )
            await session.commit()

        async with session_factory() as session:
            plan = await create_week.build_plan(session)
            assert plan[0].action == "conflict"
            assert create_week.has_conflicts(plan)
    finally:
        await engine.dispose()


async def seed_recalculation_data(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        v1 = ScoringConfig()
        v2 = ScoringConfig(
            place_1_coefficient=Decimal("0.45"),
            place_2_coefficient=Decimal("0.30"),
            place_3_coefficient=Decimal("0.20"),
            place_4_coefficient=Decimal("0.15"),
            place_5_coefficient=Decimal("0.10"),
            knockout_small_points=15,
            knockout_big_points=60,
            knockout_main_points=30,
            knockout_main_final_points=100,
        )
        session.add_all([v1, v2])
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_rules_async(session)
        player = build_player(
            telegram_id=200,
            display_name="Player",
            status=UserStatus.ACTIVE,
        )
        session.add_all(
            [
                Season(
                    name="Осень 2026",
                    scoring_config_id=v2.id,
                    starts_at=date(2026, 9, 1),
                    ends_at=None,
                ),
                player,
            ]
        )
        await session.flush()
        tournaments = [
            Tournament(
                season_id=1,
                scoring_config_id=v2.id,
                tournament_type_id=(
                    tournament_type_id("freezeout_v2")
                    if tournament_date == date(2026, 9, 4)
                    else tournament_type_id("classic_v3")
                ),
                date=tournament_date,
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            for tournament_date in recalc_points.TARGET_DATES
        ]
        session.add_all(tournaments)
        await session.flush()
        target_tournament = next(
            tournament for tournament in tournaments if tournament.date == date(2026, 9, 4)
        )
        session.add(
            TournamentResult(
                tournament_id=target_tournament.id,
                player_id=player.id,
                place=1,
                knockouts_count=2,
                big_knockouts_count=1,
                tournament_points=Decimal("450.00"),
                knockout_points=Decimal("15.00"),
                bonus_points=7,
            )
        )
        session.add(
            PlayerReward(
                player_id=player.id,
                reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                chips_amount=40_000,
                source_tournament_id=target_tournament.id,
                source_place=1,
                issued_at=target_tournament.created_at,
                valid_through=date(2026, 9, 11),
            )
        )
        await session.commit()


async def test_recalculation_dry_run_uses_domain_rule_multiplier_without_mutation(
    tmp_path: Path,
) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "recalc-dry-run.db")
    try:
        await seed_recalculation_data(session_factory)
        async with session_factory() as session:
            plan = await recalc_points.build_plan(session)
            assert plan.safe_to_apply
            assert len(plan.items) == 1
            assert plan.items[0].old_points == Decimal("450.00")
            assert plan.items[0].new_points == Decimal("675.00")

        async with session_factory() as session:
            result = (await session.execute(select(TournamentResult))).scalar_one()
            assert result.tournament_points == Decimal("450.00")
    finally:
        await engine.dispose()


async def test_recalculation_apply_changes_only_tournament_points_and_is_idempotent(
    tmp_path: Path,
) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "recalc-apply.db")
    try:
        await seed_recalculation_data(session_factory)
        async with session_factory() as session:
            plan = await recalc_points.build_plan(session)
            assert plan.safe_to_apply
            before_tournaments = await recalc_points.protected_tournament_snapshot(session)
            before_results = await recalc_points.protected_result_snapshot(session)
            before_rewards = await recalc_points.protected_reward_snapshot(session)
            await recalc_points.apply_plan(session, plan.items)
            await recalc_points.assert_protected_fields_unchanged(
                session,
                before_tournaments,
                before_results,
                before_rewards,
            )
            await session.commit()

        async with session_factory() as session:
            result = (await session.execute(select(TournamentResult))).scalar_one()
            assert result.tournament_points == Decimal("675.00")
            assert result.knockout_points == Decimal("15.00")
            assert result.bonus_points == 7
            assert result.place == 1
            second_plan = await recalc_points.build_plan(session)
            assert second_plan.items[0].changed is False
    finally:
        await engine.dispose()


async def test_recalculation_plan_fails_closed_when_target_tournament_missing(
    tmp_path: Path,
) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "recalc-missing.db")
    try:
        await seed_recalculation_data(session_factory)
        async with session_factory() as session:
            tournament = (
                await session.execute(select(Tournament).where(Tournament.date == date(2026, 9, 2)))
            ).scalar_one()
            await session.delete(tournament)
            await session.commit()

        async with session_factory() as session:
            plan = await recalc_points.build_plan(session)
            assert not plan.safe_to_apply
            assert plan.issues == (
                recalc_points.RecalculationIssue(
                    date(2026, 9, 2),
                    "target tournament is missing",
                ),
            )
    finally:
        await engine.dispose()


async def test_recalculation_plan_fails_closed_when_target_uses_wrong_scoring_config(
    tmp_path: Path,
) -> None:
    session_factory, engine = await create_session_factory(tmp_path / "recalc-wrong-config.db")
    try:
        await seed_recalculation_data(session_factory)
        async with session_factory() as session:
            v1 = (
                await session.execute(
                    select(ScoringConfig).where(ScoringConfig.knockout_main_points.is_(None))
                )
            ).scalar_one()
            tournament = (
                await session.execute(select(Tournament).where(Tournament.date == date(2026, 9, 2)))
            ).scalar_one()
            tournament.scoring_config_id = v1.id
            await session.commit()

        async with session_factory() as session:
            plan = await recalc_points.build_plan(session)
            assert not plan.safe_to_apply
            assert len(plan.issues) == 1
            assert plan.issues[0].tournament_date == date(2026, 9, 2)
            assert "not bound to scoring v2" in plan.issues[0].reason
    finally:
        await engine.dispose()


def test_scoring_v2_migration_downgrade_restores_current_season_to_v1(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "migration-downgrade.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "4c5d6e7f8a9b"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(db_path) as connection:
        v1_config_id = connection.execute(
            """
            SELECT id
            FROM scoring_configs
            WHERE place_1_coefficient = 0.45
              AND place_2_coefficient = 0.25
              AND place_3_coefficient = 0.15
              AND place_4_coefficient = 0.10
              AND place_5_coefficient = 0.05
              AND knockout_small_points = 15
              AND knockout_big_points = 60
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()[0]
        connection.execute(
            "UPDATE seasons SET ends_at = NULL, scoring_config_id = ? WHERE id = 1",
            (v1_config_id,),
        )
        connection.commit()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(db_path) as connection:
        upgraded = connection.execute(
            """
            SELECT sc.place_2_coefficient, sc.knockout_main_points
            FROM seasons AS s
            JOIN scoring_configs AS sc ON sc.id = s.scoring_config_id
            WHERE s.ends_at IS NULL
            """
        ).fetchone()
        assert upgraded == (0.3, 30)

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "4c5d6e7f8a9b"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(db_path) as connection:
        downgraded = connection.execute(
            """
            SELECT sc.place_2_coefficient, sc.knockout_small_points, sc.knockout_big_points
            FROM seasons AS s
            JOIN scoring_configs AS sc ON sc.id = s.scoring_config_id
            WHERE s.ends_at IS NULL
            """
        ).fetchone()
        assert downgraded == (0.25, 15, 60)
        v2_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM scoring_configs
            WHERE place_1_coefficient = 0.45
              AND place_2_coefficient = 0.30
              AND place_3_coefficient = 0.20
              AND place_4_coefficient = 0.15
              AND place_5_coefficient = 0.10
              AND knockout_small_points = 15
              AND knockout_big_points = 60
            """
        ).fetchone()[0]
        assert v2_rows == 0
