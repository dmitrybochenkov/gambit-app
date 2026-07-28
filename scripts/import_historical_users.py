#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.common.normalization import normalize_display_name  # noqa: E402
from app.db.models.enums import UserRole, UserStatus  # noqa: E402

REQUIRED_FIELDS = ("id", "display_name", "role", "status", "telegram_id")
OPTIONAL_FIELDS = ("display_name_normalized",)
DEFAULT_INPUT_FILENAME = "historical_users_with_admins.csv"
ActionKind = Literal["create", "unchanged"]


@dataclass(frozen=True)
class ImportUserRow:
    source_row: int
    id: int
    display_name: str
    display_name_normalized: str
    role: UserRole
    status: UserStatus
    telegram_id: int | None


@dataclass(frozen=True)
class ExistingUser:
    id: int
    display_name: str
    display_name_normalized: str
    telegram_id: int | None
    role: str
    status: str


@dataclass(frozen=True)
class ImportAction:
    kind: ActionKind
    row: ImportUserRow


@dataclass(frozen=True)
class ImportConflict:
    source_row: int
    user_id: int | None
    reason: str
    existing: dict[str, Any] | None
    incoming: dict[str, Any] | None
    diff: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class InvalidCsvRow:
    source_row: int
    reason: str
    raw: dict[str, str]


@dataclass(frozen=True)
class DuplicateCsvValue:
    field: str
    value: int
    source_rows: tuple[int, ...]


@dataclass(frozen=True)
class ImportStats:
    rows_read: int
    users_created: int
    users_skipped: int
    max_imported_id: int


@dataclass(frozen=True)
class ImportPlan:
    source: Path
    db_path: Path
    alembic_revision: str | None
    rows_read: int
    creates: tuple[ImportAction, ...]
    unchanged: tuple[ImportAction, ...]
    conflicts: tuple[ImportConflict, ...]
    invalid: tuple[InvalidCsvRow, ...]
    duplicate_ids: tuple[DuplicateCsvValue, ...]
    duplicate_telegram_ids: tuple[DuplicateCsvValue, ...]
    role_distribution: dict[str, int]
    status_distribution: dict[str, int]
    telegram_ids_count: int

    @property
    def verdict(self) -> str:
        if self.conflicts or self.invalid:
            return "NOT SAFE TO APPLY"
        return "SAFE TO APPLY"

    @property
    def is_safe_to_apply(self) -> bool:
        return self.verdict == "SAFE TO APPLY"


class ImportValidationError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical Gambit users into SQLite.")
    parser.add_argument("source", nargs="?", type=Path, help="Source CSV file")
    parser.add_argument(
        "--input",
        dest="input_path",
        type=Path,
        help="Source CSV file. Defaults to ../data/historical_users_with_admins.csv.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to gambit.db. Defaults to DATABASE_URL or ../data/gambit.db.",
    )
    parser.add_argument(
        "--export-report",
        type=Path,
        default=None,
        help="Directory for summary.json and CSV reports.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the import. Without this flag the script only performs a dry-run.",
    )
    args = parser.parse_args()

    try:
        source = resolve_input_path(positional_source=args.source, option_source=args.input_path)
        db_path = resolve_db_path(args.db or default_db_path())
        plan = build_import_plan(source=source, db_path=db_path)
        print_plan(plan)
        if args.export_report is not None:
            export_report(plan, args.export_report)
        if args.apply:
            stats = apply_import_plan(plan)
            print_apply_stats(stats)
    except ImportValidationError as exc:
        raise SystemExit(f"Import failed: {exc}") from exc


def resolve_input_path(
    *,
    positional_source: Path | None,
    option_source: Path | None,
) -> Path:
    if positional_source is not None and option_source is not None:
        raise ImportValidationError("Use either positional source or --input, not both.")
    return positional_source or option_source or default_input_path()


def default_input_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / DEFAULT_INPUT_FILENAME


def default_db_path() -> Path:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("sqlite+aiosqlite:///"):
        return Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    return Path(__file__).resolve().parents[1] / "data" / "gambit.db"


