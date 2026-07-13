#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_SHEET_NAME = "Данные за все время"
DEFAULT_SEASON_NAME = "Исторические результаты 2026"
HISTORICAL_TELEGRAM_ID_START = -1


@dataclass(frozen=True)
class HistoryRow:
    source_row: int
    tournament_date: date
    player_name: str
    place: int | None
    knockouts_count: int
    boss_knockouts_count: int
    bonus_points: Decimal
    tournament_points: Decimal
    knockout_points: Decimal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Gambit historical tournament results into SQLite."
    )
    parser.add_argument("source", type=Path, help="Source .xlsx or normalized .csv file")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "gambit.db",
        help="Path to gambit.db",
    )
    parser.add_argument("--sheet", default=DEFAULT_SHEET_NAME, help="Excel sheet name")
    parser.add_argument(
        "--season-name",
        default=DEFAULT_SEASON_NAME,
        help="Season name for imported historical tournaments",
    )
    parser.add_argument("--tournament-type-code", default="bounty")
    parser.add_argument(
        "--export-csv",
        type=Path,
        help="Write normalized CSV and exit unless --apply is also passed",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the database. Without this flag only a dry run is printed.",
    )
    args = parser.parse_args()

    rows, skipped_rows = load_rows(args.source, args.sheet)
    if args.export_csv:
        export_csv(args.export_csv, rows)

    summary = build_summary(rows, skipped_rows)
    print_summary(summary)
    if not args.apply:
        return

    if not rows:
        raise SystemExit("No rows to import.")
    import_rows(
        db_path=args.db,
        rows=rows,
        season_name=args.season_name,
        tournament_type_code=args.tournament_type_code,
    )
    print(f"Imported {len(rows)} rows into {args.db}")


def load_rows(source: Path, sheet_name: str) -> tuple[list[HistoryRow], list[int]]:
    if source.suffix.lower() == ".csv":
        return load_csv(source)
    if source.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return load_excel(source, sheet_name)
    raise SystemExit(f"Unsupported source format: {source.suffix}")


def load_excel(source: Path, sheet_name: str) -> tuple[list[HistoryRow], list[int]]:
    try:
        import pandas as pd
    except ImportError as error:
        raise SystemExit(
            "Reading Excel requires pandas/openpyxl. Export normalized CSV locally first."
        ) from error

    dataframe = pd.read_excel(source, sheet_name=sheet_name)
    rows: list[HistoryRow] = []
    skipped_rows: list[int] = []
    for index, record in dataframe.iterrows():
        source_row = index + 2
        raw_date = record.get("Дата")
        if pd.isna(raw_date):
            continue

        player_name = clean_text(record.get("Игрок"))
        if not player_name:
            skipped_rows.append(source_row)
            continue

        rows.append(
            HistoryRow(
                source_row=source_row,
                tournament_date=pd.Timestamp(raw_date).date(),
                player_name=player_name,
                place=optional_int(record.get("Место в турнире")),
                knockouts_count=required_int(record.get("КО")),
                boss_knockouts_count=required_int(record.get("Босс КО")),
                bonus_points=required_decimal(record.get("Доп.очки")),
                tournament_points=required_decimal(
                    record.get("Количество очков за турнир")
                ),
                knockout_points=required_decimal(record.get("Количество очков за КО")),
            )
        )
    return rows, skipped_rows


def load_csv(source: Path) -> tuple[list[HistoryRow], list[int]]:
    rows: list[HistoryRow] = []
    with source.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for record in reader:
            rows.append(
                HistoryRow(
                    source_row=int(record["source_row"]),
                    tournament_date=date.fromisoformat(record["date"]),
                    player_name=record["player_name"],
                    place=int(record["place"]) if record["place"] else None,
                    knockouts_count=int(record["knockouts_count"]),
                    boss_knockouts_count=int(record["boss_knockouts_count"]),
                    bonus_points=Decimal(record["bonus_points"]),
                    tournament_points=Decimal(record["tournament_points"]),
                    knockout_points=Decimal(record["knockout_points"]),
                )
            )
    return rows, []


