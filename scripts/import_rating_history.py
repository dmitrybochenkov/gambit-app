#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.common.normalization import normalize_display_name  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "gambit.db"
DEFAULT_ALIASES_PATH = PROJECT_ROOT / "data" / "historical_result_aliases.csv"
DEFAULT_RESULTS_SHEET = "Данные за все время"
DEFAULT_MAPPING_SHEET = "Лист12"
LEGACY_TOURNAMENT_TYPE_CODE = "legacy_unknown"
SUPERADMIN_DISPLAY_NAME = "Дима Боченков"
SUPERADMIN_TELEGRAM_ID = 754076859
EXPECTED_SOURCE_COLUMNS = (
    "Дата",
    "Игрок",
    "Место в турнире",
    "КО",
    "Босс КО",
    "Доп.очки",
    "Количество очков за турнир",
    "Количество очков за КО",
)
EXPECTED_TOURNAMENT_DISTRIBUTION = {
    "Сезон 1": 0,
    "Сезон 2": 91,
    "Лето 2026": 39,
}
REQUIRED_SEASONS = (
    ("Сезон 1", date(2025, 10, 16), date(2026, 1, 25)),
    ("Сезон 2", date(2026, 1, 27), date(2026, 5, 31)),
    ("Лето 2026", date(2026, 6, 1), None),
)
ZERO = Decimal("0.00")


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SourceRow:
    source_row: int
    tournament_date: date
    raw_player_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int
    tournament_points: Decimal
    knockout_points: Decimal


@dataclass(frozen=True)
class BlankPlayerRow:
    source_row: int
    tournament_date: date
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int
    tournament_points: Decimal
    knockout_points: Decimal
    reason: str = "blank_player"


@dataclass(frozen=True)
class ResolvedResultRow:
    source_row: int
    tournament_date: date
    raw_player_name: str
    mapped_name: str
    user_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int
    tournament_points: Decimal
    knockout_points: Decimal


@dataclass(frozen=True)
class UserCandidate:
    id: int
    display_name: str
    display_name_normalized: str


@dataclass(frozen=True)
class UnresolvedUser:
    source_row: int
    raw_player_name: str
    mapped_name: str
    display_name_normalized: str | None
    reason: str


@dataclass(frozen=True)
class AmbiguousUser:
    source_row: int
    raw_player_name: str
    mapped_name: str
    display_name_normalized: str | None
    candidates: tuple[UserCandidate, ...]


@dataclass(frozen=True)
class TournamentPlanItem:
    tournament_date: date
    season_id: int
    season_name: str
    tournament_type_id: int
    tournament_fund: int | None
    action: str
    existing_id: int | None = None
    conflict: str | None = None


@dataclass(frozen=True)
class UserPlanItem:
    display_name: str
    display_name_normalized: str
    telegram_id: int | None
    role: str
    status: str
    action: str
    id: int | None = None
    existing_id: int | None = None
    conflict: str | None = None


@dataclass(frozen=True)
class ResultPlanItem:
    source_row: int
    tournament_date: date
    user_id: int
    display_name: str
    action: str
    existing_id: int | None = None
    conflict: str | None = None
    diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportSource:
    path: Path
    source_format: str
    results_sheet: str
    mapping_sheet: str
    dated_rows_count: int
    result_rows: tuple[SourceRow, ...]
    blank_player_rows: tuple[BlankPlayerRow, ...]
    mappings: dict[str, str]


@dataclass
class ImportPlan:
    source: ImportSource
    db_path: Path
    aliases_path: Path | None
    user_items: list[UserPlanItem]
    resolved_rows: list[ResolvedResultRow]
    unresolved_users: list[UnresolvedUser]
    ambiguous_users: list[AmbiguousUser]
    tournament_items: list[TournamentPlanItem]
    result_items: list[ResultPlanItem]
    season_distribution: dict[str, int]
    errors: list[str]
    update_existing: bool = False

    @property
    def safe_to_apply(self) -> bool:
        return (
            not self.errors
            and not self.unresolved_users
            and not self.ambiguous_users
            and not any(item.action == "conflict" for item in self.user_items)
            and not any(item.action == "conflict" for item in self.tournament_items)
            and not any(item.action == "conflict" for item in self.result_items)
        )


@dataclass(frozen=True)
class ApplyStats:
    users_created: int
    users_updated: int
    users_unchanged: int
    tournaments_created: int
    tournaments_unchanged: int
    results_created: int
    results_updated: int
    results_unchanged: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely import Gambit historical tournaments and results."
    )
    parser.add_argument("source", nargs="?", type=Path, help="Source .xlsx/.csv file")
    parser.add_argument("--file", dest="source_file", type=Path, help="Source .xlsx/.csv file")
    parser.add_argument("--input", dest="input_path", type=Path, help="Source .xlsx/.csv file")
    parser.add_argument("--db", type=Path, default=default_db_path(), help="Existing SQLite DB")
    parser.add_argument("--sheet", default=DEFAULT_RESULTS_SHEET, help="Results sheet name")
    parser.add_argument(
        "--mapping-sheet",
        default=DEFAULT_MAPPING_SHEET,
        help="Player mapping sheet name",
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=DEFAULT_ALIASES_PATH,
        help="Optional CSV with source_name,user_id aliases",
    )
    parser.add_argument(
        "--export-report",
        type=Path,
        help="Directory for JSON summary and CSV error reports",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the safe plan")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Allow updating differing existing TournamentResult rows",
    )
    args = parser.parse_args()
    source_path = args.source_file or args.input_path or args.source
    if source_path is None:
        parser.error("source file is required; pass positional source, --file, or --input")

    try:
        plan = build_import_plan(
            source_path=source_path,
            db_path=args.db,
            results_sheet=args.sheet,
            mapping_sheet=args.mapping_sheet,
            aliases_path=args.aliases if args.aliases.exists() else None,
            update_existing=args.update_existing,
        )
        if args.export_report:
            export_report(args.export_report, plan)
        print_report(plan)
        if args.apply:
            stats = apply_import_plan(plan)
            print_apply_stats(stats, args.db)
            verification = verify_post_import(args.db, plan)
            print_json("Post-import verification", verification)
    except ImportValidationError as error:
        raise SystemExit(f"Import failed: {error}") from error


def default_db_path() -> Path:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("sqlite+aiosqlite:///"):
        return Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    return DEFAULT_DB_PATH


