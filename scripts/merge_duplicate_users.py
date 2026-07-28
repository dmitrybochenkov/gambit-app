#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.common.normalization import normalize_display_name  # noqa: E402

ROLE_RANK = {"player": 1, "admin": 2, "superadmin": 3}
STATUS_RANK = {"blocked": 1, "active": 2}
TIMESTAMP_COLUMNS = {"created_at", "updated_at"}


@dataclass(frozen=True)
class UserRow:
    id: int
    display_name: str
    display_name_normalized: str
    telegram_id: int | None
    role: str
    status: str


@dataclass(frozen=True)
class ForeignKeyRef:
    table: str
    column: str
    on_delete: str


@dataclass(frozen=True)
class FieldUpdate:
    normalized_name: str
    survivor_id: int
    field: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class ForeignKeyMove:
    normalized_name: str
    table: str
    column: str
    from_user_id: int
    to_user_id: int
    rows: int


@dataclass(frozen=True)
class DeduplicatedRelation:
    normalized_name: str
    table: str
    duplicate_row_id: int
    survivor_row_id: int
    reason: str


@dataclass(frozen=True)
class MergeConflict:
    normalized_name: str
    table: str
    reason: str
    survivor_id: int
    duplicate_id: int | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DuplicateGroupPlan:
    normalized_name: str
    survivor: UserRow
    duplicates: tuple[UserRow, ...]
    field_updates: tuple[FieldUpdate, ...]
    foreign_key_moves: tuple[ForeignKeyMove, ...]
    deduplicated_relations: tuple[DeduplicatedRelation, ...]
    conflicts: tuple[MergeConflict, ...]

    @property
    def status(self) -> str:
        return "blocked" if self.conflicts else "mergeable"


@dataclass(frozen=True)
class MergePlan:
    db_path: Path
    alembic_revision: str
    groups: tuple[DuplicateGroupPlan, ...]
    foreign_keys: tuple[ForeignKeyRef, ...]

    @property
    def conflicts(self) -> tuple[MergeConflict, ...]:
        return tuple(conflict for group in self.groups for conflict in group.conflicts)

    @property
    def verdict(self) -> str:
        return "SAFE TO APPLY" if not self.conflicts else "NOT SAFE TO APPLY"


class MergeValidationError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge duplicate Gambit users by normalized name.")
    parser.add_argument("--db", type=Path, required=True, help="Existing SQLite database")
    parser.add_argument("--export-report", type=Path, help="Directory for merge reports")
    parser.add_argument("--apply", action="store_true", help="Apply the safe merge plan")
    parser.add_argument(
        "--only-normalized-name",
        help="Limit dry-run/apply to one normalized name for focused checks",
    )
    args = parser.parse_args()

    try:
        plan = build_merge_plan(args.db, only_normalized_name=args.only_normalized_name)
        print_plan(plan)
        if args.export_report is not None:
            export_report(plan, args.export_report)
        if args.apply:
            stats = apply_merge_plan(plan, only_normalized_name=args.only_normalized_name)
            print("Apply complete")
            print(json.dumps(stats, ensure_ascii=False, indent=2))
    except MergeValidationError as exc:
        raise SystemExit(f"Merge failed: {exc}") from exc


def build_merge_plan(
    db_path: Path,
    *,
    only_normalized_name: str | None = None,
) -> MergePlan:
    resolved_db_path = resolve_db_path(db_path)
    only_key = normalize_merge_name(only_normalized_name) if only_normalized_name else None
    connection = connect_existing_database(resolved_db_path)
    try:
        ensure_required_database(connection)
        alembic_revision = get_required_alembic_revision(connection)
        foreign_keys = tuple(discover_user_foreign_keys(connection))
        users = load_users(connection)
        groups: list[DuplicateGroupPlan] = []
        for normalized_name, grouped_users in duplicate_user_groups(users).items():
            if only_key is not None and normalized_name != only_key:
                continue
            groups.append(plan_group(connection, normalized_name, grouped_users, foreign_keys))
    finally:
        connection.close()
    return MergePlan(
        db_path=resolved_db_path,
        alembic_revision=alembic_revision,
        groups=tuple(sorted(groups, key=lambda group: group.normalized_name)),
        foreign_keys=foreign_keys,
    )