def export_csv(path: Path, rows: list[HistoryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "source_row",
                "date",
                "player_name",
                "place",
                "knockouts_count",
                "boss_knockouts_count",
                "bonus_points",
                "tournament_points",
                "knockout_points",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source_row": row.source_row,
                    "date": row.tournament_date.isoformat(),
                    "player_name": row.player_name,
                    "place": row.place or "",
                    "knockouts_count": row.knockouts_count,
                    "boss_knockouts_count": row.boss_knockouts_count,
                    "bonus_points": money(row.bonus_points),
                    "tournament_points": money(row.tournament_points),
                    "knockout_points": money(row.knockout_points),
                }
            )
    print(f"Exported normalized CSV to {path}")


def import_rows(
    db_path: Path,
    rows: list[HistoryRow],
    season_name: str,
    tournament_type_code: str,
) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            scoring_config_id = ensure_scoring_config(connection)
            season_id = ensure_season(
                connection=connection,
                name=season_name,
                scoring_config_id=scoring_config_id,
                starts_at=min(row.tournament_date for row in rows),
                ends_at=max(row.tournament_date for row in rows),
            )
            tournament_ids = ensure_tournaments(
                connection=connection,
                rows=rows,
                season_id=season_id,
                tournament_type_code=tournament_type_code,
            )
            player_ids = ensure_players(connection, rows)
            upsert_results(connection, rows, tournament_ids, player_ids)
    finally:
        connection.close()


def ensure_scoring_config(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT id FROM scoring_configs ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row[0])
    cursor = connection.execute(
        """
        INSERT INTO scoring_configs (
            place_1_coefficient,
            place_2_coefficient,
            place_3_coefficient,
            place_4_coefficient,
            place_5_coefficient,
            knockout_small_points,
            knockout_big_points,
            created_at,
            updated_at
        )
        VALUES (0.45, 0.25, 0.15, 0.10, 0.05, 15, 60, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    return int(cursor.lastrowid)


def ensure_season(
    connection: sqlite3.Connection,
    name: str,
    scoring_config_id: int,
    starts_at: date,
    ends_at: date,
) -> int:
    row = connection.execute("SELECT id FROM seasons WHERE name = ?", (name,)).fetchone()
    if row:
        connection.execute(
            """
            UPDATE seasons
            SET starts_at = ?, ends_at = ?, scoring_config_id = ?, status = 'closed'
            WHERE id = ?
            """,
            (starts_at.isoformat(), ends_at.isoformat(), scoring_config_id, row[0]),
        )
        return int(row[0])

    cursor = connection.execute(
        """
        INSERT INTO seasons (name, scoring_config_id, starts_at, ends_at, status)
        VALUES (?, ?, ?, ?, 'closed')
        """,
        (name, scoring_config_id, starts_at.isoformat(), ends_at.isoformat()),
    )
    return int(cursor.lastrowid)


def ensure_tournaments(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
    season_id: int,
    tournament_type_code: str,
) -> dict[date, int]:
    tournament_type_id = get_tournament_type_id(connection, tournament_type_code)
    rows_by_date: dict[date, list[HistoryRow]] = defaultdict(list)
    for row in rows:
        rows_by_date[row.tournament_date].append(row)

    tournament_ids: dict[date, int] = {}
    for tournament_date, tournament_rows in rows_by_date.items():
        points_pool = sum(
            (row.tournament_points for row in tournament_rows),
            Decimal("0"),
        )
        capacity = max(1, len(tournament_rows))
        existing = connection.execute(
            "SELECT id FROM tournaments WHERE date = ? AND tournament_type_id = ?",
            (tournament_date.isoformat(), tournament_type_id),
        ).fetchone()
        if existing:
            tournament_id = int(existing[0])
            connection.execute(
                """
                UPDATE tournaments
                SET season_id = ?,
                    capacity = ?,
                    points_pool = ?,
                    status = 'closed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (season_id, capacity, money(points_pool), tournament_id),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO tournaments (
                    season_id,
                    tournament_type_id,
                    date,
                    capacity,
                    points_pool,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    season_id,
                    tournament_type_id,
                    tournament_date.isoformat(),
                    capacity,
                    money(points_pool),
                ),
            )
            tournament_id = int(cursor.lastrowid)
        tournament_ids[tournament_date] = tournament_id
    return tournament_ids


