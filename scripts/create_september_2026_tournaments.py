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

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import Tournament  # noqa: E402
from app.db.models.enums import TournamentStatus  # noqa: E402
from app.db.repositories.season_repository import SeasonRepository  # noqa: E402
from app.db.repositories.tournament_repository import TournamentRepository  # noqa: E402
from app.db.repositories.tournament_type_repository import (  # noqa: E402
    TournamentTypeRepository,
)


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
    TargetTournament(date(2026, 9, 9), "bounty_v3"),
    TargetTournament(date(2026, 9, 10), "classic_v3"),
    TargetTournament(date(2026, 9, 11), "deep_stack_v2"),
    TargetTournament(date(2026, 9, 12), "freezeout_v2", 2000),
    TargetTournament(date(2026, 9, 13), "main_ko"),
)
LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE = "legacy_unknown"


class MaintenanceError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the controlled Gambit tournament week 2026-09-09..2026-09-13."
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
        config = await type_repository.get_real_config(
            await tournament_type_id_by_code(type_repository, target.tournament_type_code),
            legacy_unknown_code=LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
        )
        if config is None or not config.tournament_type.is_creatable:
            items.append(
                TournamentPlanItem(target, "conflict", "target tournament type is missing")
            )
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


async def tournament_type_id_by_code(
    repository: TournamentTypeRepository,
    code: str,
) -> int:
    tournament_type = await repository.get_by_code(code)
    if tournament_type is None:
        raise MaintenanceError(f"Tournament type is missing: {code}")
    return tournament_type.id


async def apply_plan(session, plan: tuple[TournamentPlanItem, ...]) -> None:
    repository = TournamentRepository(session)
    type_repository = TournamentTypeRepository(session)
    season_repository = SeasonRepository(session)
    for item in plan:
        if item.action == "unchanged":
            continue
        if item.action != "create":
            raise MaintenanceError(f"Cannot apply {item.action}: {item.target.tournament_date}")
        tournament_type_id = await tournament_type_id_by_code(
            type_repository,
            item.target.tournament_type_code,
        )
        season = await season_repository.get_for_date(item.target.tournament_date)
        if season is None:
            raise MaintenanceError(f"Season is missing for {item.target.tournament_date}")
        await repository.add(
            Tournament(
                season_id=season.id,
                scoring_config_id=season.scoring_config_id,
                tournament_type_id=tournament_type_id,
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
