#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_SHEET_NAME = "Данные за все время"
DEFAULT_MAPPING_SHEET_NAME = "Лист12"
DEFAULT_TOURNAMENT_TYPE_CODE = "legacy_unknown"
HISTORICAL_TELEGRAM_ID_START = -1

KNOWN_SEASONS = [
    ("Сезон 1", date(2025, 10, 16), date(2026, 1, 25), "closed"),
    ("Сезон 2", date(2026, 1, 27), date(2026, 5, 31), "closed"),
]

SEASON_NAMES = {
    1: "Зима",
    2: "Весна",
    3: "Лето",
    4: "Осень",
}


@dataclass(frozen=True)
class HistoryRow:
    source_row: int
    tournament_date: date
    raw_player_name: str
    player_name: str
    full_name: str | None
    nickname: str | None
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
        "--mapping-sheet",
        default=DEFAULT_MAPPING_SHEET_NAME,
        help="Excel sheet with raw player names and Очист_меппинг",
    )
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Import players missing from the mapping sheet using their raw result names.",
    )
    parser.add_argument(
        "--tournament-type-code",
        default=DEFAULT_TOURNAMENT_TYPE_CODE,
        help="Tournament type code for all imported historical tournaments",
    )
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

    rows, skipped_rows = load_rows(
        args.source,
        args.sheet,
        args.mapping_sheet,
        args.allow_unmapped,
    )
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
        tournament_type_code=args.tournament_type_code,
    )
    print(f"Imported {len(rows)} rows into {args.db}")


def load_rows(
    source: Path,
    sheet_name: str,
    mapping_sheet_name: str,
    allow_unmapped: bool,
) -> tuple[list[HistoryRow], list[int]]:
    if not source.exists():
        raise SystemExit(f"Source file not found: {source}")
    if source.suffix.lower() == ".csv":
        return load_csv(source)
    if source.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return load_excel(source, sheet_name, mapping_sheet_name, allow_unmapped)
    raise SystemExit(f"Unsupported source format: {source.suffix}")


@dataclass(frozen=True)
class PlayerMapping:
    source_row: int
    raw_name: str
    mapped_name: str
    full_name: str | None
    nickname: str | None


