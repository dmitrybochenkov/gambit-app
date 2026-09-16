#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import Tournament  # noqa: E402
from app.db.models.enums import KnockoutMode, TournamentStatus  # noqa: E402
from app.db.repositories.season_repository import SeasonRepository  # noqa: E402
from app.db.repositories.tournament_repository import TournamentRepository  # noqa: E402
from app.db.repositories.tournament_type_repository import (  # noqa: E402
    TournamentTypeConfigRecord,
    TournamentTypeRepository,
)


@dataclass(frozen=True)
class ExpectedTypeConfig:
    name: str
    short_name: str
    calendar_code: str
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: tuple[tuple[int, int, int], ...]
    knockout_mode: KnockoutMode


@dataclass(frozen=True)
class TargetTournament:
    tournament_date: date
    tournament_type_code: str
    tournament_fund: int | None = None


@dataclass(frozen=True)
class TournamentPlanItem:
    target: TargetTournament
    action: str
    details: str


TARGET_TOURNAMENTS = (
    TargetTournament(date(2026, 9, 16), "slow_blinds"),
    TargetTournament(date(2026, 9, 17), "bounty_v3"),
    TargetTournament(date(2026, 9, 18), "classic_v3"),
    TargetTournament(date(2026, 9, 19), "satellite"),
    TargetTournament(date(2026, 9, 20), "black_party"),
)

EXPECTED_TYPES = {
    "slow_blinds": ExpectedTypeConfig(
        name="Slow Blinds",
        short_name="Slow Blinds",
        calendar_code="SB",
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=800,
        addon_stack=60_000,
        rebuys=((1, 800, 30_000),),
        knockout_mode=KnockoutMode.NONE,
    ),
    "bounty_v3": ExpectedTypeConfig(
        name="Bounty",
        short_name="Bounty",
        calendar_code="B3",
        entry_fee=600,
        entry_stack=20_000,
        addon_fee=800,
        addon_stack=125_000,
        rebuys=(
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 60_000),
            (4, 1000, 80_000),
            (5, 1000, 80_000),
        ),
        knockout_mode=KnockoutMode.SMALL_BIG,
    ),
    "classic_v3": ExpectedTypeConfig(
        name="Freeroll",
        short_name="Freeroll",
        calendar_code="FR",
        entry_fee=0,
        entry_stack=15_000,
        addon_fee=800,
        addon_stack=125_000,
        rebuys=(
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 60_000),
            (4, 1000, 80_000),
            (5, 1000, 80_000),
        ),
        knockout_mode=KnockoutMode.NONE,
    ),
    "satellite": ExpectedTypeConfig(
        name="Satellite",
        short_name="Satellite",
        calendar_code="ST",
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=1000,
        addon_stack=150_000,
        rebuys=((1, 1000, 50_000), (2, 1000, 70_000)),
        knockout_mode=KnockoutMode.NONE,
    ),
    "black_party": ExpectedTypeConfig(
        name="Black Party",
        short_name="Black Party",
        calendar_code="BP",
        entry_fee=800,
        entry_stack=30_000,
        addon_fee=1000,
        addon_stack=150_000,
        rebuys=(
            (1, 800, 40_000),
            (2, 800, 50_000),
            (3, 1000, 80_000),
            (4, 1000, 100_000),
        ),
        knockout_mode=KnockoutMode.NONE,
    ),
}
LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE = "legacy_unknown"


class MaintenanceError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the controlled Gambit tournament week 2026-09-16..2026-09-20."
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
            if has_conflicts(plan):
                raise MaintenanceError("NOT SAFE TO APPLY")
            if not apply:
                return
            try:
                await apply_plan(session, plan)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            print("Applied.")
    finally:
        await engine.dispose()


async def build_plan(session) -> tuple[TournamentPlanItem, ...]:
    tournament_repository = TournamentRepository(session)
    type_repository = TournamentTypeRepository(session)
    season_repository = SeasonRepository(session)
    existing_by_date = {
        tournament.date: tournament
        for tournament in await tournament_repository.list_by_dates(
            tuple(target.tournament_date for target in TARGET_TOURNAMENTS)
        )
    }
    items: list[TournamentPlanItem] = []
    for target in TARGET_TOURNAMENTS:
        config = await _validated_type_config(type_repository, target.tournament_type_code)
        if isinstance(config, str):
            items.append(TournamentPlanItem(target, "conflict", config))
            continue
        season = await season_repository.get_for_date(target.tournament_date)
        if season is None:
            items.append(TournamentPlanItem(target, "conflict", "season is missing for date"))
            continue
        existing = existing_by_date.get(target.tournament_date)
        if existing is None:
            items.append(
                TournamentPlanItem(
                    target,
                    "create",
                    f"season={season.name}, scoring_config_id={season.scoring_config_id}",
                )
            )
            continue
        expected = (
            existing.tournament_type_id == config.tournament_type.id
            and existing.tournament_fund == target.tournament_fund
            and existing.status == TournamentStatus.ACTIVE
            and existing.registration_open is False
            and existing.scoring_config_id == season.scoring_config_id
        )
        action = "unchanged" if expected else "conflict"
        items.append(
            TournamentPlanItem(
                target,
                action,
                (
                    f"existing id={existing.id}, type_id={existing.tournament_type_id}, "
                    f"fund={existing.tournament_fund}, status={existing.status.value}, "
                    f"registration_open={existing.registration_open}, "
                    f"scoring_config_id={existing.scoring_config_id}"
                ),
            )
        )
    return tuple(items)


