from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.common.normalization import normalize_display_name  # noqa: E402
from import_rating_history import ImportValidationError, XlsxWorkbook, clean_text  # noqa: E402

DEFAULT_SHEET = "Лист12"


@dataclass(frozen=True)
class SourceGenderRow:
    source_row: int
    display_name: str
    display_name_normalized: str
    gender: str | None


@dataclass(frozen=True)
class DatabaseUser:
    id: int
    display_name: str
    display_name_normalized: str
    gender: str | None


@dataclass(frozen=True)
class GenderPlanItem:
    category: str
    source: SourceGenderRow | None
    user: DatabaseUser | None
    reason: str


@dataclass(frozen=True)
class GenderImportPlan:
    source_rows: tuple[SourceGenderRow, ...]
    items: tuple[GenderPlanItem, ...]

    @property
    def safe_updates(self) -> tuple[GenderPlanItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.category == "matched"
            and item.source is not None
            and item.user is not None
            and item.source.gender is not None
            and item.user.gender != item.source.gender
        )

    @property
    def counts(self) -> Counter[str]:
        return Counter(item.category for item in self.items)

    @property
    def source_gender_counts(self) -> Counter[str]:
        return Counter(row.gender or "blank" for row in self.source_rows)

    @property
    def matched_gender_counts(self) -> Counter[str]:
        return Counter(
            item.source.gender or "blank"
            for item in self.items
            if item.category == "matched" and item.source is not None
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical user gender values.")
    parser.add_argument("source", type=Path, help="Path to historical rating XLSX.")
    parser.add_argument(
        "--sheet",
        default=DEFAULT_SHEET,
        help=f"Source sheet name. Default: {DEFAULT_SHEET}",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite DB path. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe updates. Default is dry-run.",
    )
    args = parser.parse_args()

    db_path = args.db or sqlite_path_from_database_url(os.environ.get("DATABASE_URL"))
    if db_path is None:
        raise SystemExit("Provide --db or sqlite DATABASE_URL.")
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")

    source_rows = load_source_rows(args.source, args.sheet)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        plan = build_plan(source_rows, load_users(connection))
        print_report(plan)
        if args.apply:
            apply_plan(connection, plan)
            print(f"Updated: {len(plan.safe_updates)}")
        else:
            print(f"Would update: {len(plan.safe_updates)}")


def sqlite_path_from_database_url(value: str | None) -> Path | None:
    if not value:
        return None
    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    for prefix in prefixes:
        if value.startswith(prefix):
            return Path(value.removeprefix(prefix))
    raise SystemExit("Only SQLite DATABASE_URL is supported by this one-off importer.")


def load_source_rows(path: Path, sheet_name: str = DEFAULT_SHEET) -> tuple[SourceGenderRow, ...]:
    workbook = XlsxWorkbook(path)
    rows: list[SourceGenderRow] = []
    for source_row, record in workbook.iter_records(
        sheet_name,
        ("user", "Пол"),
        allow_extra_columns=True,
    ):
        display_name = clean_text(record["user"])
        if not display_name:
            continue
        normalized = normalize_display_name(display_name)
        if normalized is None:
            continue
        rows.append(
            SourceGenderRow(
                source_row=source_row,
                display_name=display_name,
                display_name_normalized=normalized,
                gender=parse_source_gender(record["Пол"]),
            )
        )
    return tuple(rows)


def parse_source_gender(value: object) -> str | None:
    raw = clean_text(value).casefold()
    if raw == "":
        return None
    if raw == "м":
        return "male"
    if raw == "ж":
        return "female"
    raise ImportValidationError(f"Unknown gender source value: {value!r}")


def load_users(connection: sqlite3.Connection) -> tuple[DatabaseUser, ...]:
    rows = connection.execute(
        """
        SELECT id, display_name, display_name_normalized, gender
        FROM users
        ORDER BY id
        """
    ).fetchall()
    return tuple(
        DatabaseUser(
            id=int(row["id"]),
            display_name=str(row["display_name"]),
            display_name_normalized=str(row["display_name_normalized"]),
            gender=row["gender"],
        )
        for row in rows
    )


def build_plan(
    source_rows: tuple[SourceGenderRow, ...],
    users: tuple[DatabaseUser, ...],
) -> GenderImportPlan:
    users_by_normalized: dict[str, list[DatabaseUser]] = defaultdict(list)
    for user in users:
        users_by_normalized[user.display_name_normalized].append(user)

    source_by_normalized: dict[str, list[SourceGenderRow]] = defaultdict(list)
    for row in source_rows:
        source_by_normalized[row.display_name_normalized].append(row)

    items: list[GenderPlanItem] = []
    for row in source_rows:
        duplicate_sources = source_by_normalized[row.display_name_normalized]
        candidates = users_by_normalized.get(row.display_name_normalized, [])
        if len(duplicate_sources) > 1 or len(candidates) > 1:
            items.append(GenderPlanItem("ambiguous", row, None, "duplicate normalized name"))
            continue
        if not candidates:
            items.append(GenderPlanItem("not_in_database", row, None, "source user not found"))
            continue
        user = candidates[0]
        if row.gender is None:
            items.append(GenderPlanItem("unknown_source", row, user, "blank source gender"))
            continue
        if user.gender is not None and user.gender != row.gender:
            items.append(GenderPlanItem("conflict", row, user, "existing gender differs"))
            continue
        items.append(GenderPlanItem("matched", row, user, "safe"))

    source_names = set(source_by_normalized)
    for user in users:
        if user.display_name_normalized not in source_names:
            items.append(GenderPlanItem("not_in_source", None, user, "database user not in source"))
    return GenderImportPlan(source_rows=source_rows, items=tuple(items))


def apply_plan(connection: sqlite3.Connection, plan: GenderImportPlan) -> None:
    with connection:
        for item in plan.safe_updates:
            if item.user is None or item.source is None:
                continue
            connection.execute(
                "UPDATE users SET gender = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item.source.gender, item.user.id),
            )


def print_report(plan: GenderImportPlan) -> None:
    counts = plan.counts
    source_counts = plan.source_gender_counts
    matched_counts = plan.matched_gender_counts
    print(f"Source rows: {len(plan.source_rows)}")
    print(f"Source male: {source_counts['male']}")
    print(f"Source female: {source_counts['female']}")
    print(f"Source blank: {source_counts['blank']}")
    print(f"Matched male: {matched_counts['male']}")
    print(f"Matched female: {matched_counts['female']}")
    print(f"Matched: {counts['matched']}")
    print(f"Unknown source: {counts['unknown_source']}")
    print(f"Not in database: {counts['not_in_database']}")
    print(f"Not in source: {counts['not_in_source']}")
    print(f"Ambiguous: {counts['ambiguous']}")
    print(f"Conflicts: {counts['conflict']}")
    for category in (
        "unknown_source",
        "not_in_database",
        "not_in_source",
        "ambiguous",
        "conflict",
    ):
        print_category(plan, category)


def print_category(plan: GenderImportPlan, category: str) -> None:
    rows = [item for item in plan.items if item.category == category]
    if not rows:
        return
    print("")
    print(f"{category}:")
    for item in rows:
        source = (
            f"row={item.source.source_row} name={item.source.display_name!r} "
            f"gender={item.source.gender or 'blank'}"
            if item.source is not None
            else "source=-"
        )
        user = (
            f"user_id={item.user.id} name={item.user.display_name!r} "
            f"gender={item.user.gender or 'NULL'}"
            if item.user is not None
            else "user=-"
        )
        print(f"- {source}; {user}; {item.reason}")


if __name__ == "__main__":
    main()