def resolve_db_path(db_path: Path) -> Path:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise ImportValidationError(f"Database file does not exist: {resolved}")
    if not resolved.is_file():
        raise ImportValidationError(f"Database path is not a file: {resolved}")
    return resolved


def load_rows(source: Path) -> list[ImportUserRow]:
    rows, invalid = load_rows_with_errors(source)
    if invalid:
        first = invalid[0]
        raise ImportValidationError(f"Row {first.source_row}: {first.reason}")
    duplicates = find_duplicate_csv_values(rows)
    if duplicates:
        duplicate = duplicates[0]
        rows_text = ", ".join(str(row) for row in duplicate.source_rows)
        raise ImportValidationError(
            f"Row {duplicate.source_rows[-1]}: duplicate {duplicate.field} "
            f"{duplicate.value}; rows: {rows_text}."
        )
    return rows


def load_rows_with_errors(source: Path) -> tuple[list[ImportUserRow], list[InvalidCsvRow]]:
    if not source.exists():
        raise ImportValidationError(f"CSV file not found: {source}")

    with source.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ImportValidationError("CSV header is missing.")
        missing_fields = [field for field in REQUIRED_FIELDS if field not in reader.fieldnames]
        if missing_fields:
            raise ImportValidationError(
                "CSV is missing required fields: " + ", ".join(missing_fields)
            )
        rows: list[ImportUserRow] = []
        invalid: list[InvalidCsvRow] = []
        for index, row in enumerate(reader, start=2):
            try:
                rows.append(_parse_row(row, source_row=index))
            except ImportValidationError as exc:
                invalid.append(InvalidCsvRow(source_row=index, reason=str(exc), raw=dict(row)))
    return rows, invalid


def build_import_plan(source: Path, db_path: Path) -> ImportPlan:
    resolved_db_path = resolve_db_path(db_path)
    rows, invalid = load_rows_with_errors(source)
    duplicate_ids, duplicate_telegram_ids = split_duplicate_csv_values(
        find_duplicate_csv_values(rows)
    )
    duplicate_conflicts = [
        conflict_from_duplicate(duplicate)
        for duplicate in (*duplicate_ids, *duplicate_telegram_ids)
    ]
    duplicate_source_rows = {
        source_row
        for duplicate in (*duplicate_ids, *duplicate_telegram_ids)
        for source_row in duplicate.source_rows
    }
    valid_unique_rows = [row for row in rows if row.source_row not in duplicate_source_rows]
    role_distribution = Counter(row.role.value for row in rows)
    status_distribution = Counter(row.status.value for row in rows)
    telegram_ids_count = sum(1 for row in rows if row.telegram_id is not None)

    connection = connect_existing_database(resolved_db_path)
    try:
        ensure_users_table(connection)
        alembic_revision = get_required_alembic_revision(connection)
        existing_by_id = load_existing_users_by_id(connection)
        existing_by_telegram_id = load_existing_users_by_telegram_id(connection)
        creates: list[ImportAction] = []
        unchanged: list[ImportAction] = []
        conflicts: list[ImportConflict] = [*duplicate_conflicts]
        for row in valid_unique_rows:
            existing = existing_by_id.get(row.id)
            if existing is not None:
                if existing_matches_row(existing, row):
                    unchanged.append(ImportAction(kind="unchanged", row=row))
                else:
                    conflicts.append(conflict_from_existing_user(existing, row))
                continue
            telegram_conflict = (
                existing_by_telegram_id.get(row.telegram_id)
                if row.telegram_id is not None
                else None
            )
            if telegram_conflict is not None:
                conflicts.append(conflict_from_telegram_id(telegram_conflict, row))
                continue
            creates.append(ImportAction(kind="create", row=row))
    finally:
        connection.close()

    return ImportPlan(
        source=source,
        db_path=resolved_db_path,
        alembic_revision=alembic_revision,
        rows_read=len(rows) + len(invalid),
        creates=tuple(creates),
        unchanged=tuple(unchanged),
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.source_row, item.reason))),
        invalid=tuple(sorted(invalid, key=lambda item: item.source_row)),
        duplicate_ids=tuple(duplicate_ids),
        duplicate_telegram_ids=tuple(duplicate_telegram_ids),
        role_distribution=dict(sorted(role_distribution.items())),
        status_distribution=dict(sorted(status_distribution.items())),
        telegram_ids_count=telegram_ids_count,
    )


