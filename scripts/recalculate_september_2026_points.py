#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import (  # noqa: E402
    PlayerReward,
    ScoringConfig,
    Tournament,
    TournamentResult,
    TournamentTypeRule,
)
from app.services.result_service import ResultService  # noqa: E402


TARGET_DATES = (
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 5),
    date(2026, 9, 6),
)
V2_PLACE_COEFFICIENTS = (
    Decimal("0.45"),
    Decimal("0.30"),
    Decimal("0.20"),
    Decimal("0.15"),
    Decimal("0.10"),
)
V2_SMALL_KO_POINTS = 15
V2_BIG_KO_POINTS = 60
V2_MAIN_KO_POINTS = 30
V2_MAIN_FINAL_KO_POINTS = 100


@dataclass(frozen=True)
class RecalculationItem:
    tournament_id: int
    tournament_date: date
    player_id: int
    place: int | None
    old_points: Decimal
    new_points: Decimal

    @property
    def changed(self) -> bool:
        return self.old_points != self.new_points


@dataclass(frozen=True)
class RecalculationIssue:
    tournament_date: date
    reason: str


@dataclass(frozen=True)
class RecalculationPlan:
    items: tuple[RecalculationItem, ...]
    issues: tuple[RecalculationIssue, ...]

    @property
    def safe_to_apply(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class ProtectedSnapshot:
    result_id: int
    tournament_id: int
    player_id: int
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    knockout_points: Decimal
    bonus_points: int


@dataclass(frozen=True)
class RewardSnapshot:
    reward_id: int
    player_id: int
    reward_type: str
    chips_amount: int
    source_tournament_id: int
    source_place: int
    issued_at: object
    valid_through: date
    redeemed_at: object
    redeemed_tournament_id: int | None
    redeemed_by_user_id: int | None
    redeemed_tournament_day: date | None
    expiration_reminder_sent_at: object


@dataclass(frozen=True)
class TournamentSnapshot:
    tournament_id: int
    tournament_date: date
    season_id: int
    scoring_config_id: int
    tournament_type_id: int
    tournament_fund: int | None
    registration_open: bool
    status: str


class MaintenanceError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalculate 2026-09-02..2026-09-06 tournament_points via domain scoring."
    )
    parser.add_argument("--db", type=Path, required=True, help="Existing SQLite DB path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the maintenance operation. Default is dry-run.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(db_path=args.db, apply=args.apply))
    except MaintenanceError as exc:
        raise SystemExit(str(exc)) from exc


async def run(*, db_path: Path, apply: bool) -> None:
    resolved_db = db_path.expanduser().resolve()
    if not resolved_db.exists():
        raise MaintenanceError(f"Database does not exist: {resolved_db}")

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{resolved_db}"
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            plan = await build_plan(session)
            print_plan(plan, apply=apply, db_path=resolved_db)
            if not plan.safe_to_apply:
                raise MaintenanceError("NOT SAFE TO APPLY")
            if not apply:
                return
            before_tournaments = await protected_tournament_snapshot(session)
            before_results = await protected_result_snapshot(session)
            before_rewards = await protected_reward_snapshot(session)
            try:
                await apply_plan(session, plan.items)
                await assert_protected_fields_unchanged(
                    session,
                    before_tournaments,
                    before_results,
                    before_rewards,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            print("Applied.")
    finally:
        await engine.dispose()


async def build_plan(session) -> RecalculationPlan:
    issues = await validate_target_tournaments(session)
    if issues:
        return RecalculationPlan(items=(), issues=issues)

    rows = await session.execute(
        select(Tournament, TournamentResult, ScoringConfig, TournamentTypeRule)
        .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
        .join(ScoringConfig, ScoringConfig.id == Tournament.scoring_config_id)
        .outerjoin(
            TournamentTypeRule,
            TournamentTypeRule.tournament_type_id == Tournament.tournament_type_id,
        )
        .options(selectinload(Tournament.tournament_type))
        .where(Tournament.date.in_(TARGET_DATES))
        .order_by(
            Tournament.date,
            TournamentResult.place.is_(None),
            TournamentResult.place,
            TournamentResult.player_id,
        )
    )
    items: list[RecalculationItem] = []
    for tournament, result, scoring_config, rule in rows:
        if tournament.tournament_fund is None:
            raise MaintenanceError(f"Tournament fund is missing: {tournament.date}")
        new_points = ResultService.calculate_tournament_points(
            tournament_fund=Decimal(tournament.tournament_fund),
            place=result.place,
            scoring_config=scoring_config,
            rule=rule,
        )
        items.append(
            RecalculationItem(
                tournament_id=tournament.id,
                tournament_date=tournament.date,
                player_id=result.player_id,
                place=result.place,
                old_points=Decimal(result.tournament_points),
                new_points=new_points,
            )
        )
    return RecalculationPlan(items=tuple(items), issues=())


async def validate_target_tournaments(session) -> tuple[RecalculationIssue, ...]:
    rows = await session.execute(
        select(Tournament, ScoringConfig)
        .join(ScoringConfig, ScoringConfig.id == Tournament.scoring_config_id)
        .where(Tournament.date.in_(TARGET_DATES))
        .order_by(Tournament.date, Tournament.id)
    )
    tournaments_by_date: dict[date, list[tuple[Tournament, ScoringConfig]]] = {
        target_date: [] for target_date in TARGET_DATES
    }
    for tournament, scoring_config in rows:
        tournaments_by_date.setdefault(tournament.date, []).append((tournament, scoring_config))

    issues: list[RecalculationIssue] = []
    for target_date in TARGET_DATES:
        rows_for_date = tournaments_by_date.get(target_date, [])
        if not rows_for_date:
            issues.append(RecalculationIssue(target_date, "target tournament is missing"))
            continue
        if len(rows_for_date) != 1:
            issues.append(RecalculationIssue(target_date, "target tournament is ambiguous"))
            continue
        _, scoring_config = rows_for_date[0]
        if not scoring_config_matches_v2(scoring_config):
            issues.append(
                RecalculationIssue(
                    target_date,
                    f"target tournament is not bound to scoring v2: {scoring_config.id}",
                )
            )
    return tuple(issues)


def scoring_config_matches_v2(config: ScoringConfig) -> bool:
    return (
        Decimal(config.place_1_coefficient) == V2_PLACE_COEFFICIENTS[0]
        and Decimal(config.place_2_coefficient) == V2_PLACE_COEFFICIENTS[1]
        and Decimal(config.place_3_coefficient) == V2_PLACE_COEFFICIENTS[2]
        and Decimal(config.place_4_coefficient) == V2_PLACE_COEFFICIENTS[3]
        and Decimal(config.place_5_coefficient) == V2_PLACE_COEFFICIENTS[4]
        and config.knockout_small_points == V2_SMALL_KO_POINTS
        and config.knockout_big_points == V2_BIG_KO_POINTS
        and config.knockout_main_points == V2_MAIN_KO_POINTS
        and config.knockout_main_final_points == V2_MAIN_FINAL_KO_POINTS
    )


async def apply_plan(session, items: tuple[RecalculationItem, ...]) -> None:
    for item in items:
        if not item.changed:
            continue
        result = (
            await session.execute(
                select(TournamentResult).where(
                    TournamentResult.tournament_id == item.tournament_id,
                    TournamentResult.player_id == item.player_id,
                )
            )
        ).scalar_one()
        result.tournament_points = item.new_points


async def protected_result_snapshot(session) -> tuple[ProtectedSnapshot, ...]:
    rows = await session.execute(
        select(TournamentResult)
        .join(Tournament, Tournament.id == TournamentResult.tournament_id)
        .where(Tournament.date.in_(TARGET_DATES))
        .order_by(TournamentResult.id)
    )
    return tuple(
        ProtectedSnapshot(
            result_id=result.id,
            tournament_id=result.tournament_id,
            player_id=result.player_id,
            place=result.place,
            knockouts_count=result.knockouts_count,
            big_knockouts_count=result.big_knockouts_count,
            knockout_points=Decimal(result.knockout_points),
            bonus_points=result.bonus_points,
        )
        for result in rows.scalars()
    )


async def assert_protected_fields_unchanged(
    session,
    before_tournaments: tuple[TournamentSnapshot, ...],
    before_results: tuple[ProtectedSnapshot, ...],
    before_rewards: tuple[RewardSnapshot, ...],
) -> None:
    after_tournaments = await protected_tournament_snapshot(session)
    if before_tournaments != after_tournaments:
        raise MaintenanceError("Protected tournament fields changed; rolling back.")
    after_results = await protected_result_snapshot(session)
    if before_results != after_results:
        raise MaintenanceError("Protected result fields changed; rolling back.")
    after_rewards = await protected_reward_snapshot(session)
    if before_rewards != after_rewards:
        raise MaintenanceError("Reward rows changed; rolling back.")


async def protected_tournament_snapshot(session) -> tuple[TournamentSnapshot, ...]:
    rows = await session.execute(
        select(Tournament).where(Tournament.date.in_(TARGET_DATES)).order_by(Tournament.id)
    )
    return tuple(
        TournamentSnapshot(
            tournament_id=tournament.id,
            tournament_date=tournament.date,
            season_id=tournament.season_id,
            scoring_config_id=tournament.scoring_config_id,
            tournament_type_id=tournament.tournament_type_id,
            tournament_fund=tournament.tournament_fund,
            registration_open=tournament.registration_open,
            status=(
                tournament.status.value
                if hasattr(tournament.status, "value")
                else str(tournament.status)
            ),
        )
        for tournament in rows.scalars()
    )


async def protected_reward_snapshot(session) -> tuple[RewardSnapshot, ...]:
    rows = await session.execute(
        select(PlayerReward)
        .join(Tournament, Tournament.id == PlayerReward.source_tournament_id)
        .where(Tournament.date.in_(TARGET_DATES))
        .order_by(PlayerReward.id)
    )
    return tuple(
        RewardSnapshot(
            reward_id=reward.id,
            player_id=reward.player_id,
            reward_type=(
                reward.reward_type.value
                if hasattr(reward.reward_type, "value")
                else str(reward.reward_type)
            ),
            chips_amount=reward.chips_amount,
            source_tournament_id=reward.source_tournament_id,
            source_place=reward.source_place,
            issued_at=reward.issued_at,
            valid_through=reward.valid_through,
            redeemed_at=reward.redeemed_at,
            redeemed_tournament_id=reward.redeemed_tournament_id,
            redeemed_by_user_id=reward.redeemed_by_user_id,
            redeemed_tournament_day=reward.redeemed_tournament_day,
            expiration_reminder_sent_at=reward.expiration_reminder_sent_at,
        )
        for reward in rows.scalars()
    )


def print_plan(
    plan: RecalculationPlan,
    *,
    apply: bool,
    db_path: Path,
) -> None:
    print(f"Database: {db_path}")
    print(f"Mode: {'apply' if apply else 'dry-run'}")
    for issue in plan.issues:
        print(f"issue: date={issue.tournament_date.isoformat()} reason={issue.reason}")
    for item in plan.items:
        marker = "change" if item.changed else "unchanged"
        print(
            f"{marker}: tournament={item.tournament_id} date={item.tournament_date.isoformat()} "
            f"player={item.player_id} place={item.place} "
            f"old_points={item.old_points:.2f} new_points={item.new_points:.2f}"
        )
    print(
        "Summary: "
        f"rows={len(plan.items)} "
        f"change={sum(1 for item in plan.items if item.changed)} "
        f"unchanged={sum(1 for item in plan.items if not item.changed)} "
        f"issues={len(plan.issues)}"
    )
    print(f"Verdict: {'SAFE TO APPLY' if plan.safe_to_apply else 'NOT SAFE TO APPLY'}")


if __name__ == "__main__":
    main()