def load_excel(
    source: Path,
    sheet_name: str,
    mapping_sheet_name: str,
    allow_unmapped: bool,
) -> tuple[list[HistoryRow], list[int]]:
    try:
        import pandas as pd
    except ImportError as error:
        raise SystemExit(
            "Reading Excel requires pandas/openpyxl. Export normalized CSV locally first."
        ) from error

    mappings = load_player_mappings(source, mapping_sheet_name, pd)
    dataframe = pd.read_excel(source, sheet_name=sheet_name)
    rows: list[HistoryRow] = []
    skipped_rows: list[int] = []
    unmapped_players: dict[str, list[int]] = defaultdict(list)
    for index, record in dataframe.iterrows():
        source_row = index + 2
        raw_date = record.get("Дата")
        if pd.isna(raw_date):
            continue

        raw_player_name = clean_text(record.get("Игрок"))
        if not raw_player_name:
            skipped_rows.append(source_row)
            continue
        mapping = mappings.get(raw_player_name)
        if mapping:
            player_name = mapping.mapped_name
            full_name = mapping.full_name
            nickname = mapping.nickname
        elif allow_unmapped:
            player_name = raw_player_name
            full_name, nickname = split_identity(player_name)
        else:
            unmapped_players[raw_player_name].append(source_row)
            continue

        rows.append(
            HistoryRow(
                source_row=source_row,
                tournament_date=pd.Timestamp(raw_date).date(),
                raw_player_name=raw_player_name,
                player_name=player_name,
                full_name=full_name,
                nickname=nickname,
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
    if unmapped_players:
        details = ", ".join(
            f"{name} (rows {rows[:5]})" for name, rows in sorted(unmapped_players.items())
        )
        raise SystemExit(
            "Missing player mappings on "
            f"{mapping_sheet_name!r}: {details}. Use --allow-unmapped to import raw names."
        )
    validate_unique_results(rows)
    return rows, skipped_rows


def load_player_mappings(source: Path, sheet_name: str, pd: Any) -> dict[str, PlayerMapping]:
    dataframe = pd.read_excel(source, sheet_name=sheet_name)
    required_columns = {"Игрок", "Очист_меппинг", "ф", "н"}
    missing_columns = required_columns - set(dataframe.columns)
    if missing_columns:
        raise SystemExit(
            f"Mapping sheet {sheet_name!r} is missing columns: {sorted(missing_columns)}"
        )

    mappings: dict[str, PlayerMapping] = {}
    identities_by_mapped_name: dict[str, tuple[str | None, str | None]] = {}
    for index, record in dataframe.iterrows():
        source_row = index + 2
        raw_name = clean_text(record.get("Игрок"))
        if not raw_name:
            continue
        mapped_name = clean_text(record.get("Очист_меппинг"))
        if not mapped_name:
            raise SystemExit(f"Empty Очист_меппинг on {sheet_name!r} row {source_row}")

        has_full_name = bool(clean_text(record.get("ф")))
        has_nickname = bool(clean_text(record.get("н")))
        if has_full_name and has_nickname:
            raise SystemExit(f"Both ф and н are set on {sheet_name!r} row {source_row}")
        if has_full_name:
            full_name, nickname = mapped_name, None
        elif has_nickname:
            full_name, nickname = None, mapped_name
        else:
            full_name, nickname = split_identity(mapped_name)

        mapping = PlayerMapping(
            source_row=source_row,
            raw_name=raw_name,
            mapped_name=mapped_name,
            full_name=full_name,
            nickname=nickname,
        )
        existing = mappings.get(raw_name)
        if existing and (
            existing.mapped_name,
            existing.full_name,
            existing.nickname,
        ) != (
            mapping.mapped_name,
            mapping.full_name,
            mapping.nickname,
        ):
            raise SystemExit(
                f"Conflicting mappings for {raw_name!r}: rows "
                f"{existing.source_row} and {source_row}"
            )
        mappings[raw_name] = mapping

        identity = (full_name, nickname)
        existing_identity = identities_by_mapped_name.get(mapped_name)
        if existing_identity and existing_identity != identity:
            raise SystemExit(
                f"Conflicting ф/н markers for {mapped_name!r} "
                f"on {sheet_name!r} row {source_row}"
            )
        identities_by_mapped_name[mapped_name] = identity
    return mappings


def validate_unique_results(rows: list[HistoryRow]) -> None:
    seen: dict[tuple[date, str], int] = {}
    duplicates: list[str] = []
    for row in rows:
        key = (row.tournament_date, row.player_name)
        previous_row = seen.get(key)
        if previous_row is not None:
            duplicates.append(
                f"{row.tournament_date.isoformat()} {row.player_name!r} "
                f"(rows {previous_row}, {row.source_row})"
            )
        else:
            seen[key] = row.source_row
    if duplicates:
        raise SystemExit(
            "Duplicate results after player mapping: " + "; ".join(duplicates[:20])
        )


def load_csv(source: Path) -> tuple[list[HistoryRow], list[int]]:
    rows: list[HistoryRow] = []
    with source.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for record in reader:
            rows.append(
                HistoryRow(
                    source_row=int(record["source_row"]),
                    tournament_date=date.fromisoformat(record["date"]),
                    raw_player_name=record.get("raw_player_name")
                    or record["player_name"],
                    player_name=record["player_name"],
                    full_name=record.get("full_name") or None,
                    nickname=record.get("nickname") or None,
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
                "raw_player_name",
                "player_name",
                "full_name",
                "nickname",
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
                    "raw_player_name": row.raw_player_name,
                    "player_name": row.player_name,
                    "full_name": row.full_name or "",
                    "nickname": row.nickname or "",
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
    tournament_type_code: str,
) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            scoring_config_id = ensure_scoring_config(connection)
            ensure_known_seasons(connection, scoring_config_id)
            tournament_type_id = ensure_legacy_tournament_type(
                connection,
                tournament_type_code,
            )
            season_ids = ensure_seasons_for_rows(connection, rows, scoring_config_id)
            tournament_ids = ensure_tournaments(
                connection=connection,
                rows=rows,
                season_ids=season_ids,
                tournament_type_id=tournament_type_id,
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


def ensure_known_seasons(
    connection: sqlite3.Connection,
    scoring_config_id: int,
) -> None:
    for name, starts_at, ends_at, status in KNOWN_SEASONS:
        ensure_season(
            connection=connection,
            name=name,
            scoring_config_id=scoring_config_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status=status,
        )


def ensure_seasons_for_rows(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
    scoring_config_id: int,
) -> dict[date, int]:
    season_ids: dict[date, int] = {}
    for tournament_date in sorted({row.tournament_date for row in rows}):
        season_id = find_season_id_for_date(connection, tournament_date)
        if season_id is None:
            season_id = ensure_calendar_season(
                connection,
                scoring_config_id,
                tournament_date,
            )
        season_ids[tournament_date] = season_id
    return season_ids


def ensure_calendar_season(
    connection: sqlite3.Connection,
    scoring_config_id: int,
    value: date,
) -> int:
    quarter = (value.month - 1) // 3 + 1
    starts_at = date(value.year, 3 * (quarter - 1) + 1, 1)
    if quarter == 4:
        ends_at = date(value.year, 12, 31)
    else:
        ends_at = date(value.year, 3 * quarter + 1, 1).replace(day=1)
        ends_at = date.fromordinal(ends_at.toordinal() - 1)
    name = f"{SEASON_NAMES[quarter]} {value.year}"
    status = "active" if starts_at <= date.today() <= ends_at else "closed"
    return ensure_season(
        connection=connection,
        name=name,
        scoring_config_id=scoring_config_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
    )


def ensure_season(
    connection: sqlite3.Connection,
    name: str,
    scoring_config_id: int,
    starts_at: date,
    ends_at: date,
    status: str,
) -> int:
    row = connection.execute("SELECT id FROM seasons WHERE name = ?", (name,)).fetchone()
    if row:
        connection.execute(
            """
            UPDATE seasons
            SET starts_at = ?, ends_at = ?, scoring_config_id = ?, status = ?
            WHERE id = ?
            """,
            (starts_at.isoformat(), ends_at.isoformat(), scoring_config_id, status, row[0]),
        )
        return int(row[0])

    cursor = connection.execute(
        """
        INSERT INTO seasons (name, scoring_config_id, starts_at, ends_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, scoring_config_id, starts_at.isoformat(), ends_at.isoformat(), status),
    )
    return int(cursor.lastrowid)


def find_season_id_for_date(
    connection: sqlite3.Connection,
    value: date,
) -> int | None:
    row = connection.execute(
        """
        SELECT id FROM seasons
        WHERE starts_at <= ? AND ends_at >= ?
        ORDER BY id
        LIMIT 1
        """,
        (value.isoformat(), value.isoformat()),
    ).fetchone()
    return int(row[0]) if row else None


def ensure_legacy_tournament_type(connection: sqlite3.Connection, code: str) -> int:
    row = connection.execute(
        "SELECT id FROM tournament_types WHERE code = ?",
        (code,),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = connection.execute(
        """
        INSERT INTO tournament_types (
            code, name, description, status, created_at, updated_at
        )
        VALUES (
            ?,
            'Неопределенный турнир',
            'Исторический турнир из старой таблицы результатов.',
            'active',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        """,
        (code,),
    )
    tournament_type_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO tournament_type_rules (
            tournament_type_id,
            points_multiplier,
            prize_place_multiplier,
            prize_place_multiplier_places,
            knockout_mode,
            created_at,
            updated_at
        )
        VALUES (?, 1.00, 1.00, NULL, 'none', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (tournament_type_id,),
    )
    return tournament_type_id


def ensure_tournaments(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
    season_ids: dict[date, int],
    tournament_type_id: int,
) -> dict[date, int]:
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
                (
                    season_ids[tournament_date],
                    capacity,
                    money(points_pool),
                    tournament_id,
                ),
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
                    season_ids[tournament_date],
                    tournament_type_id,
                    tournament_date.isoformat(),
                    capacity,
                    money(points_pool),
                ),
            )
            tournament_id = int(cursor.lastrowid)
        tournament_ids[tournament_date] = tournament_id
    return tournament_ids


def ensure_players(
    connection: sqlite3.Connection,
    rows: list[HistoryRow],
) -> dict[str, int]:
    player_ids: dict[str, int] = {}
    next_historical_telegram_id = next_negative_telegram_id(connection)

    for player_name in sorted({row.player_name for row in rows}):
        full_name, nickname = identity_for_player_name(player_name, rows)
        full_name_normalized = normalize_full_name(full_name)
        nickname_normalized = normalize_nickname(nickname)
        existing = find_existing_player(
            connection,
            full_name=full_name,
            full_name_normalized=full_name_normalized,
            nickname=nickname,
            nickname_normalized=nickname_normalized,
        )
        if existing:
            player_ids[player_name] = existing
            continue

        cursor = connection.execute(
            """
            INSERT INTO players (
                telegram_id,
                full_name,
                full_name_normalized,
                nickname,
                nickname_normalized,
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
                ?,
                ?,
                'active',
                'user',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (
                next_historical_telegram_id,
                full_name,
                full_name_normalized,
                nickname,
                nickname_normalized,
            ),
        )
        player_ids[player_name] = int(cursor.lastrowid)
        next_historical_telegram_id -= 1
    return player_ids


def identity_for_player_name(
    player_name: str,
    rows: list[HistoryRow],
) -> tuple[str | None, str | None]:
    identities = {
        (row.full_name, row.nickname) for row in rows if row.player_name == player_name
    }
    if len(identities) > 1:
        raise ValueError(f"Conflicting identities for mapped player {player_name!r}")
    identity = next(iter(identities), (None, None))
    if identity != (None, None):
        return identity
    return split_identity(player_name)


def find_existing_player(
    connection: sqlite3.Connection,
    full_name: str | None,
    full_name_normalized: str | None,
    nickname: str | None,
    nickname_normalized: str | None,
) -> int | None:
    filters = []
    values: list[str] = []
    for column, value in [
        ("full_name", full_name),
        ("full_name_normalized", full_name_normalized),
        ("nickname", nickname),
        ("nickname_normalized", nickname_normalized),
    ]:
        if value:
            filters.append(f"{column} = ?")
            values.append(value)
    if not filters:
        return None

    row = connection.execute(
        f"""
        SELECT id FROM players
        WHERE {" OR ".join(filters)}
        ORDER BY telegram_id DESC, id
        LIMIT 1
        """,
        values,
    ).fetchone()
    return int(row[0]) if row else None


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
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", player_name)
    if match:
        full_name = clean_text(match.group(1))
        nickname = clean_text(match.group(2))
        return full_name or None, nickname or None
    if len(player_name.split()) >= 2:
        return player_name, None
    return None, player_name


def build_summary(rows: list[HistoryRow], skipped_rows: list[int]) -> dict[str, Any]:
    season_counts: dict[str, int] = defaultdict(int)
    for tournament_date in {row.tournament_date for row in rows}:
        season_counts[season_name_for_date(tournament_date)] += 1

    return {
        "rows": len(rows),
        "skipped_blank_player_rows": len(skipped_rows),
        "first_skipped_blank_player_rows": skipped_rows[:20],
        "raw_players": len({row.raw_player_name for row in rows}),
        "players": len({row.player_name for row in rows}),
        "dates": len({row.tournament_date for row in rows}),
        "tournaments_by_season": dict(sorted(season_counts.items())),
        "placed_rows": sum(1 for row in rows if row.place is not None),
        "rows_with_points": sum(
            1
            for row in rows
            if row.tournament_points + row.knockout_points + row.bonus_points > 0
        ),
    }


def season_name_for_date(value: date) -> str:
    for name, starts_at, ends_at, _status in KNOWN_SEASONS:
        if starts_at <= value <= ends_at:
            return name
    quarter = (value.month - 1) // 3 + 1
    return f"{SEASON_NAMES[quarter]} {value.year}"


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


def normalize_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized or None


def normalize_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е").strip()
    normalized = normalized.removeprefix("@")
    normalized = re.sub(r"[\s._-]+", "", normalized)
    normalized = re.sub(r"[^0-9a-zа-я]+", "", normalized)
    return normalized or None


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