def build_import_plan(
    *,
    source_path: Path,
    db_path: Path,
    results_sheet: str = DEFAULT_RESULTS_SHEET,
    mapping_sheet: str = DEFAULT_MAPPING_SHEET,
    aliases_path: Path | None = None,
    update_existing: bool = False,
    strict_expectations: bool = True,
    create_missing_users: bool | None = None,
) -> ImportPlan:
    source = load_import_source(source_path, results_sheet, mapping_sheet)
    if create_missing_users is None:
        create_missing_users = source.source_format == "csv"
    aliases = (
        {}
        if source.source_format == "csv"
        else load_aliases(aliases_path)
        if aliases_path is not None
        else {}
    )
    connection = connect_existing_database(db_path)
    try:
        validate_required_database_state(connection)
        legacy_type_id = get_required_tournament_type_id(connection, LEGACY_TOURNAMENT_TYPE_CODE)
        effective_strict_expectations = strict_expectations and source.source_format != "csv"
        user_items = build_user_plan(
            connection,
            source.result_rows,
            create_missing_users=create_missing_users,
        )
        resolved_rows, unresolved_users, ambiguous_users = resolve_users(
            connection,
            source.result_rows,
            source.mappings,
            aliases,
            user_items=user_items,
        )
        resolved_rows = clear_duplicate_prize_places(resolved_rows)
        tournament_items, season_distribution, season_errors = build_tournament_plan(
            connection,
            source,
            resolved_rows,
            legacy_type_id,
            strict_expectations=effective_strict_expectations,
        )
        result_items = build_result_plan(
            connection,
            resolved_rows,
            tournament_items,
            update_existing=update_existing,
        )
        result_errors = validate_result_rows(resolved_rows)
        errors = [*season_errors, *result_errors]
        return ImportPlan(
            source=source,
            db_path=db_path,
            aliases_path=aliases_path,
            user_items=user_items,
            resolved_rows=resolved_rows,
            unresolved_users=unresolved_users,
            ambiguous_users=ambiguous_users,
            tournament_items=tournament_items,
            result_items=result_items,
            season_distribution=season_distribution,
            errors=errors,
            update_existing=update_existing,
        )
    finally:
        connection.close()


def load_import_source(
    source_path: Path,
    results_sheet: str,
    mapping_sheet: str,
) -> ImportSource:
    if not source_path.exists():
        raise ImportValidationError(f"Source file not found: {source_path}")
    if source_path.suffix.lower() == ".csv":
        return load_csv_import_source(source_path)
    if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ImportValidationError("Historical result import expects an .xlsx/.xlsm/.csv source.")

    workbook = XlsxWorkbook(source_path)
    mappings = load_player_mappings(workbook, mapping_sheet)
    result_rows: list[SourceRow] = []
    blank_rows: list[BlankPlayerRow] = []
    dated_rows_count = 0
    for source_row, record in workbook.iter_records(results_sheet, EXPECTED_SOURCE_COLUMNS):
        raw_date = record["Дата"]
        if raw_date is None or clean_text(raw_date) == "":
            continue
        dated_rows_count += 1
        tournament_date = parse_excel_date(raw_date)
        raw_player_name = clean_text(record["Игрок"])
        values = {
            "source_row": source_row,
            "tournament_date": tournament_date,
            "place": optional_int(record["Место в турнире"]),
            "knockouts_count": required_int(record["КО"]),
            "big_knockouts_count": required_int(record["Босс КО"]),
            "bonus_points": required_int(record["Доп.очки"]),
            "tournament_points": required_decimal(record["Количество очков за турнир"]),
            "knockout_points": required_decimal(record["Количество очков за КО"]),
        }
        if not raw_player_name:
            blank_rows.append(BlankPlayerRow(**values))
            continue
        result_rows.append(SourceRow(raw_player_name=raw_player_name, **values))

    return ImportSource(
        path=source_path,
        source_format="xlsx",
        results_sheet=results_sheet,
        mapping_sheet=mapping_sheet,
        dated_rows_count=dated_rows_count,
        result_rows=tuple(result_rows),
        blank_player_rows=tuple(blank_rows),
        mappings=mappings,
    )


def load_csv_import_source(source_path: Path) -> ImportSource:
    result_rows: list[SourceRow] = []
    blank_rows: list[BlankPlayerRow] = []
    dated_rows_count = 0
    with source_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ImportValidationError("CSV source is empty.")
        header = tuple(clean_text(column) for column in reader.fieldnames)
        if header != EXPECTED_SOURCE_COLUMNS:
            raise ImportValidationError(
                f"CSV must contain columns exactly: {', '.join(EXPECTED_SOURCE_COLUMNS)}"
            )
        for source_row, record in enumerate(reader, start=2):
            raw_date = record["Дата"]
            if raw_date is None or clean_text(raw_date) == "":
                continue
            dated_rows_count += 1
            tournament_date = parse_excel_date(raw_date)
            raw_player_name = clean_text(record["Игрок"])
            values = {
                "source_row": source_row,
                "tournament_date": tournament_date,
                "place": optional_int(record["Место в турнире"]),
                "knockouts_count": required_int(record["КО"]),
                "big_knockouts_count": required_int(record["Босс КО"]),
                "bonus_points": required_int(record["Доп.очки"]),
                "tournament_points": required_decimal(record["Количество очков за турнир"]),
                "knockout_points": required_decimal(record["Количество очков за КО"]),
            }
            if not raw_player_name:
                blank_rows.append(BlankPlayerRow(**values))
                continue
            result_rows.append(SourceRow(raw_player_name=raw_player_name, **values))
    return ImportSource(
        path=source_path,
        source_format="csv",
        results_sheet="",
        mapping_sheet="",
        dated_rows_count=dated_rows_count,
        result_rows=tuple(result_rows),
        blank_player_rows=tuple(blank_rows),
        mappings={},
    )


def load_player_mappings(workbook: XlsxWorkbook, sheet_name: str) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for source_row, record in workbook.iter_records(
        sheet_name,
        ("Игрок", "Очист_меппинг"),
        allow_extra_columns=True,
    ):
        raw_name = clean_text(record["Игрок"])
        if not raw_name:
            continue
        mapped_name = clean_text(record["Очист_меппинг"])
        if not mapped_name:
            raise ImportValidationError(f"Empty Очист_меппинг on {sheet_name} row {source_row}")
        previous = mappings.get(raw_name)
        if previous is not None and previous != mapped_name:
            raise ImportValidationError(
                f"Conflicting mappings for {raw_name!r}: {previous!r} vs {mapped_name!r}"
            )
        mappings[raw_name] = mapped_name
    return mappings