def connect_existing_database(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=rw"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def ensure_users_table(connection: sqlite3.Connection) -> None:
    users_table = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()
    if users_table is None:
        raise ImportValidationError("Database does not contain required table: users.")


def get_required_alembic_revision(connection: sqlite3.Connection) -> str:
    version_table = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'alembic_version'
        """
    ).fetchone()
    if version_table is None:
        raise ImportValidationError("Database does not contain required table: alembic_version.")
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise ImportValidationError("Database alembic_version is empty.")
    return str(row["version_num"])


def load_existing_users_by_id(connection: sqlite3.Connection) -> dict[int, ExistingUser]:
    return {
        int(row["id"]): existing_user_from_row(row)
        for row in connection.execute(
            """
            SELECT id, display_name, display_name_normalized, telegram_id, role, status
            FROM users
            """
        )
    }


def load_existing_users_by_telegram_id(
    connection: sqlite3.Connection,
) -> dict[int, ExistingUser]:
    return {
        int(row["telegram_id"]): existing_user_from_row(row)
        for row in connection.execute(
            """
            SELECT id, display_name, display_name_normalized, telegram_id, role, status
            FROM users
            WHERE telegram_id IS NOT NULL
            """
        )
    }


def existing_user_from_row(row: sqlite3.Row) -> ExistingUser:
    return ExistingUser(
        id=int(row["id"]),
        display_name=str(row["display_name"]),
        display_name_normalized=str(row["display_name_normalized"]),
        telegram_id=int(row["telegram_id"]) if row["telegram_id"] is not None else None,
        role=str(row["role"]),
        status=str(row["status"]),
    )


def import_users(db_path: Path, rows: list[ImportUserRow]) -> ImportStats:
    plan = build_import_plan_from_rows(source=Path("<memory>"), db_path=db_path, rows=rows)
    return apply_import_plan(plan)


def build_import_plan_from_rows(
    *,
    source: Path,
    db_path: Path,
    rows: list[ImportUserRow],
) -> ImportPlan:
    resolved_db_path = resolve_db_path(db_path)
    duplicate_ids, duplicate_telegram_ids = split_duplicate_csv_values(
        find_duplicate_csv_values(rows)
    )
    duplicate_conflicts = [
        conflict_from_duplicate(duplicate)
        for duplicate in (*duplicate_ids, *duplicate_telegram_ids)
    ]
    duplicate_source_rows = {
        source_row
        for duplicate in (*duplicate_ids, *duplicate_telegram_ids)
        for source_row in duplicate.source_rows
    }
    valid_unique_rows = [row for row in rows if row.source_row not in duplicate_source_rows]
    role_distribution = Counter(row.role.value for row in rows)
    status_distribution = Counter(row.status.value for row in rows)
    telegram_ids_count = sum(1 for row in rows if row.telegram_id is not None)
    connection = connect_existing_database(resolved_db_path)
    try:
        ensure_users_table(connection)
        alembic_revision = get_required_alembic_revision(connection)
        existing_by_id = load_existing_users_by_id(connection)
        existing_by_telegram_id = load_existing_users_by_telegram_id(connection)
        creates: list[ImportAction] = []
        unchanged: list[ImportAction] = []
        conflicts: list[ImportConflict] = [*duplicate_conflicts]
        for row in valid_unique_rows:
            existing = existing_by_id.get(row.id)
            if existing is not None:
                if existing_matches_row(existing, row):
                    unchanged.append(ImportAction(kind="unchanged", row=row))
                else:
                    conflicts.append(conflict_from_existing_user(existing, row))
                continue
            telegram_conflict = (
                existing_by_telegram_id.get(row.telegram_id)
                if row.telegram_id is not None
                else None
            )
            if telegram_conflict is not None:
                conflicts.append(conflict_from_telegram_id(telegram_conflict, row))
                continue
            creates.append(ImportAction(kind="create", row=row))
    finally:
        connection.close()
    return ImportPlan(
        source=source,
        db_path=resolved_db_path,
        alembic_revision=alembic_revision,
        rows_read=len(rows),
        creates=tuple(creates),
        unchanged=tuple(unchanged),
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.source_row, item.reason))),
        invalid=(),
        duplicate_ids=tuple(duplicate_ids),
        duplicate_telegram_ids=tuple(duplicate_telegram_ids),
        role_distribution=dict(sorted(role_distribution.items())),
        status_distribution=dict(sorted(status_distribution.items())),
        telegram_ids_count=telegram_ids_count,
    )


def apply_import_plan(plan: ImportPlan) -> ImportStats:
    if not plan.is_safe_to_apply:
        reasons = [item.reason for item in plan.conflicts]
        reasons.extend(item.reason for item in plan.invalid)
        reason_text = "; ".join(reasons[:3])
        raise ImportValidationError(f"Import plan is NOT SAFE TO APPLY: {reason_text}.")
    connection = connect_existing_database(plan.db_path)
    try:
        ensure_users_table(connection)
        connection.execute("BEGIN")
        for action in plan.creates:
            insert_user(connection, action.row)
        _sync_sqlite_sequence(
            connection,
            max((action.row.id for action in (*plan.creates, *plan.unchanged)), default=0),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return ImportStats(
        rows_read=plan.rows_read,
        users_created=len(plan.creates),
        users_skipped=len(plan.unchanged),
        max_imported_id=max(
            (action.row.id for action in (*plan.creates, *plan.unchanged)),
            default=0,
        ),
    )


def insert_user(connection: sqlite3.Connection, row: ImportUserRow) -> None:
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
            row.id,
            row.display_name,
            row.display_name_normalized,
            row.telegram_id,
            row.role.value,
            row.status.value,
        ),
    )


def export_report(plan: ImportPlan, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(plan_summary(plan), ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    write_actions_csv(directory / "creates.csv", plan.creates)
    write_actions_csv(directory / "unchanged.csv", plan.unchanged)
    write_conflicts_csv(directory / "conflicts.csv", plan.conflicts)
    write_invalid_csv(directory / "invalid.csv", plan.invalid)


def plan_summary(plan: ImportPlan) -> dict[str, Any]:
    return {
        "source": str(plan.source),
        "db_path": str(plan.db_path),
        "alembic_revision": plan.alembic_revision,
        "rows_read": plan.rows_read,
        "create": len(plan.creates),
        "unchanged": len(plan.unchanged),
        "conflict": len(plan.conflicts),
        "invalid": len(plan.invalid),
        "role_distribution": plan.role_distribution,
        "status_distribution": plan.status_distribution,
        "telegram_ids_count": plan.telegram_ids_count,
        "duplicate_ids": [asdict(item) for item in plan.duplicate_ids],
        "duplicate_telegram_ids": [asdict(item) for item in plan.duplicate_telegram_ids],
        "verdict": plan.verdict,
    }


def write_actions_csv(path: Path, actions: tuple[ImportAction, ...]) -> None:
    fieldnames = (
        "source_row",
        "id",
        "display_name",
        "display_name_normalized",
        "telegram_id",
        "role",
        "status",
    )
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for action in sorted(actions, key=lambda item: item.row.source_row):
            writer.writerow(user_row_dict(action.row))


def write_conflicts_csv(path: Path, conflicts: tuple[ImportConflict, ...]) -> None:
    fieldnames = (
        "source_row",
        "user_id",
        "reason",
        "existing",
        "incoming",
        "diff",
    )
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for conflict in conflicts:
            writer.writerow(
                {
                    "source_row": conflict.source_row,
                    "user_id": conflict.user_id,
                    "reason": conflict.reason,
                    "existing": json.dumps(conflict.existing, ensure_ascii=False, sort_keys=True),
                    "incoming": json.dumps(conflict.incoming, ensure_ascii=False, sort_keys=True),
                    "diff": json.dumps(conflict.diff, ensure_ascii=False, sort_keys=True),
                }
            )


def write_invalid_csv(path: Path, invalid_rows: tuple[InvalidCsvRow, ...]) -> None:
    fieldnames = ("source_row", "reason", "raw")
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in invalid_rows:
            writer.writerow(
                {
                    "source_row": item.source_row,
                    "reason": item.reason,
                    "raw": json.dumps(item.raw, ensure_ascii=False, sort_keys=True),
                }
            )


def print_plan(plan: ImportPlan) -> None:
    print(f"Database: {plan.db_path}")
    print(f"Alembic revision: {plan.alembic_revision or 'unknown'}")
    print("Summary:")
    print(f"  total: {plan.rows_read}")
    print(f"  create: {len(plan.creates)}")
    print(f"  unchanged: {len(plan.unchanged)}")
    print(f"  conflicts: {len(plan.conflicts)}")
    print(f"  invalid: {len(plan.invalid)}")
    print(f"  verdict: {plan.verdict}")
    print(f"Rows read: {plan.rows_read}")
    print(f"Users to create: {len(plan.creates)}")
    print(f"Users unchanged: {len(plan.unchanged)}")
    print(f"Conflicts: {len(plan.conflicts)}")
    print(f"Invalid rows: {len(plan.invalid)}")
    print(f"Role distribution: {plan.role_distribution}")
    print(f"Status distribution: {plan.status_distribution}")
    print(f"Non-empty telegram_id: {plan.telegram_ids_count}")
    print(f"Duplicate ids in CSV: {len(plan.duplicate_ids)}")
    print(f"Duplicate telegram_id in CSV: {len(plan.duplicate_telegram_ids)}")
    print(f"Verdict: {plan.verdict}")


def print_apply_stats(stats: ImportStats) -> None:
    print(f"Rows read: {stats.rows_read}")
    print(f"Users created: {stats.users_created}")
    print(f"Users skipped: {stats.users_skipped}")
    print(f"Max imported ID: {stats.max_imported_id}")


def _parse_row(row: dict[str, str], source_row: int) -> ImportUserRow:
    user_id = _parse_required_positive_int(row.get("id"), field="id", source_row=source_row)
    display_name = (row.get("display_name") or "").strip()
    if not display_name:
        raise ImportValidationError("display_name is required.")
    display_name_normalized = normalize_display_name(display_name)
    if display_name_normalized is None:
        raise ImportValidationError("display_name is empty after normalization.")
    incoming_normalized = (row.get("display_name_normalized") or "").strip()
    if incoming_normalized and incoming_normalized != display_name_normalized:
        raise ImportValidationError(
            "display_name_normalized does not match normalize_display_name()."
        )

    return ImportUserRow(
        source_row=source_row,
        id=user_id,
        display_name=display_name,
        display_name_normalized=display_name_normalized,
        role=_parse_enum(UserRole, row.get("role"), field="role"),
        status=_parse_enum(UserStatus, row.get("status"), field="status"),
        telegram_id=_parse_telegram_id(row.get("telegram_id")),
    )


def _parse_required_positive_int(value: str | None, *, field: str, source_row: int) -> int:
    raw_value = (value or "").strip()
    if not raw_value:
        raise ImportValidationError(f"{field} is required.")
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ImportValidationError(f"{field} must be an integer.") from exc
    if parsed <= 0:
        raise ImportValidationError(f"{field} must be positive.")
    return parsed


def _parse_telegram_id(value: str | None) -> int | None:
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    if raw_value.endswith(".0"):
        raw_value = raw_value[:-2]
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ImportValidationError("telegram_id must be an integer.") from exc
    if parsed <= 0:
        raise ImportValidationError("telegram_id must be positive.")
    return parsed


def _parse_enum[EnumType](
    enum_class: type[EnumType],
    value: str | None,
    *,
    field: str,
) -> EnumType:
    raw_value = (value or "").strip()
    if not raw_value:
        raise ImportValidationError(f"{field} is required.")
    try:
        return enum_class(raw_value.casefold())
    except ValueError as exc:
        allowed = ", ".join(item.name for item in enum_class)
        raise ImportValidationError(
            f"invalid {field} {raw_value!r}. Allowed values: {allowed}."
        ) from exc


def find_duplicate_csv_values(rows: list[ImportUserRow]) -> list[DuplicateCsvValue]:
    ids: dict[int, list[int]] = {}
    telegram_ids: dict[int, list[int]] = {}
    for row in rows:
        ids.setdefault(row.id, []).append(row.source_row)
        if row.telegram_id is not None:
            telegram_ids.setdefault(row.telegram_id, []).append(row.source_row)
    duplicates = [
        DuplicateCsvValue(field="id", value=value, source_rows=tuple(source_rows))
        for value, source_rows in ids.items()
        if len(source_rows) > 1
    ]
    duplicates.extend(
        DuplicateCsvValue(field="telegram_id", value=value, source_rows=tuple(source_rows))
        for value, source_rows in telegram_ids.items()
        if len(source_rows) > 1
    )
    return sorted(duplicates, key=lambda item: (item.field, item.value))


def split_duplicate_csv_values(
    duplicates: list[DuplicateCsvValue],
) -> tuple[list[DuplicateCsvValue], list[DuplicateCsvValue]]:
    duplicate_ids = [item for item in duplicates if item.field == "id"]
    duplicate_telegram_ids = [item for item in duplicates if item.field == "telegram_id"]
    return duplicate_ids, duplicate_telegram_ids


def conflict_from_duplicate(duplicate: DuplicateCsvValue) -> ImportConflict:
    return ImportConflict(
        source_row=duplicate.source_rows[0],
        user_id=None,
        reason=f"duplicate {duplicate.field} in CSV",
        existing=None,
        incoming={
            "field": duplicate.field,
            "value": duplicate.value,
            "source_rows": list(duplicate.source_rows),
        },
        diff={},
    )


def existing_matches_row(existing: ExistingUser, row: ImportUserRow) -> bool:
    return existing_to_dict(existing) == incoming_to_dict(row)


def conflict_from_existing_user(existing: ExistingUser, row: ImportUserRow) -> ImportConflict:
    return ImportConflict(
        source_row=row.source_row,
        user_id=row.id,
        reason="same id exists with different data",
        existing=existing_to_dict(existing),
        incoming=incoming_to_dict(row),
        diff=diff_users(existing_to_dict(existing), incoming_to_dict(row)),
    )


def conflict_from_telegram_id(existing: ExistingUser, row: ImportUserRow) -> ImportConflict:
    return ImportConflict(
        source_row=row.source_row,
        user_id=row.id,
        reason="new id uses occupied telegram_id",
        existing=existing_to_dict(existing),
        incoming=incoming_to_dict(row),
        diff={"telegram_id": {"existing": existing.telegram_id, "incoming": row.telegram_id}},
    )


def user_row_dict(row: ImportUserRow) -> dict[str, Any]:
    return {
        "source_row": row.source_row,
        "id": row.id,
        "display_name": row.display_name,
        "display_name_normalized": row.display_name_normalized,
        "telegram_id": row.telegram_id,
        "role": row.role.value,
        "status": row.status.value,
    }


def incoming_to_dict(row: ImportUserRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "display_name_normalized": row.display_name_normalized,
        "telegram_id": row.telegram_id,
        "role": row.role.value,
        "status": row.status.value,
    }


def existing_to_dict(user: ExistingUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "display_name_normalized": user.display_name_normalized,
        "telegram_id": user.telegram_id,
        "role": user.role,
        "status": user.status,
    }


def diff_users(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fields = ("display_name", "display_name_normalized", "telegram_id", "role", "status")
    return {
        field: {"existing": existing[field], "incoming": incoming[field]}
        for field in fields
        if existing[field] != incoming[field]
    }


def _sync_sqlite_sequence(connection: sqlite3.Connection, max_imported_id: int) -> None:
    sqlite_sequence_exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'sqlite_sequence'
        """
    ).fetchone()
    if sqlite_sequence_exists is None:
        return
    connection.execute(
        """
        INSERT INTO sqlite_sequence(name, seq)
        VALUES ('users', ?)
        ON CONFLICT(name) DO UPDATE SET seq = MAX(seq, excluded.seq)
        """,
        (max_imported_id,),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


if __name__ == "__main__":
    main()
