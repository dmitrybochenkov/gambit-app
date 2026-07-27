#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.common.normalization import normalize_display_name  # noqa: E402
from app.db.models.enums import UserRole, UserStatus  # noqa: E402

REQUIRED_FIELDS = ("id", "display_name", "role", "status", "telegram_id")


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
class ImportStats:
    rows_read: int
    users_created: int
    users_skipped: int
    max_imported_id: int


class ImportValidationError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical Gambit users into SQLite.")
    parser.add_argument("source", type=Path, help="Source CSV file")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to gambit.db. Defaults to DATABASE_URL or ../data/gambit.db.",
    )
    args = parser.parse_args()

    try:
        rows = load_rows(args.source)
        stats = import_users(db_path=args.db or default_db_path(), rows=rows)
    except ImportValidationError as exc:
        raise SystemExit(f"Import failed: {exc}") from exc

    print(f"Rows read: {stats.rows_read}")
    print(f"Users created: {stats.users_created}")
    print(f"Users skipped: {stats.users_skipped}")
    print(f"Max imported ID: {stats.max_imported_id}")


def load_rows(source: Path) -> list[ImportUserRow]:
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
        rows = [_parse_row(row, source_row=index) for index, row in enumerate(reader, start=2)]

    _validate_unique_csv_values(rows)
    return rows


def default_db_path() -> Path:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("sqlite+aiosqlite:///"):
        return Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    return Path(__file__).resolve().parents[1] / "data" / "gambit.db"


def import_users(db_path: Path, rows: list[ImportUserRow]) -> ImportStats:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        created = 0
        skipped = 0
        for row in rows:
            if _user_exists_with_same_data(connection, row):
                skipped += 1
                continue
            _ensure_no_db_conflicts(connection, row)
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
            created += 1
        _sync_sqlite_sequence(connection, max((row.id for row in rows), default=0))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return ImportStats(
        rows_read=len(rows),
        users_created=created,
        users_skipped=skipped,
        max_imported_id=max((row.id for row in rows), default=0),
    )


def _parse_row(row: dict[str, str], source_row: int) -> ImportUserRow:
    user_id = _parse_required_positive_int(row.get("id"), field="id", source_row=source_row)
    display_name = (row.get("display_name") or "").strip()
    if not display_name:
        raise ImportValidationError(f"Row {source_row}: display_name is required.")
    display_name_normalized = normalize_display_name(display_name)
    if display_name_normalized is None:
        raise ImportValidationError(f"Row {source_row}: display_name is empty after normalization.")

    return ImportUserRow(
        source_row=source_row,
        id=user_id,
        display_name=display_name,
        display_name_normalized=display_name_normalized,
        role=_parse_enum(UserRole, row.get("role"), field="role", source_row=source_row),
        status=_parse_enum(UserStatus, row.get("status"), field="status", source_row=source_row),
        telegram_id=_parse_telegram_id(row.get("telegram_id"), source_row=source_row),
    )


def _parse_required_positive_int(value: str | None, *, field: str, source_row: int) -> int:
    raw_value = (value or "").strip()
    if not raw_value:
        raise ImportValidationError(f"Row {source_row}: {field} is required.")
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ImportValidationError(f"Row {source_row}: {field} must be an integer.") from exc
    if parsed <= 0:
        raise ImportValidationError(f"Row {source_row}: {field} must be positive.")
    return parsed


def _parse_telegram_id(value: str | None, *, source_row: int) -> int | None:
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    if raw_value.endswith(".0"):
        raw_value = raw_value[:-2]
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ImportValidationError(f"Row {source_row}: telegram_id must be an integer.") from exc
    if parsed <= 0:
        raise ImportValidationError(f"Row {source_row}: telegram_id must be positive.")
    return parsed


def _parse_enum[EnumType](
    enum_class: type[EnumType],
    value: str | None,
    *,
    field: str,
    source_row: int,
) -> EnumType:
    raw_value = (value or "").strip()
    if not raw_value:
        raise ImportValidationError(f"Row {source_row}: {field} is required.")
    try:
        return enum_class(raw_value.casefold())
    except ValueError as exc:
        allowed = ", ".join(item.name for item in enum_class)
        raise ImportValidationError(
            f"Row {source_row}: invalid {field} {raw_value!r}. Allowed values: {allowed}."
        ) from exc


def _validate_unique_csv_values(rows: list[ImportUserRow]) -> None:
    seen_ids: dict[int, int] = {}
    seen_telegram_ids: dict[int, ImportUserRow] = {}
    for row in rows:
        if row.id in seen_ids:
            raise ImportValidationError(
                f"Row {row.source_row}: duplicate id {row.id}; "
                f"first seen on row {seen_ids[row.id]}."
            )
        seen_ids[row.id] = row.source_row

        if row.telegram_id is None:
            continue
        existing_telegram = seen_telegram_ids.get(row.telegram_id)
        if existing_telegram is not None:
            raise ImportValidationError(
                f"Row {row.source_row}: telegram_id {row.telegram_id} conflicts with row "
                f"{existing_telegram.source_row}."
            )
        seen_telegram_ids[row.telegram_id] = row


def _user_exists_with_same_data(connection: sqlite3.Connection, row: ImportUserRow) -> bool:
    existing = connection.execute("SELECT * FROM users WHERE id = ?", (row.id,)).fetchone()
    if existing is None:
        return False
    if _row_matches_existing_user(existing, row):
        return True
    raise ImportValidationError(
        f"Row {row.source_row}: user id {row.id} already exists with different data."
    )


def _row_matches_existing_user(existing: sqlite3.Row, row: ImportUserRow) -> bool:
    return (
        existing["display_name"] == row.display_name
        and existing["display_name_normalized"] == row.display_name_normalized
        and existing["telegram_id"] == row.telegram_id
        and existing["role"] == row.role.value
        and existing["status"] == row.status.value
    )


def _ensure_no_db_conflicts(connection: sqlite3.Connection, row: ImportUserRow) -> None:
    if row.telegram_id is None:
        return
    telegram_conflict = connection.execute(
        """
        SELECT id FROM users
        WHERE telegram_id = ? AND id != ?
        """,
        (row.telegram_id, row.id),
    ).fetchone()
    if telegram_conflict is not None:
        raise ImportValidationError(
            f"Row {row.source_row}: telegram_id {row.telegram_id} conflicts with "
            f"existing user id {telegram_conflict['id']}."
        )


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


if __name__ == "__main__":
    main()