def load_aliases(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or {"source_name", "user_id"} - set(reader.fieldnames):
            raise ImportValidationError("Alias CSV must contain source_name,user_id columns.")
        aliases: dict[str, int] = {}
        for index, row in enumerate(reader, start=2):
            source_name = clean_text(row.get("source_name"))
            if not source_name:
                raise ImportValidationError(f"Alias row {index} has empty source_name.")
            try:
                user_id = int(str(row.get("user_id", "")).strip())
            except ValueError as error:
                raise ImportValidationError(f"Alias row {index} has invalid user_id.") from error
            previous = aliases.get(source_name)
            if previous is not None and previous != user_id:
                raise ImportValidationError(f"Conflicting aliases for {source_name!r}.")
            aliases[source_name] = user_id
    return aliases


def build_user_plan(
    connection: sqlite3.Connection,
    rows: tuple[SourceRow, ...],
    *,
    create_missing_users: bool,
) -> list[UserPlanItem]:
    items: list[UserPlanItem] = []
    users_by_normalized = load_users_by_normalized(connection)
    users_by_telegram = load_users_by_telegram(connection)
    user_rows_by_id = load_user_rows_by_id(connection)
    next_user_id = max_existing_user_id(connection) + 1
    planned_normalized: set[str] = set()

    superadmin_item, next_user_id = plan_superadmin_user(
        users_by_normalized,
        users_by_telegram,
        user_rows_by_id,
        next_user_id,
    )
    items.append(superadmin_item)
    planned_normalized.add(superadmin_item.display_name_normalized)

    if not create_missing_users:
        return items

    for display_name in unique_player_names(rows):
        normalized = normalize_display_name(display_name)
        if normalized is None or normalized in planned_normalized:
            continue
        candidates = users_by_normalized.get(normalized, [])
        if len(candidates) > 1:
            items.append(
                UserPlanItem(
                    display_name=display_name,
                    display_name_normalized=normalized,
                    telegram_id=None,
                    role="player",
                    status="active",
                    action="conflict",
                    conflict="multiple_existing_users_with_same_normalized_name",
                )
            )
            planned_normalized.add(normalized)
            continue
        if len(candidates) == 1:
            planned_normalized.add(normalized)
            continue
        items.append(
            UserPlanItem(
                id=next_user_id,
                display_name=display_name,
                display_name_normalized=normalized,
                telegram_id=None,
                role="player",
                status="active",
                action="create",
            )
        )
        next_user_id += 1
        planned_normalized.add(normalized)
    return items


def plan_superadmin_user(
    users_by_normalized: dict[str, list[UserCandidate]],
    users_by_telegram: dict[int, sqlite3.Row],
    user_rows_by_id: dict[int, sqlite3.Row],
    next_user_id: int,
) -> tuple[UserPlanItem, int]:
    normalized = normalize_display_name(SUPERADMIN_DISPLAY_NAME)
    if normalized is None:
        raise ImportValidationError("SUPERADMIN display name normalizes to empty value.")
    telegram_user = users_by_telegram.get(SUPERADMIN_TELEGRAM_ID)
    if telegram_user is not None:
        if normalized_user_name(telegram_user) != normalized:
            return (
                UserPlanItem(
                    display_name=SUPERADMIN_DISPLAY_NAME,
                    display_name_normalized=normalized,
                    telegram_id=SUPERADMIN_TELEGRAM_ID,
                    role="superadmin",
                    status="active",
                    action="conflict",
                    existing_id=int(telegram_user["id"]),
                    conflict="telegram_id_belongs_to_different_user",
                ),
                next_user_id,
            )
        return (
            existing_user_item(
                telegram_user,
                display_name=SUPERADMIN_DISPLAY_NAME,
                normalized=normalized,
                telegram_id=SUPERADMIN_TELEGRAM_ID,
                role="superadmin",
                status="active",
            ),
            next_user_id,
        )

    candidates = users_by_normalized.get(normalized, [])
    if len(candidates) > 1:
        return (
            UserPlanItem(
                display_name=SUPERADMIN_DISPLAY_NAME,
                display_name_normalized=normalized,
                telegram_id=SUPERADMIN_TELEGRAM_ID,
                role="superadmin",
                status="active",
                action="conflict",
                conflict="multiple_existing_superadmin_name_candidates",
            ),
            next_user_id,
        )
    if len(candidates) == 1:
        row = user_rows_by_id.get(candidates[0].id)
        if row is None:
            raise ImportValidationError("Internal user lookup failed.")
        if row["telegram_id"] is not None:
            return (
                UserPlanItem(
                    display_name=SUPERADMIN_DISPLAY_NAME,
                    display_name_normalized=normalized,
                    telegram_id=SUPERADMIN_TELEGRAM_ID,
                    role="superadmin",
                    status="active",
                    action="conflict",
                    existing_id=int(row["id"]),
                    conflict="existing_superadmin_name_candidate_has_different_telegram_id",
                ),
                next_user_id,
            )
        return (
            existing_user_item(
                row,
                display_name=SUPERADMIN_DISPLAY_NAME,
                normalized=normalized,
                telegram_id=SUPERADMIN_TELEGRAM_ID,
                role="superadmin",
                status="active",
            ),
            next_user_id,
        )

    return (
        UserPlanItem(
            id=next_user_id,
            display_name=SUPERADMIN_DISPLAY_NAME,
            display_name_normalized=normalized,
            telegram_id=SUPERADMIN_TELEGRAM_ID,
            role="superadmin",
            status="active",
            action="create",
        ),
        next_user_id + 1,
    )


def existing_user_item(
    row: sqlite3.Row,
    *,
    display_name: str,
    normalized: str,
    telegram_id: int | None,
    role: str,
    status: str,
) -> UserPlanItem:
    expected = {
        "display_name": display_name,
        "display_name_normalized": normalized,
        "telegram_id": telegram_id,
        "role": role,
        "status": status,
    }
    actual = {
        "display_name": clean_text(row["display_name"]),
        "display_name_normalized": normalized_user_name(row),
        "telegram_id": row["telegram_id"],
        "role": clean_text(row["role"]),
        "status": clean_text(row["status"]),
    }
    return UserPlanItem(
        display_name=display_name,
        display_name_normalized=normalized,
        telegram_id=telegram_id,
        role=role,
        status=status,
        action="unchanged" if actual == expected else "update",
        existing_id=int(row["id"]),
    )


def unique_player_names(rows: tuple[SourceRow, ...]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = clean_text(row.raw_player_name)
        normalized = normalize_display_name(name)
        key = normalized or name
        if key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def resolve_users(
    connection: sqlite3.Connection,
    rows: tuple[SourceRow, ...],
    mappings: dict[str, str],
    aliases: dict[str, int],
    *,
    user_items: list[UserPlanItem] | None = None,
) -> tuple[list[ResolvedResultRow], list[UnresolvedUser], list[AmbiguousUser]]:
    resolved: list[ResolvedResultRow] = []
    unresolved: list[UnresolvedUser] = []
    ambiguous: list[AmbiguousUser] = []
    users_by_normalized = load_users_by_normalized(connection)
    users_by_id = load_users_by_id(connection)
    apply_planned_user_candidates(users_by_normalized, users_by_id, user_items or [])

    for row in rows:
        mapped_name = mappings.get(row.raw_player_name, row.raw_player_name)
        alias_user_id = aliases.get(row.raw_player_name, aliases.get(mapped_name))
        if alias_user_id is not None:
            user = users_by_id.get(alias_user_id)
            if user is None:
                unresolved.append(
                    UnresolvedUser(
                        source_row=row.source_row,
                        raw_player_name=row.raw_player_name,
                        mapped_name=mapped_name,
                        display_name_normalized=None,
                        reason=f"alias_user_id_not_found:{alias_user_id}",
                    )
                )
                continue
            resolved.append(resolved_result(row, mapped_name, user))
            continue

        normalized = normalize_display_name(mapped_name)
        if normalized is None:
            unresolved.append(
                UnresolvedUser(
                    source_row=row.source_row,
                    raw_player_name=row.raw_player_name,
                    mapped_name=mapped_name,
                    display_name_normalized=None,
                    reason="empty_normalized_name",
                )
            )
            continue
        candidates = users_by_normalized.get(normalized, [])
        if not candidates:
            unresolved.append(
                UnresolvedUser(
                    source_row=row.source_row,
                    raw_player_name=row.raw_player_name,
                    mapped_name=mapped_name,
                    display_name_normalized=normalized,
                    reason="user_not_found",
                )
            )
            continue
        if len(candidates) > 1:
            ambiguous.append(
                AmbiguousUser(
                    source_row=row.source_row,
                    raw_player_name=row.raw_player_name,
                    mapped_name=mapped_name,
                    display_name_normalized=normalized,
                    candidates=tuple(candidates),
                )
            )
            continue
        resolved.append(resolved_result(row, mapped_name, candidates[0]))

    return resolved, unresolved, ambiguous


def resolved_result(
    row: SourceRow,
    mapped_name: str,
    user: UserCandidate,
) -> ResolvedResultRow:
    return ResolvedResultRow(
        source_row=row.source_row,
        tournament_date=row.tournament_date,
        raw_player_name=row.raw_player_name,
        mapped_name=mapped_name,
        user_id=user.id,
        display_name=user.display_name,
        place=row.place,
        knockouts_count=row.knockouts_count,
        big_knockouts_count=row.big_knockouts_count,
        bonus_points=row.bonus_points,
        tournament_points=row.tournament_points,
        knockout_points=row.knockout_points,
    )


def clear_duplicate_prize_places(rows: list[ResolvedResultRow]) -> list[ResolvedResultRow]:
    seen_places: set[tuple[date, int]] = set()
    result: list[ResolvedResultRow] = []
    for row in rows:
        if row.place is None:
            result.append(row)
            continue
        key = (row.tournament_date, row.place)
        if key in seen_places:
            result.append(replace(row, place=None))
            continue
        seen_places.add(key)
        result.append(row)
    return result


def load_users_by_normalized(
    connection: sqlite3.Connection,
) -> dict[str, list[UserCandidate]]:
    result: dict[str, list[UserCandidate]] = defaultdict(list)
    for row in connection.execute(
        """
        SELECT id, display_name, display_name_normalized
        FROM users
        ORDER BY id
        """
    ):
        normalized = normalized_user_name(row)
        if normalized is None:
            continue
        result[normalized].append(
            UserCandidate(
                id=int(row["id"]),
                display_name=clean_text(row["display_name"]),
                display_name_normalized=normalized,
            )
        )
    return result


def load_users_by_id(connection: sqlite3.Connection) -> dict[int, UserCandidate]:
    users: dict[int, UserCandidate] = {}
    for row in connection.execute(
        "SELECT id, display_name, display_name_normalized FROM users ORDER BY id"
    ):
        normalized = normalized_user_name(row)
        if normalized is None:
            continue
        users[int(row["id"])] = UserCandidate(
            id=int(row["id"]),
            display_name=clean_text(row["display_name"]),
            display_name_normalized=normalized,
        )
    return users


def load_user_rows_by_id(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {
        int(row["id"]): row
        for row in connection.execute(
            """
            SELECT id, display_name, display_name_normalized, telegram_id, role, status
            FROM users
            ORDER BY id
            """
        )
    }


def load_users_by_telegram(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {
        int(row["telegram_id"]): row
        for row in connection.execute(
            """
            SELECT id, display_name, display_name_normalized, telegram_id, role, status
            FROM users
            WHERE telegram_id IS NOT NULL
            ORDER BY id
            """
        )
    }


def max_existing_user_id(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COALESCE(MAX(id), 0) FROM users").fetchone()[0])


def apply_planned_user_candidates(
    users_by_normalized: dict[str, list[UserCandidate]],
    users_by_id: dict[int, UserCandidate],
    user_items: list[UserPlanItem],
) -> None:
    for item in user_items:
        user_id = item.id if item.action == "create" else item.existing_id
        if user_id is None or item.action == "conflict":
            continue
        candidate = UserCandidate(
            id=user_id,
            display_name=item.display_name,
            display_name_normalized=item.display_name_normalized,
        )
        users_by_id[user_id] = candidate
        existing_candidates = users_by_normalized.setdefault(item.display_name_normalized, [])
        if all(existing.id != user_id for existing in existing_candidates):
            existing_candidates.append(candidate)


def build_tournament_plan(
    connection: sqlite3.Connection,
    source: ImportSource,
    resolved_rows: list[ResolvedResultRow],
    legacy_type_id: int,
    *,
    strict_expectations: bool = True,
) -> tuple[list[TournamentPlanItem], dict[str, int], list[str]]:
    rows_by_date: dict[date, list[ResolvedResultRow]] = defaultdict(list)
    for row in resolved_rows:
        rows_by_date[row.tournament_date].append(row)
    season_distribution: dict[str, int] = Counter()
    items: list[TournamentPlanItem] = []
    errors: list[str] = []
    for tournament_date in sorted(source_dates(source)):
        season = find_season_for_date(connection, tournament_date)
        if season is None:
            errors.append(f"No existing season covers {tournament_date.isoformat()}.")
            continue
        season_distribution[season["name"]] += 1
        tournament_fund = None
        existing = connection.execute(
            """
            SELECT id, season_id, tournament_type_id, date, tournament_fund, status
            FROM tournaments
            WHERE date = ?
            """,
            (tournament_date.isoformat(),),
        ).fetchone()
        conflict = None
        action = "create"
        existing_id = None
        if existing is not None:
            existing_id = int(existing["id"])
            expected = {
                "season_id": int(season["id"]),
                "tournament_type_id": legacy_type_id,
                "tournament_fund": None,
                "status": "closed",
            }
            actual = {
                "season_id": int(existing["season_id"]),
                "tournament_type_id": int(existing["tournament_type_id"]),
                "tournament_fund": (
                    None
                    if existing["tournament_fund"] is None
                    else required_int(existing["tournament_fund"])
                ),
                "status": str(existing["status"]),
            }
            if actual == expected:
                action = "unchanged"
            else:
                action = "conflict"
                conflict = json.dumps({"expected": expected, "actual": actual}, ensure_ascii=False)
        items.append(
            TournamentPlanItem(
                tournament_date=tournament_date,
                season_id=int(season["id"]),
                season_name=str(season["name"]),
                tournament_type_id=legacy_type_id,
                tournament_fund=tournament_fund,
                action=action,
                existing_id=existing_id,
                conflict=conflict,
            )
        )

    expected = EXPECTED_TOURNAMENT_DISTRIBUTION
    actual = {name: season_distribution.get(name, 0) for name in expected}
    if strict_expectations and actual != expected:
        errors.append(
            f"Unexpected tournament distribution by season: expected {expected}, got {actual}."
        )
    return items, actual, errors


def build_result_plan(
    connection: sqlite3.Connection,
    resolved_rows: list[ResolvedResultRow],
    tournament_items: list[TournamentPlanItem],
    *,
    update_existing: bool,
) -> list[ResultPlanItem]:
    tournament_ids_by_date = {
        item.tournament_date: item.existing_id
        for item in tournament_items
        if item.existing_id is not None
    }
    result_items: list[ResultPlanItem] = []
    for row in resolved_rows:
        existing_id = None
        action = "create"
        conflict = None
        diff: dict[str, tuple[Any, Any]] = {}
        tournament_id = tournament_ids_by_date.get(row.tournament_date)
        if tournament_id is not None:
            existing = connection.execute(
                """
                SELECT *
                FROM tournament_results
                WHERE tournament_id = ? AND player_id = ?
                """,
                (tournament_id, row.user_id),
            ).fetchone()
            if existing is not None:
                existing_id = int(existing["id"])
                diff = result_diff(existing, row)
                if not diff:
                    action = "unchanged"
                elif update_existing:
                    action = "update"
                else:
                    action = "conflict"
                    conflict = json.dumps(diff, ensure_ascii=False, default=str)
        result_items.append(
            ResultPlanItem(
                source_row=row.source_row,
                tournament_date=row.tournament_date,
                user_id=row.user_id,
                display_name=row.display_name,
                action=action,
                existing_id=existing_id,
                conflict=conflict,
                diff=diff,
            )
        )
    return result_items


def result_diff(existing: sqlite3.Row, row: ResolvedResultRow) -> dict[str, tuple[Any, Any]]:
    expected = {
        "place": row.place,
        "knockouts_count": row.knockouts_count,
        "big_knockouts_count": row.big_knockouts_count,
        "bonus_points": str(row.bonus_points),
        "tournament_points": money(row.tournament_points),
        "knockout_points": money(row.knockout_points),
    }
    actual = {
        "place": existing["place"],
        "knockouts_count": existing["knockouts_count"],
        "big_knockouts_count": existing["big_knockouts_count"],
        "bonus_points": str(required_int(existing["bonus_points"])),
        "tournament_points": money(decimal_from_db(existing["tournament_points"])),
        "knockout_points": money(decimal_from_db(existing["knockout_points"])),
    }
    return {key: (actual[key], expected[key]) for key in expected if actual[key] != expected[key]}


def validate_result_rows(rows: list[ResolvedResultRow]) -> list[str]:
    seen: dict[tuple[date, int], int] = {}
    places_by_tournament: dict[tuple[date, int], int] = {}
    errors: list[str] = []
    for row in rows:
        if row.place is not None and row.place not in {1, 2, 3, 4, 5}:
            errors.append(
                f"Invalid place in import source: row {row.source_row}, "
                f"{row.tournament_date.isoformat()}, place={row.place}."
            )
        key = (row.tournament_date, row.user_id)
        previous_row = seen.get(key)
        if previous_row is not None:
            errors.append(
                "Duplicate result in import source after mapping: "
                f"{row.tournament_date.isoformat()} user_id={row.user_id} "
                f"rows {previous_row} and {row.source_row}."
            )
        else:
            seen[key] = row.source_row
        if row.place is not None:
            place_key = (row.tournament_date, row.place)
            previous_place_row = places_by_tournament.get(place_key)
            if previous_place_row is not None:
                errors.append(
                    "Duplicate prize place in import source: "
                    f"{row.tournament_date.isoformat()} place={row.place} "
                    f"rows {previous_place_row} and {row.source_row}."
                )
            else:
                places_by_tournament[place_key] = row.source_row
    return errors


def apply_import_plan(plan: ImportPlan) -> ApplyStats:
    if not plan.safe_to_apply:
        raise ImportValidationError("Plan is NOT SAFE TO APPLY.")
    if not plan.db_path.is_file():
        raise ImportValidationError(f"Database file does not exist: {plan.db_path}")

    connection = connect_existing_database(plan.db_path)
    try:
        connection.execute("BEGIN")
        user_stats = apply_users(connection, plan.user_items)
        tournament_ids = apply_tournaments(connection, plan.tournament_items)
        stats = apply_results(
            connection,
            plan.resolved_rows,
            plan.result_items,
            tournament_ids,
        )
        connection.commit()
        return ApplyStats(
            users_created=user_stats["created"],
            users_updated=user_stats["updated"],
            users_unchanged=user_stats["unchanged"],
            tournaments_created=sum(1 for item in plan.tournament_items if item.action == "create"),
            tournaments_unchanged=sum(
                1 for item in plan.tournament_items if item.action == "unchanged"
            ),
            results_created=stats["created"],
            results_updated=stats["updated"],
            results_unchanged=stats["unchanged"],
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_tournaments(
    connection: sqlite3.Connection,
    items: list[TournamentPlanItem],
) -> dict[date, int]:
    tournament_ids: dict[date, int] = {}
    for item in items:
        if item.action == "unchanged":
            assert item.existing_id is not None
            tournament_ids[item.tournament_date] = item.existing_id
            continue
        if item.action != "create":
            raise ImportValidationError(f"Cannot apply tournament action {item.action}.")
        cursor = connection.execute(
            """
            INSERT INTO tournaments (
                season_id,
                tournament_type_id,
                date,
                tournament_fund,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                item.season_id,
                item.tournament_type_id,
                item.tournament_date.isoformat(),
                item.tournament_fund,
            ),
        )
        tournament_ids[item.tournament_date] = int(cursor.lastrowid)
    return tournament_ids


def apply_users(
    connection: sqlite3.Connection,
    items: list[UserPlanItem],
) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for item in items:
        if item.action == "unchanged":
            stats["unchanged"] += 1
            continue
        if item.action == "create":
            if item.id is None:
                raise ImportValidationError("Cannot create user without planned id.")
            connection.execute(
                """
                INSERT INTO users (
                    id,
                    display_name,
                    display_name_normalized,
                    telegram_id,
                    role,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    item.id,
                    item.display_name,
                    item.display_name_normalized,
                    item.telegram_id,
                    item.role,
                    item.status,
                ),
            )
            stats["created"] += 1
            continue
        if item.action == "update":
            if item.existing_id is None:
                raise ImportValidationError("Cannot update user without existing id.")
            connection.execute(
                """
                UPDATE users
                SET display_name = ?,
                    display_name_normalized = ?,
                    telegram_id = ?,
                    role = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    item.display_name,
                    item.display_name_normalized,
                    item.telegram_id,
                    item.role,
                    item.status,
                    item.existing_id,
                ),
            )
            stats["updated"] += 1
            continue
        raise ImportValidationError(f"Cannot apply user action {item.action}.")
    return stats


def apply_results(
    connection: sqlite3.Connection,
    rows: list[ResolvedResultRow],
    items: list[ResultPlanItem],
    tournament_ids: dict[date, int],
) -> dict[str, int]:
    items_by_source_row = {item.source_row: item for item in items}
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for row in rows:
        item = items_by_source_row[row.source_row]
        tournament_id = tournament_ids[row.tournament_date]
        if item.action == "unchanged":
            stats["unchanged"] += 1
            continue
        if item.action == "create":
            connection.execute(
                """
                INSERT INTO tournament_results (
                    tournament_id,
                    player_id,
                    source,
                    checked_in_at,
                    place,
                    knockouts_count,
                    big_knockouts_count,
                    tournament_points,
                    knockout_points,
                    bonus_points,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                result_values(tournament_id, row),
            )
            stats["created"] += 1
            continue
        if item.action == "update":
            connection.execute(
                """
                UPDATE tournament_results
                SET place = ?,
                    knockouts_count = ?,
                    big_knockouts_count = ?,
                    tournament_points = ?,
                    knockout_points = ?,
                    bonus_points = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    row.place,
                    row.knockouts_count,
                    row.big_knockouts_count,
                    money(row.tournament_points),
                    money(row.knockout_points),
                    row.bonus_points,
                    item.existing_id,
                ),
            )
            stats["updated"] += 1
            continue
        raise ImportValidationError(f"Cannot apply result action {item.action}.")
    return stats


def result_values(tournament_id: int, row: ResolvedResultRow) -> tuple[Any, ...]:
    return (
        tournament_id,
        row.user_id,
        "walk_in_existing",
        row.place,
        row.knockouts_count,
        row.big_knockouts_count,
        money(row.tournament_points),
        money(row.knockout_points),
        row.bonus_points,
    )


def verify_post_import(db_path: Path, plan: ImportPlan) -> dict[str, Any]:
    connection = connect_existing_database(db_path)
    try:
        source_date_count = len(source_dates(plan.source))
        source_result_count = len(plan.resolved_rows)
        checks: dict[str, Any] = {
            "seasons": [
                dict(row)
                for row in connection.execute(
                    "SELECT id, name, starts_at, ends_at FROM seasons ORDER BY starts_at"
                )
            ],
            "tournament_count": scalar(connection, "SELECT COUNT(*) FROM tournaments"),
            "source_date_count": source_date_count,
            "closed_imported_tournaments": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM tournaments t
                JOIN tournament_types tt ON tt.id = t.tournament_type_id
                WHERE t.status = 'closed' AND tt.code = 'legacy_unknown'
                """,
            ),
            "duplicate_tournament_dates": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT date
                    FROM tournaments
                    GROUP BY date
                    HAVING COUNT(*) > 1
                )
                """,
            ),
            "duplicate_results": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT tournament_id, player_id
                    FROM tournament_results
                    GROUP BY tournament_id, player_id
                    HAVING COUNT(*) > 1
                )
                """,
            ),
            "orphan_results": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM tournament_results r
                LEFT JOIN tournaments t ON t.id = r.tournament_id
                LEFT JOIN users u ON u.id = r.player_id
                WHERE t.id IS NULL OR u.id IS NULL
                """,
            ),
            "negative_results": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM tournament_results
                WHERE knockouts_count < 0
                   OR big_knockouts_count < 0
                   OR tournament_points < 0
                   OR knockout_points < 0
                   OR bonus_points < 0
                """,
            ),
            "result_count_for_source_dates": result_count_for_plan_dates(connection, plan),
            "source_result_count": source_result_count,
            "plan_points": plan_points(plan.resolved_rows),
            "db_points": db_points_for_plan_dates(connection, plan),
            "season_distribution": tournament_distribution_for_plan_dates(connection, plan),
            "top20_plan": top20_from_plan(plan.resolved_rows),
            "top20_db": top20_from_db(connection),
        }
        checks["ok"] = (
            len(checks["seasons"]) == 3
            and checks["tournament_count"] >= source_date_count
            and checks["closed_imported_tournaments"] >= source_date_count
            and checks["duplicate_tournament_dates"] == 0
            and checks["duplicate_results"] == 0
            and checks["orphan_results"] == 0
            and checks["negative_results"] == 0
            and checks["result_count_for_source_dates"] == source_result_count
            and checks["plan_points"] == checks["db_points"]
        )
        return checks
    finally:
        connection.close()


def connect_existing_database(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise ImportValidationError(f"Database file does not exist: {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def validate_required_database_state(connection: sqlite3.Connection) -> None:
    required_tables = {"users", "seasons", "tournament_types", "tournaments", "tournament_results"}
    existing_tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    }
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        raise ImportValidationError(f"Database is missing tables: {', '.join(missing_tables)}.")
    get_required_tournament_type_id(connection, LEGACY_TOURNAMENT_TYPE_CODE)


def get_required_tournament_type_id(connection: sqlite3.Connection, code: str) -> int:
    row = connection.execute(
        "SELECT id FROM tournament_types WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        raise ImportValidationError(f"Tournament type {code!r} does not exist.")
    return int(row["id"])


def find_season_for_date(connection: sqlite3.Connection, value: date) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, name, starts_at, ends_at
        FROM seasons
        WHERE starts_at <= ? AND (ends_at IS NULL OR ends_at >= ?)
        ORDER BY starts_at DESC, id DESC
        LIMIT 1
        """,
        (value.isoformat(), value.isoformat()),
    ).fetchone()


def source_dates(source: ImportSource) -> set[date]:
    return {
        *(row.tournament_date for row in source.result_rows),
        *(row.tournament_date for row in source.blank_player_rows),
    }


def print_report(plan: ImportPlan) -> None:
    summary = report_summary(plan)
    print_json("Historical rating import dry-run", summary)
    if plan.unresolved_users:
        print("\nFirst unresolved users:")
        for item in plan.unresolved_users[:20]:
            print(
                f"row {item.source_row}: {item.raw_player_name!r} -> "
                f"{item.mapped_name!r} ({item.reason})"
            )
    if plan.ambiguous_users:
        print("\nFirst ambiguous users:")
        for item in plan.ambiguous_users[:20]:
            candidates = ", ".join(
                f"{candidate.id}:{candidate.display_name}" for candidate in item.candidates
            )
            print(
                f"row {item.source_row}: {item.raw_player_name!r} -> "
                f"{item.mapped_name!r} candidates [{candidates}]"
            )
    if plan.source.blank_player_rows:
        print("\nFirst blank-player rows:")
        for item in plan.source.blank_player_rows[:20]:
            print(
                f"row {item.source_row}: {item.tournament_date.isoformat()} "
                f"place={item.place} KO={item.knockouts_count} "
                f"big={item.big_knockouts_count} tournament_points={money(item.tournament_points)} "
                f"knockout_points={money(item.knockout_points)} bonus={item.bonus_points}"
            )
    print(f"\nVerdict: {'SAFE TO APPLY' if plan.safe_to_apply else 'NOT SAFE TO APPLY'}")


def report_summary(plan: ImportPlan) -> dict[str, Any]:
    unique_dates = source_dates(plan.source)
    user_actions = Counter(item.action for item in plan.user_items)
    tournament_actions = Counter(item.action for item in plan.tournament_items)
    result_actions = Counter(item.action for item in plan.result_items)
    superadmin_item = next(
        item for item in plan.user_items if item.telegram_id == SUPERADMIN_TELEGRAM_ID
    )
    return {
        "source": str(plan.source.path),
        "source_format": plan.source.source_format,
        "results_sheet": plan.source.results_sheet,
        "mapping_sheet": plan.source.mapping_sheet,
        "db_path": str(plan.db_path),
        "superadmin": {
            "display_name": superadmin_item.display_name,
            "telegram_id": superadmin_item.telegram_id,
            "role": superadmin_item.role,
            "status": superadmin_item.status,
            "action": superadmin_item.action,
            "id": superadmin_item.id or superadmin_item.existing_id,
        },
        "date_min": min(unique_dates).isoformat() if unique_dates else None,
        "date_max": max(unique_dates).isoformat() if unique_dates else None,
        "unique_tournaments": len(unique_dates),
        "dated_source_rows": plan.source.dated_rows_count,
        "importable_result_rows": len(plan.source.result_rows),
        "blank_player_rows": len(plan.source.blank_player_rows),
        "blank_player_rows_intentionally_skipped": len(plan.source.blank_player_rows),
        "resolved_result_rows": len(plan.resolved_rows),
        "unresolved_rows": len(plan.unresolved_users),
        "ambiguous_rows": len(plan.ambiguous_users),
        "unique_users": len({row.user_id for row in plan.resolved_rows}),
        "raw_players": len({row.raw_player_name for row in plan.source.result_rows}),
        "mapped_players": len({row.mapped_name for row in plan.resolved_rows}),
        "users": dict(user_actions),
        "season_distribution": plan.season_distribution,
        "tournaments": dict(tournament_actions),
        "results": dict(result_actions),
        "placed_results": sum(1 for row in plan.resolved_rows if row.place is not None),
        "results_with_ko": sum(1 for row in plan.resolved_rows if row.knockouts_count > 0),
        "results_with_big_ko": sum(1 for row in plan.resolved_rows if row.big_knockouts_count > 0),
        "points": plan_points(plan.resolved_rows),
        "errors": plan.errors[:20],
        "verdict": "SAFE TO APPLY" if plan.safe_to_apply else "NOT SAFE TO APPLY",
    }


def print_apply_stats(stats: ApplyStats, db_path: Path) -> None:
    print_json(
        "Historical rating import apply",
        {
            "db_path": str(db_path),
            **asdict(stats),
        },
    )


def print_json(title: str, payload: dict[str, Any]) -> None:
    print(title)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))


def export_report(directory: Path, plan: ImportPlan) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(report_summary(plan), ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    write_csv_report(
        directory / "users.csv",
        [
            {
                "id": item.id or item.existing_id or "",
                "display_name": item.display_name,
                "display_name_normalized": item.display_name_normalized,
                "telegram_id": item.telegram_id or "",
                "role": item.role,
                "status": item.status,
                "action": item.action,
                "conflict": item.conflict or "",
            }
            for item in plan.user_items
        ],
    )
    write_csv_report(
        directory / "tournaments.csv",
        [
            {
                "date": item.tournament_date.isoformat(),
                "season_id": item.season_id,
                "season_name": item.season_name,
                "tournament_type_id": item.tournament_type_id,
                "tournament_fund": ""
                if item.tournament_fund is None
                else money(item.tournament_fund),
                "action": item.action,
                "existing_id": item.existing_id or "",
                "conflict": item.conflict or "",
            }
            for item in plan.tournament_items
        ],
    )
    write_csv_report(
        directory / "results.csv",
        [
            {
                "source_row": item.source_row,
                "date": item.tournament_date.isoformat(),
                "user_id": item.user_id,
                "display_name": item.display_name,
                "action": item.action,
                "existing_id": item.existing_id or "",
                "conflict": item.conflict or "",
            }
            for item in plan.result_items
        ],
    )
    write_csv_report(
        directory / "unresolved_users.csv",
        [
            {
                "source_row": item.source_row,
                "raw_player_name": item.raw_player_name,
                "mapped_name": item.mapped_name,
                "display_name_normalized": item.display_name_normalized or "",
                "reason": item.reason,
            }
            for item in plan.unresolved_users
        ],
    )
    write_csv_report(
        directory / "ambiguous_users.csv",
        [
            {
                "source_row": item.source_row,
                "raw_player_name": item.raw_player_name,
                "mapped_name": item.mapped_name,
                "display_name_normalized": item.display_name_normalized or "",
                "candidate_ids": ",".join(str(candidate.id) for candidate in item.candidates),
                "candidate_names": " | ".join(
                    candidate.display_name for candidate in item.candidates
                ),
            }
            for item in plan.ambiguous_users
        ],
    )
    write_csv_report(
        directory / "blank_player_rows.csv",
        blank_player_report_rows(plan),
    )
    write_csv_report(
        directory / "blank_players.csv",
        blank_player_report_rows(plan),
    )
    export_report_rest(directory, plan)


def blank_player_report_rows(plan: ImportPlan) -> list[dict[str, Any]]:
    return [
        {
            "source_row": item.source_row,
            "date": item.tournament_date.isoformat(),
            "place": item.place or "",
            "knockouts_count": item.knockouts_count,
            "big_knockouts_count": item.big_knockouts_count,
            "tournament_points": money(item.tournament_points),
            "knockout_points": money(item.knockout_points),
            "bonus_points": str(item.bonus_points),
            "reason": item.reason,
        }
        for item in plan.source.blank_player_rows
    ]


def export_report_rest(directory: Path, plan: ImportPlan) -> None:
    write_csv_report(
        directory / "tournament_conflicts.csv",
        [
            {
                "date": item.tournament_date.isoformat(),
                "existing_id": item.existing_id or "",
                "conflict": item.conflict or "",
            }
            for item in plan.tournament_items
            if item.action == "conflict"
        ],
    )
    write_csv_report(
        directory / "result_conflicts.csv",
        [
            {
                "source_row": item.source_row,
                "date": item.tournament_date.isoformat(),
                "user_id": item.user_id,
                "display_name": item.display_name,
                "existing_id": item.existing_id or "",
                "conflict": item.conflict or "",
            }
            for item in plan.result_items
            if item.action == "conflict"
        ],
    )


def write_csv_report(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plan_points(rows: list[ResolvedResultRow]) -> dict[str, str]:
    return {
        "tournament_points": money(sum((row.tournament_points for row in rows), ZERO)),
        "knockout_points": money(sum((row.knockout_points for row in rows), ZERO)),
        "bonus_points": str(sum(row.bonus_points for row in rows)),
        "total_points": money(
            sum(
                (row.tournament_points + row.knockout_points + row.bonus_points for row in rows),
                ZERO,
            )
        ),
    }


def db_points_for_plan_dates(connection: sqlite3.Connection, plan: ImportPlan) -> dict[str, str]:
    placeholders = ",".join("?" for _ in source_dates(plan.source))
    row = connection.execute(
        f"""
        SELECT
            COALESCE(SUM(r.tournament_points), 0) AS tournament_points,
            COALESCE(SUM(r.knockout_points), 0) AS knockout_points,
            COALESCE(SUM(r.bonus_points), 0) AS bonus_points
        FROM tournament_results r
        JOIN tournaments t ON t.id = r.tournament_id
        WHERE t.date IN ({placeholders})
        """,
        [item.isoformat() for item in sorted(source_dates(plan.source))],
    ).fetchone()
    tournament_points = decimal_from_db(row["tournament_points"])
    knockout_points = decimal_from_db(row["knockout_points"])
    bonus_points = decimal_from_db(row["bonus_points"])
    return {
        "tournament_points": money(tournament_points),
        "knockout_points": money(knockout_points),
        "bonus_points": str(int(bonus_points)),
        "total_points": money(tournament_points + knockout_points + bonus_points),
    }


def result_count_for_plan_dates(connection: sqlite3.Connection, plan: ImportPlan) -> int:
    placeholders = ",".join("?" for _ in source_dates(plan.source))
    return int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM tournament_results r
            JOIN tournaments t ON t.id = r.tournament_id
            WHERE t.date IN ({placeholders})
            """,
            [item.isoformat() for item in sorted(source_dates(plan.source))],
        ).fetchone()[0]
    )


def tournament_distribution_for_plan_dates(
    connection: sqlite3.Connection,
    plan: ImportPlan,
) -> dict[str, int]:
    placeholders = ",".join("?" for _ in source_dates(plan.source))
    return {
        str(row["name"]): int(row["count"])
        for row in connection.execute(
            f"""
            SELECT s.name, COUNT(*) AS count
            FROM tournaments t
            JOIN seasons s ON s.id = t.season_id
            WHERE t.date IN ({placeholders})
            GROUP BY s.name
            ORDER BY s.starts_at
            """,
            [item.isoformat() for item in sorted(source_dates(plan.source))],
        )
    }


def top20_from_plan(rows: list[ResolvedResultRow]) -> list[dict[str, Any]]:
    totals: dict[int, dict[str, Any]] = {}
    for row in rows:
        item = totals.setdefault(
            row.user_id,
            {"user_id": row.user_id, "display_name": row.display_name, "points": ZERO},
        )
        item["points"] += row.tournament_points + row.knockout_points + row.bonus_points
    return [
        {
            "user_id": item["user_id"],
            "display_name": item["display_name"],
            "points": money(item["points"]),
        }
        for item in sorted(
            totals.values(),
            key=lambda item: (-item["points"], item["display_name"]),
        )[:20]
    ]


def top20_from_db(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "user_id": int(row["user_id"]),
            "display_name": str(row["display_name"]),
            "points": money(decimal_from_db(row["points"])),
        }
        for row in connection.execute(
            """
            SELECT u.id AS user_id,
                   u.display_name,
                   SUM(r.tournament_points + r.knockout_points + r.bonus_points) AS points
            FROM tournament_results r
            JOIN users u ON u.id = r.player_id
            GROUP BY u.id, u.display_name
            ORDER BY points DESC, u.display_name
            LIMIT 20
            """
        )
    ]


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value)
    text = "".join(char for char in text if unicodedata.category(char) not in {"Cf", "Cc"})
    return " ".join(text.split()).strip()


def normalized_user_name(row: sqlite3.Row) -> str | None:
    normalized = normalize_display_name(clean_text(row["display_name_normalized"]))
    if normalized is not None:
        return normalized
    return normalize_display_name(clean_text(row["display_name"]))


def optional_int(value: Any) -> int | None:
    if value is None or clean_text(value) == "":
        return None
    return required_int(value)


def required_int(value: Any) -> int:
    if value is None or clean_text(value) == "":
        return 0
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ImportValidationError(f"Invalid integer value: {value!r}") from error
    if number != number.to_integral_value():
        raise ImportValidationError(f"Invalid integer value: {value!r}")
    return int(number)


def required_decimal(value: Any) -> Decimal:
    if value is None or clean_text(value) == "":
        return ZERO
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise ImportValidationError(f"Invalid decimal value: {value!r}") from error


def decimal_from_db(value: Any) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"))


def money(value: Decimal | int) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def parse_excel_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float, Decimal)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    text = clean_text(value)
    if not text:
        raise ImportValidationError("Empty tournament date.")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.strptime(text, "%d.%m.%Y").date()
        except ValueError as error:
            raise ImportValidationError(f"Invalid tournament date: {value!r}") from error


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_date_or_none(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return asdict(value)
    return str(value)


class XlsxWorkbook:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    package_rel_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.shared_strings = self._load_shared_strings()
        self.sheet_paths = self._load_sheet_paths()

    def iter_records(
        self,
        sheet_name: str,
        required_columns: tuple[str, ...],
        *,
        allow_extra_columns: bool = False,
    ) -> list[tuple[int, dict[str, Any]]]:
        rows = list(self.iter_rows(sheet_name))
        if not rows:
            raise ImportValidationError(f"Sheet {sheet_name!r} is empty.")
        header = [clean_text(value) for value in rows[0][1]]
        missing = [column for column in required_columns if column not in header]
        if missing:
            raise ImportValidationError(
                f"Sheet {sheet_name!r} is missing columns: {', '.join(missing)}"
            )
        if not allow_extra_columns and tuple(header[: len(required_columns)]) != required_columns:
            raise ImportValidationError(
                f"Sheet {sheet_name!r} must start with columns: {required_columns}"
            )
        indexes = {column: header.index(column) for column in required_columns}
        records: list[tuple[int, dict[str, Any]]] = []
        for source_row, values in rows[1:]:
            if not any(value is not None and clean_text(value) != "" for value in values):
                continue
            records.append(
                (
                    source_row,
                    {
                        column: values[index] if index < len(values) else None
                        for column, index in indexes.items()
                    },
                )
            )
        return records

    def iter_rows(self, sheet_name: str) -> list[tuple[int, list[Any]]]:
        path = self.sheet_paths.get(sheet_name)
        if path is None:
            raise ImportValidationError(f"Sheet not found: {sheet_name!r}")
        root = ElementTree.fromstring(self.archive.read(path))
        rows: list[tuple[int, list[Any]]] = []
        for row_element in root.findall(f".//{self.namespace}sheetData/{self.namespace}row"):
            row_index = int(row_element.attrib["r"])
            values: dict[int, Any] = {}
            for cell in row_element.findall(f"{self.namespace}c"):
                reference = cell.attrib.get("r", "")
                column_index = column_index_from_reference(reference)
                values[column_index] = self._cell_value(cell)
            max_column = max(values, default=-1)
            rows.append((row_index, [values.get(index) for index in range(max_column + 1)]))
        return rows

    def _cell_value(self, cell: ElementTree.Element) -> Any:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            text_element = cell.find(f"{self.namespace}is/{self.namespace}t")
            return text_element.text if text_element is not None else ""
        value_element = cell.find(f"{self.namespace}v")
        if value_element is None:
            return None
        raw_value = value_element.text or ""
        if cell_type == "s":
            return self.shared_strings[int(raw_value)]
        if cell_type == "str":
            return raw_value
        try:
            number = Decimal(raw_value)
        except InvalidOperation:
            return raw_value
        if number == number.to_integral():
            return int(number)
        return number

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.archive.namelist():
            return []
        root = ElementTree.fromstring(self.archive.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall(f"{self.namespace}si"):
            parts = [text.text or "" for text in item.findall(f".//{self.namespace}t")]
            strings.append("".join(parts))
        return strings

    def _load_sheet_paths(self) -> dict[str, str]:
        workbook_root = ElementTree.fromstring(self.archive.read("xl/workbook.xml"))
        rel_root = ElementTree.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        relationships = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{self.package_rel_namespace}Relationship")
        }
        sheets: dict[str, str] = {}
        for sheet in workbook_root.findall(f".//{self.namespace}sheet"):
            name = sheet.attrib["name"]
            relationship_id = sheet.attrib[f"{self.rel_namespace}id"]
            target = relationships[relationship_id]
            sheets[name] = "xl/" + target.lstrip("/")
        return sheets


def column_index_from_reference(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return index - 1


if __name__ == "__main__":
    main()