def apply_merge_plan(plan: MergePlan, *, only_normalized_name: str | None = None) -> dict[str, int]:
    fresh_plan = build_merge_plan(plan.db_path, only_normalized_name=only_normalized_name)
    if fresh_plan.conflicts:
        raise MergeValidationError("Merge plan is NOT SAFE TO APPLY.")
    connection = connect_existing_database(plan.db_path)
    try:
        connection.execute("BEGIN")
        for group in fresh_plan.groups:
            apply_group(connection, group)
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise MergeValidationError(f"Foreign key check failed: {len(foreign_key_errors)} rows.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "merged_groups": len(fresh_plan.groups),
        "deleted_users": sum(len(group.duplicates) for group in fresh_plan.groups),
        "foreign_key_rows_moved": sum(
            move.rows for group in fresh_plan.groups for move in group.foreign_key_moves
        ),
        "deduplicated_relation_rows": sum(
            len(group.deduplicated_relations) for group in fresh_plan.groups
        ),
    }


def resolve_db_path(db_path: Path) -> Path:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise MergeValidationError(f"Database file does not exist: {resolved}")
    if not resolved.is_file():
        raise MergeValidationError(f"Database path is not a file: {resolved}")
    return resolved


def connect_existing_database(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=rw"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def ensure_required_database(connection: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name IN ('users', 'alembic_version')
            """
        )
    }
    missing = {"users", "alembic_version"} - tables
    if missing:
        raise MergeValidationError("Database is missing required tables: " + ", ".join(missing))


def get_required_alembic_revision(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise MergeValidationError("Database alembic_version is empty.")
    return str(row["version_num"])


def load_users(connection: sqlite3.Connection) -> list[UserRow]:
    return [
        UserRow(
            id=int(row["id"]),
            display_name=str(row["display_name"]),
            display_name_normalized=str(row["display_name_normalized"]),
            telegram_id=int(row["telegram_id"]) if row["telegram_id"] is not None else None,
            role=str(row["role"]),
            status=str(row["status"]),
        )
        for row in connection.execute(
            """
            SELECT id, display_name, display_name_normalized, telegram_id, role, status
            FROM users
            ORDER BY id
            """
        )
    ]


def duplicate_user_groups(users: list[UserRow]) -> dict[str, list[UserRow]]:
    grouped: dict[str, list[UserRow]] = defaultdict(list)
    for user in users:
        normalized = normalize_merge_name(user.display_name)
        if normalized is not None:
            grouped[normalized].append(user)
    return {
        normalized: sorted(items, key=lambda item: item.id)
        for normalized, items in grouped.items()
        if len(items) > 1
    }


def normalize_merge_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(
        char for char in value if unicodedata.category(char) not in {"Cf", "Cc"}
    )
    return normalize_display_name(cleaned)


def discover_user_foreign_keys(connection: sqlite3.Connection) -> list[ForeignKeyRef]:
    refs: list[ForeignKeyRef] = []
    tables = [
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        for fk in connection.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})"):
            if str(fk["table"]) == "users" and str(fk["to"]) == "id":
                refs.append(
                    ForeignKeyRef(
                        table=table,
                        column=str(fk["from"]),
                        on_delete=str(fk["on_delete"]),
                    )
                )
    return sorted(refs, key=lambda item: (item.table, item.column))


def plan_group(
    connection: sqlite3.Connection,
    normalized_name: str,
    users: list[UserRow],
    foreign_keys: tuple[ForeignKeyRef, ...],
) -> DuplicateGroupPlan:
    survivor = users[0]
    duplicates = tuple(users[1:])
    conflicts = list(plan_user_field_conflicts(normalized_name, survivor, duplicates))
    field_updates = plan_field_updates(normalized_name, survivor, duplicates)
    moves: list[ForeignKeyMove] = []
    dedupes: list[DeduplicatedRelation] = []

    for duplicate in duplicates:
        for fk in foreign_keys:
            row_count = count_fk_rows(connection, fk, duplicate.id)
            if row_count == 0:
                continue
            table_conflicts, table_dedupes, movable_rows = inspect_fk_move(
                connection,
                normalized_name=normalized_name,
                fk=fk,
                survivor_id=survivor.id,
                duplicate_id=duplicate.id,
            )
            conflicts.extend(table_conflicts)
            dedupes.extend(table_dedupes)
            if movable_rows:
                moves.append(
                    ForeignKeyMove(
                        normalized_name=normalized_name,
                        table=fk.table,
                        column=fk.column,
                        from_user_id=duplicate.id,
                        to_user_id=survivor.id,
                        rows=movable_rows,
                    )
                )

    return DuplicateGroupPlan(
        normalized_name=normalized_name,
        survivor=survivor,
        duplicates=duplicates,
        field_updates=tuple(field_updates),
        foreign_key_moves=tuple(moves),
        deduplicated_relations=tuple(dedupes),
        conflicts=tuple(conflicts),
    )


def plan_user_field_conflicts(
    normalized_name: str,
    survivor: UserRow,
    duplicates: tuple[UserRow, ...],
) -> list[MergeConflict]:
    telegram_ids = sorted(
        {user.telegram_id for user in (survivor, *duplicates) if user.telegram_id is not None}
    )
    if len(telegram_ids) <= 1:
        return []
    return [
        MergeConflict(
            normalized_name=normalized_name,
            table="users",
            reason="different non-empty telegram_id values",
            survivor_id=survivor.id,
            duplicate_id=None,
            details={"telegram_ids": telegram_ids},
        )
    ]


def plan_field_updates(
    normalized_name: str,
    survivor: UserRow,
    duplicates: tuple[UserRow, ...],
) -> list[FieldUpdate]:
    updates: list[FieldUpdate] = []
    duplicate_telegram_ids = sorted(
        {user.telegram_id for user in duplicates if user.telegram_id is not None}
    )
    if survivor.telegram_id is None and len(duplicate_telegram_ids) == 1:
        updates.append(
            FieldUpdate(
                normalized_name=normalized_name,
                survivor_id=survivor.id,
                field="telegram_id",
                old_value=None,
                new_value=duplicate_telegram_ids[0],
            )
        )

    highest_role = max(
        (user.role for user in (survivor, *duplicates)),
        key=lambda role: ROLE_RANK.get(role, 0),
    )
    if ROLE_RANK.get(highest_role, 0) > ROLE_RANK.get(survivor.role, 0):
        updates.append(
            FieldUpdate(
                normalized_name=normalized_name,
                survivor_id=survivor.id,
                field="role",
                old_value=survivor.role,
                new_value=highest_role,
            )
        )

    highest_status = max(
        (user.status for user in (survivor, *duplicates)),
        key=lambda status: STATUS_RANK.get(status, 0),
    )
    if STATUS_RANK.get(highest_status, 0) > STATUS_RANK.get(survivor.status, 0):
        updates.append(
            FieldUpdate(
                normalized_name=normalized_name,
                survivor_id=survivor.id,
                field="status",
                old_value=survivor.status,
                new_value=highest_status,
            )
        )
    return updates


def count_fk_rows(connection: sqlite3.Connection, fk: ForeignKeyRef, user_id: int) -> int:
    query = (
        f"SELECT COUNT(*) FROM {quote_identifier(fk.table)} "
        f"WHERE {quote_identifier(fk.column)} = ?"
    )
    return int(connection.execute(query, (user_id,)).fetchone()[0])


def inspect_fk_move(
    connection: sqlite3.Connection,
    *,
    normalized_name: str,
    fk: ForeignKeyRef,
    survivor_id: int,
    duplicate_id: int,
) -> tuple[list[MergeConflict], list[DeduplicatedRelation], int]:
    rows = fetch_rows_for_user(connection, fk, duplicate_id)
    unique_indexes = user_related_unique_indexes(connection, fk)
    conflicts: list[MergeConflict] = []
    dedupes: list[DeduplicatedRelation] = []
    movable_rows = 0

    for row in rows:
        duplicate_row_id = int(row["id"])
        duplicate_row_conflict = False
        duplicate_row_deduped = False
        for index_columns in unique_indexes:
            survivor_match = find_unique_match(
                connection,
                fk=fk,
                row=row,
                survivor_id=survivor_id,
                index_columns=index_columns,
            )
            if survivor_match is None:
                continue
            if relation_rows_equivalent(row, survivor_match, fk.column):
                dedupes.append(
                    DeduplicatedRelation(
                        normalized_name=normalized_name,
                        table=fk.table,
                        duplicate_row_id=duplicate_row_id,
                        survivor_row_id=int(survivor_match["id"]),
                        reason="identical relation after survivor replacement",
                    )
                )
                duplicate_row_deduped = True
            else:
                conflicts.append(
                    MergeConflict(
                        normalized_name=normalized_name,
                        table=fk.table,
                        reason="unique relation conflict with different data",
                        survivor_id=survivor_id,
                        duplicate_id=duplicate_id,
                        details={
                            "duplicate_row_id": duplicate_row_id,
                            "survivor_row_id": int(survivor_match["id"]),
                            "unique_columns": list(index_columns),
                        },
                    )
                )
                duplicate_row_conflict = True
        if not duplicate_row_deduped and not duplicate_row_conflict:
            movable_rows += 1
    return conflicts, dedupes, movable_rows


def fetch_rows_for_user(
    connection: sqlite3.Connection,
    fk: ForeignKeyRef,
    user_id: int,
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            f"SELECT * FROM {quote_identifier(fk.table)} WHERE {quote_identifier(fk.column)} = ?",
            (user_id,),
        )
    )


def user_related_unique_indexes(
    connection: sqlite3.Connection,
    fk: ForeignKeyRef,
) -> list[tuple[str, ...]]:
    indexes: list[tuple[str, ...]] = []
    for index in connection.execute(f"PRAGMA index_list({quote_identifier(fk.table)})"):
        if int(index["unique"]) != 1:
            continue
        columns = tuple(
            str(row["name"])
            for row in connection.execute(f"PRAGMA index_info({quote_identifier(index['name'])})")
        )
        if fk.column in columns:
            indexes.append(columns)
    return indexes


def find_unique_match(
    connection: sqlite3.Connection,
    *,
    fk: ForeignKeyRef,
    row: sqlite3.Row,
    survivor_id: int,
    index_columns: tuple[str, ...],
) -> sqlite3.Row | None:
    where: list[str] = []
    params: list[Any] = []
    for column in index_columns:
        value = survivor_id if column == fk.column else row[column]
        if value is None:
            where.append(f"{quote_identifier(column)} IS NULL")
        else:
            where.append(f"{quote_identifier(column)} = ?")
            params.append(value)
    query = f"SELECT * FROM {quote_identifier(fk.table)} WHERE {' AND '.join(where)}"
    return connection.execute(query, params).fetchone()


def relation_rows_equivalent(
    duplicate_row: sqlite3.Row,
    survivor_row: sqlite3.Row,
    fk_column: str,
) -> bool:
    for column in duplicate_row.keys():
        if column in {"id", fk_column, *TIMESTAMP_COLUMNS}:
            continue
        if duplicate_row[column] != survivor_row[column]:
            return False
    return True


def apply_group(connection: sqlite3.Connection, group: DuplicateGroupPlan) -> None:
    if any(update.field == "telegram_id" for update in group.field_updates):
        duplicate_ids = [user.id for user in group.duplicates]
        if duplicate_ids:
            placeholders = ",".join("?" for _ in duplicate_ids)
            connection.execute(
                f"UPDATE users SET telegram_id = NULL WHERE id IN ({placeholders})",
                duplicate_ids,
            )
    for update in group.field_updates:
        connection.execute(
            f"""
            UPDATE users
            SET {quote_identifier(update.field)} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (update.new_value, update.survivor_id),
        )
    dedupe_ids_by_table: dict[str, list[int]] = defaultdict(list)
    for item in group.deduplicated_relations:
        dedupe_ids_by_table[item.table].append(item.duplicate_row_id)
    for table, row_ids in dedupe_ids_by_table.items():
        placeholders = ",".join("?" for _ in row_ids)
        connection.execute(
            f"DELETE FROM {quote_identifier(table)} WHERE id IN ({placeholders})",
            row_ids,
        )
    for move in group.foreign_key_moves:
        connection.execute(
            f"""
            UPDATE {quote_identifier(move.table)}
            SET {quote_identifier(move.column)} = ?
            WHERE {quote_identifier(move.column)} = ?
            """,
            (move.to_user_id, move.from_user_id),
        )
    duplicate_ids = [user.id for user in group.duplicates]
    if duplicate_ids:
        placeholders = ",".join("?" for _ in duplicate_ids)
        connection.execute(
            f"DELETE FROM users WHERE id IN ({placeholders})",
            duplicate_ids,
        )


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def print_plan(plan: MergePlan) -> None:
    summary = plan_summary(plan)
    print("Duplicate user merge dry-run")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def plan_summary(plan: MergePlan) -> dict[str, Any]:
    return {
        "db_path": str(plan.db_path),
        "alembic_revision": plan.alembic_revision,
        "duplicate_groups_found": len(plan.groups),
        "mergeable_groups": sum(1 for group in plan.groups if group.status == "mergeable"),
        "blocked_groups": sum(1 for group in plan.groups if group.status == "blocked"),
        "survivor_users": [group.survivor.id for group in plan.groups],
        "duplicate_users_to_delete": sum(len(group.duplicates) for group in plan.groups),
        "foreign_key_rows_to_move": sum(
            move.rows for group in plan.groups for move in group.foreign_key_moves
        ),
        "duplicate_relation_rows_to_remove": sum(
            len(group.deduplicated_relations) for group in plan.groups
        ),
        "conflicts": len(plan.conflicts),
        "verdict": plan.verdict,
    }