async def _validated_type_config(
    repository: TournamentTypeRepository,
    code: str,
) -> TournamentTypeConfigRecord | str:
    tournament_type = await repository.get_by_code(code)
    if tournament_type is None:
        return f"tournament type is missing: {code}"
    config = await repository.get_real_config(
        tournament_type.id,
        legacy_unknown_code=LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
    )
    if config is None or not config.tournament_type.is_creatable:
        return "target tournament type is missing or not creatable"
    expected = EXPECTED_TYPES[code]
    if (
        config.tournament_type.name,
        config.tournament_type.short_name,
        config.tournament_type.calendar_code,
    ) != (expected.name, expected.short_name, expected.calendar_code):
        return (
            "target tournament type identity mismatch: "
            f"name={config.tournament_type.name!r}, "
            f"short_name={config.tournament_type.short_name!r}, "
            f"calendar_code={config.tournament_type.calendar_code!r}"
        )
    economy = config.economy
    if economy is None:
        return "target tournament type economy is missing"
    if (
        economy.entry_fee,
        economy.entry_stack,
        economy.addon_fee,
        economy.addon_stack,
    ) != (
        expected.entry_fee,
        expected.entry_stack,
        expected.addon_fee,
        expected.addon_stack,
    ):
        return "target tournament type economy mismatch"
    actual_rebuys = tuple((rebuy.rebuy_order, rebuy.fee, rebuy.stack) for rebuy in config.rebuys)
    if actual_rebuys != expected.rebuys:
        return f"target tournament type rebuys mismatch: {actual_rebuys!r}"
    if config.rule is None or config.rule.knockout_mode != expected.knockout_mode:
        return "target tournament type rule mismatch"
    return config


async def apply_plan(session, plan: tuple[TournamentPlanItem, ...]) -> None:
    repository = TournamentRepository(session)
    type_repository = TournamentTypeRepository(session)
    season_repository = SeasonRepository(session)
    for item in plan:
        if item.action == "unchanged":
            continue
        if item.action != "create":
            raise MaintenanceError(f"Cannot apply {item.action}: {item.target.tournament_date}")
        config = await _validated_type_config(type_repository, item.target.tournament_type_code)
        if isinstance(config, str):
            raise MaintenanceError(config)
        season = await season_repository.get_for_date(item.target.tournament_date)
        if season is None:
            raise MaintenanceError(f"Season is missing for {item.target.tournament_date}")
        await repository.add(
            Tournament(
                season_id=season.id,
                scoring_config_id=season.scoring_config_id,
                tournament_type_id=config.tournament_type.id,
                date=item.target.tournament_date,
                tournament_fund=item.target.tournament_fund,
                registration_open=False,
                status=TournamentStatus.ACTIVE,
            )
        )


def has_conflicts(plan: tuple[TournamentPlanItem, ...]) -> bool:
    return any(item.action == "conflict" for item in plan)


def print_plan(
    plan: tuple[TournamentPlanItem, ...],
    *,
    apply: bool,
    db_path: Path,
) -> None:
    print(f"Database: {db_path}")
    print(f"Mode: {'apply' if apply else 'dry-run'}")
    for item in plan:
        print(
            f"{item.action}: {item.target.tournament_date.isoformat()} "
            f"{item.target.tournament_type_code} fund={item.target.tournament_fund} "
            f"({item.details})"
        )
    print(
        "Summary: "
        f"create={sum(1 for item in plan if item.action == 'create')} "
        f"unchanged={sum(1 for item in plan if item.action == 'unchanged')} "
        f"conflict={sum(1 for item in plan if item.action == 'conflict')}"
    )
    print(f"Verdict: {'NOT SAFE TO APPLY' if has_conflicts(plan) else 'SAFE TO APPLY'}")


if __name__ == "__main__":
    main()