def get_tournament_type_id(connection: sqlite3.Connection, code: str) -> int:
    row = connection.execute(
        "SELECT id FROM tournament_types WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"Tournament type not found: {code}")
    return int(row[0])


def ensure_players(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
) -> dict[str, int]:
    player_ids: dict[str, int] = {}
    next_historical_telegram_id = next_negative_telegram_id(connection)

    for player_name in sorted({row.player_name for row in rows}):
        full_name, nickname = split_identity(player_name)
        existing = connection.execute(
            """
            SELECT id FROM players
            WHERE full_name = ? OR nickname = ?
            ORDER BY telegram_id DESC
            LIMIT 1
            """,
            (player_name, player_name),
        ).fetchone()
        if existing:
            player_ids[player_name] = int(existing[0])
            continue

        cursor = connection.execute(
            """
            INSERT INTO players (
                telegram_id,
                full_name,
                nickname,
                status,
                role,
                approved_at,
                created_at,
                updated_at
            )
            VALUES (
                ?,
                ?,
                ?,
                'active',
                'user',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (next_historical_telegram_id, full_name, nickname),
        )
        player_ids[player_name] = int(cursor.lastrowid)
        next_historical_telegram_id -= 1
    return player_ids


def upsert_results(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
    tournament_ids: dict[date, int],
    player_ids: dict[str, int],
) -> None:
    for row in rows:
        connection.execute(
            """
            INSERT INTO tournament_results (
                tournament_id,
                player_id,
                place,
                knockouts_count,
                boss_knockouts_count,
                tournament_points,
                knockout_points,
                bonus_points,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(tournament_id, player_id) DO UPDATE SET
                place = excluded.place,
                knockouts_count = excluded.knockouts_count,
                boss_knockouts_count = excluded.boss_knockouts_count,
                tournament_points = excluded.tournament_points,
                knockout_points = excluded.knockout_points,
                bonus_points = excluded.bonus_points,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                tournament_ids[row.tournament_date],
                player_ids[row.player_name],
                row.place,
                row.knockouts_count,
                row.boss_knockouts_count,
                money(row.tournament_points),
                money(row.knockout_points),
                money(row.bonus_points),
            ),
        )


def next_negative_telegram_id(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT MIN(telegram_id) FROM players WHERE telegram_id < 0"
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0]) - 1
    return HISTORICAL_TELEGRAM_ID_START


def split_identity(player_name: str) -> tuple[str | None, str | None]:
    if len(player_name.split()) >= 2:
        return player_name, None
    return None, player_name


def build_summary(rows: list[HistoryRow], skipped_rows: list[int]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "skipped_blank_player_rows": len(skipped_rows),
        "first_skipped_blank_player_rows": skipped_rows[:20],
        "players": len({row.player_name for row in rows}),
        "dates": len({row.tournament_date for row in rows}),
        "placed_rows": sum(1 for row in rows if row.place is not None),
        "rows_with_points": sum(
            1
            for row in rows
            if row.tournament_points + row.knockout_points + row.bonus_points > 0
        ),
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("Import summary")
    for key, value in summary.items():
        print(f"{key}: {value}")


def clean_text(value: Any) -> str:
    if value is None or is_nan(value):
        return ""
    text = str(value)
    text = "".join(
        char for char in text if unicodedata.category(char) not in {"Cf", "Cc"}
    )
    return " ".join(text.split()).strip()


def optional_int(value: Any) -> int | None:
    if value is None or is_nan(value):
        return None
    return int(value)


def required_int(value: Any) -> int:
    if value is None or is_nan(value):
        return 0
    return int(value)


def required_decimal(value: Any) -> Decimal:
    if value is None or is_nan(value):
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise ValueError(f"Invalid decimal value: {value}") from error


def is_nan(value: Any) -> bool:
    return value != value


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


if __name__ == "__main__":
    main()