def export_report(plan: MergePlan, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(plan_summary(plan), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv_report(directory / "duplicate_groups.csv", duplicate_group_rows(plan))
    write_csv_report(directory / "field_updates.csv", field_update_rows(plan))
    write_csv_report(directory / "foreign_key_moves.csv", foreign_key_move_rows(plan))
    write_csv_report(directory / "deduplicated_relations.csv", deduplicated_relation_rows(plan))
    write_csv_report(directory / "conflicts.csv", conflict_rows(plan))
    write_csv_report(directory / "deleted_users.csv", deleted_user_rows(plan))


def duplicate_group_rows(plan: MergePlan) -> list[dict[str, Any]]:
    rows = []
    for group in plan.groups:
        counts = Counter(
            (move.table, move.column) for move in group.foreign_key_moves
        )
        rows.append(
            {
                "normalized_name": group.normalized_name,
                "survivor_id": group.survivor.id,
                "survivor_display_name": group.survivor.display_name,
                "duplicate_ids": ",".join(str(user.id) for user in group.duplicates),
                "foreign_key_moves": json.dumps(
                    {f"{table}.{column}": count for (table, column), count in counts.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "field_updates": len(group.field_updates),
                "deleted_user_ids": ",".join(str(user.id) for user in group.duplicates),
                "conflicts": len(group.conflicts),
                "status": group.status,
            }
        )
    return rows


def field_update_rows(plan: MergePlan) -> list[dict[str, Any]]:
    return [asdict(update) for group in plan.groups for update in group.field_updates]


def foreign_key_move_rows(plan: MergePlan) -> list[dict[str, Any]]:
    return [asdict(move) for group in plan.groups for move in group.foreign_key_moves]


def deduplicated_relation_rows(plan: MergePlan) -> list[dict[str, Any]]:
    return [asdict(item) for group in plan.groups for item in group.deduplicated_relations]


def conflict_rows(plan: MergePlan) -> list[dict[str, Any]]:
    return [
        {
            **asdict(conflict),
            "details": json.dumps(conflict.details, ensure_ascii=False, sort_keys=True),
        }
        for conflict in plan.conflicts
    ]


def deleted_user_rows(plan: MergePlan) -> list[dict[str, Any]]:
    return [
        {
            "normalized_name": group.normalized_name,
            "survivor_id": group.survivor.id,
            "deleted_user_id": user.id,
            "deleted_display_name": user.display_name,
        }
        for group in plan.groups
        for user in group.duplicates
        if group.status == "mergeable"
    ]


def write_csv_report(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
