import importlib.util
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.base import Base

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "merge_duplicate_users.py"
RATING_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_rating_history.py"

spec = importlib.util.spec_from_file_location("merge_duplicate_users", SCRIPT_PATH)
assert spec is not None
merge_duplicate_users = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = merge_duplicate_users
spec.loader.exec_module(merge_duplicate_users)

rating_spec = importlib.util.spec_from_file_location(
    "import_rating_history_for_merge",
    RATING_SCRIPT_PATH,
)
assert rating_spec is not None
import_rating_history = importlib.util.module_from_spec(rating_spec)
assert rating_spec.loader is not None
sys.modules[rating_spec.name] = import_rating_history
rating_spec.loader.exec_module(import_rating_history)


RESULT_HEADER = [
    "Дата",
    "Игрок",
    "Место в турнире",
    "КО",
    "Босс КО",
    "Доп.очки",
    "Количество очков за турнир",
    "Количество очков за КО",
]
MAPPING_HEADER = ["Игрок", "Меппинг", "Очист_меппинг", "ф", "н"]


def create_database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version (version_num) VALUES ('test-head');

            INSERT INTO scoring_configs (
                id,
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
            VALUES (1, 0.45, 0.25, 0.15, 0.10, 0.05, 15, 60,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO seasons (id, name, scoring_config_id, starts_at, ends_at)
            VALUES
              (1, 'Сезон 1', 1, '2025-10-16', '2026-01-25'),
              (2, 'Сезон 2', 1, '2026-01-27', '2026-05-31'),
              (3, 'Лето 2026', 1, '2026-06-01', NULL);
            INSERT INTO tournament_types (id, code, name, status, created_at, updated_at)
            VALUES (7, 'legacy_unknown', 'Неопределенный турнир', 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO tournaments (
                id, season_id, tournament_type_id, date, tournament_fund, status,
                created_at, updated_at
            )
            VALUES
              (1, 2, 7, '2026-01-28', 1000, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
              (2, 2, 7, '2026-01-29', 1000, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """
        )
        connection.commit()
    finally:
        connection.close()


def insert_user(
    path: Path,
    user_id: int,
    display_name: str,
    *,
    telegram_id: int | None = None,
    role: str = "player",
    status: str = "active",
) -> None:
    normalized = import_rating_history.normalize_display_name(display_name)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, display_name_normalized, telegram_id, role, status,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id, display_name, normalized, telegram_id, role, status),
        )
        connection.commit()
    finally:
        connection.close()


def read_table(path: Path, table: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(f"SELECT * FROM {table} ORDER BY id"))
    finally:
        connection.close()


def execute(path: Path, sql: str, params: tuple[object, ...] = ()) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def build_plan(path: Path) -> merge_duplicate_users.MergePlan:
    return merge_duplicate_users.build_merge_plan(path)


def apply_plan(path: Path) -> dict[str, int]:
    return merge_duplicate_users.apply_merge_plan(build_plan(path))


def test_duplicate_users_choose_min_id_survivor(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 23, "Аляутдинов Дамир")
    insert_user(db_path, 279, "\u200eАляутдинов Дамир")

    plan = build_plan(db_path)

    assert len(plan.groups) == 1
    assert plan.groups[0].survivor.id == 23
    assert [user.id for user in plan.groups[0].duplicates] == [279]
    assert plan.verdict == "SAFE TO APPLY"


def test_merge_moves_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")
    execute(
        db_path,
        """
        INSERT INTO tournament_results (
            tournament_id, player_id, source, checked_in_at, place,
            knockouts_count, big_knockouts_count,
            tournament_points, knockout_points, bonus_points, created_at, updated_at
        )
        VALUES (
            1, 2, 'walk_in_existing', CURRENT_TIMESTAMP, 1, 0, 0,
            100, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
    )

    stats = apply_plan(db_path)
    results = read_table(db_path, "tournament_results")

    assert stats["foreign_key_rows_moved"] == 1
    assert results[0]["player_id"] == 1
    assert [user["id"] for user in read_table(db_path, "users")] == [1]


def test_merge_deduplicates_identical_related_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")
    for player_id in (1, 2):
        execute(
            db_path,
            """
            INSERT INTO tournament_results (
                tournament_id, player_id, source, checked_in_at, place,
                knockouts_count, big_knockouts_count,
                tournament_points, knockout_points, bonus_points, created_at, updated_at
            )
            VALUES (
                1, ?, 'walk_in_existing', CURRENT_TIMESTAMP, 1, 0, 0,
                100, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (player_id,),
        )

    plan = build_plan(db_path)
    stats = merge_duplicate_users.apply_merge_plan(plan)
    results = read_table(db_path, "tournament_results")

    assert len(plan.groups[0].deduplicated_relations) == 1
    assert stats["deduplicated_relation_rows"] == 1
    assert len(results) == 1
    assert results[0]["player_id"] == 1


def test_merge_blocks_different_unique_related_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")
    for player_id, points in ((1, 100), (2, 200)):
        execute(
            db_path,
            """
            INSERT INTO tournament_results (
                tournament_id, player_id, source, checked_in_at, place,
                knockouts_count, big_knockouts_count,
                tournament_points, knockout_points, bonus_points, created_at, updated_at
            )
            VALUES (
                1, ?, 'walk_in_existing', CURRENT_TIMESTAMP, 1, 0, 0,
                ?, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (player_id, points),
        )

    plan = build_plan(db_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.groups[0].conflicts[0].reason == "unique relation conflict with different data"
    with pytest.raises(merge_duplicate_users.MergeValidationError):
        merge_duplicate_users.apply_merge_plan(plan)
    assert [row["player_id"] for row in read_table(db_path, "tournament_results")] == [1, 2]


def test_merge_transfers_single_telegram_id(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок", telegram_id=None)
    insert_user(db_path, 2, "игрок", telegram_id=222)

    apply_plan(db_path)

    users = read_table(db_path, "users")
    assert users[0]["id"] == 1
    assert users[0]["telegram_id"] == 222


def test_merge_blocks_different_telegram_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок", telegram_id=111)
    insert_user(db_path, 2, "игрок", telegram_id=222)

    plan = build_plan(db_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.groups[0].conflicts[0].reason == "different non-empty telegram_id values"


def test_merge_preserves_highest_role_and_active_status(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок", role="player", status="blocked")
    insert_user(db_path, 2, "игрок", role="superadmin", status="active")

    apply_plan(db_path)

    user = read_table(db_path, "users")[0]
    assert user["role"] == "superadmin"
    assert user["status"] == "active"


def test_merge_dry_run_does_not_change_database(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")

    plan = build_plan(db_path)

    assert plan.verdict == "SAFE TO APPLY"
    assert [user["id"] for user in read_table(db_path, "users")] == [1, 2]


def test_merge_apply_is_idempotent_and_removes_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")

    first = apply_plan(db_path)
    second = apply_plan(db_path)

    assert first["merged_groups"] == 1
    assert second["merged_groups"] == 0
    assert len(build_plan(db_path).groups) == 0
    assert [user["id"] for user in read_table(db_path, "users")] == [1]


def test_merge_rolls_back_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")
    execute(
        db_path,
        """
        INSERT INTO tournament_results (
            tournament_id, player_id, source, checked_in_at, place,
            knockouts_count, big_knockouts_count,
            tournament_points, knockout_points, bonus_points, created_at, updated_at
        )
        VALUES (
            1, 2, 'walk_in_existing', CURRENT_TIMESTAMP, 1, 0, 0,
            100, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
    )
    original_apply_group = merge_duplicate_users.apply_group

    def failing_apply_group(connection: sqlite3.Connection, group: object) -> None:
        original_apply_group(connection, group)
        raise RuntimeError("boom")

    monkeypatch.setattr(merge_duplicate_users, "apply_group", failing_apply_group)

    with pytest.raises(RuntimeError, match="boom"):
        apply_plan(db_path)

    assert [user["id"] for user in read_table(db_path, "users")] == [1, 2]
    assert read_table(db_path, "tournament_results")[0]["player_id"] == 2


def test_merge_exports_reports(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    report_dir = tmp_path / "report"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "игрок")

    plan = build_plan(db_path)
    merge_duplicate_users.export_report(plan, report_dir)

    assert {path.name for path in report_dir.iterdir()} == {
        "summary.json",
        "duplicate_groups.csv",
        "field_updates.csv",
        "foreign_key_moves.csv",
        "deduplicated_relations.csv",
        "conflicts.csv",
        "deleted_users.csv",
    }


def write_workbook(path: Path, result_rows: list[list[object]]) -> None:
    sheets = {
        "Данные за все время": [RESULT_HEADER, *result_rows],
        "Лист12": [MAPPING_HEADER, ["Raw", "", "Игрок", "", ""]],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="x"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/xl/workbook.xml" ContentType="x"/>
              <Override PartName="/xl/worksheets/sheet1.xml" ContentType="x"/>
              <Override PartName="/xl/worksheets/sheet2.xml" ContentType="x"/>
            </Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="x" Target="xl/workbook.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets>
                <sheet name="Данные за все время" sheetId="1" r:id="rId1"/>
                <sheet name="Лист12" sheetId="2" r:id="rId2"/>
              </sheets>
            </workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>
              <Relationship Id="rId2" Type="x" Target="worksheets/sheet2.xml"/>
            </Relationships>""",
        )
        for index, rows in enumerate(sheets.values(), start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(rows))


def worksheet_xml(rows: list[list[object]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            ref = f"{chr(ord('A') + column_index)}{row_index}"
            if value is None:
                continue
            if isinstance(value, str):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def test_rating_import_resolves_after_merge_and_blank_rows_do_not_block(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    source_path = tmp_path / "history.xlsx"
    create_database(db_path)
    insert_user(db_path, 1, "Игрок")
    insert_user(db_path, 2, "\u200eИгрок")
    write_workbook(
        source_path,
        [
            ["2026-02-01", "Raw", 1, 0, 0, 0, 100, 0],
            ["2026-02-02", None, 1, 0, 0, 0, 100, 0],
        ],
    )

    before = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    apply_plan(db_path)
    after = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    assert len(before.ambiguous_users) == 1
    assert len(after.ambiguous_users) == 0
    assert after.resolved_rows[0].user_id == 1
    assert len(after.source.blank_player_rows) == 1
    assert after.safe_to_apply
