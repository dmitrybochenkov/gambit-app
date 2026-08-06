import csv
import importlib.util
import json
import sqlite3
import subprocess
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.base import Base

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_rating_history.py"
PROJECT_ROOT = SCRIPT_PATH.parents[1]
spec = importlib.util.spec_from_file_location("import_rating_history", SCRIPT_PATH)
assert spec is not None
import_rating_history = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = import_rating_history
spec.loader.exec_module(import_rating_history)


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
            """
        )
        connection.commit()
    finally:
        connection.close()


def insert_user(path: Path, user_id: int, display_name: str) -> None:
    normalized = import_rating_history.normalize_display_name(display_name)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, display_name_normalized, role, status, created_at, updated_at
            )
            VALUES (?, ?, ?, 'player', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id, display_name, normalized),
        )
        connection.commit()
    finally:
        connection.close()


def write_aliases(path: Path, rows: list[tuple[str, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["source_name", "user_id"])
        writer.writerows(rows)


def write_workbook(
    path: Path,
    result_rows: list[list[object]],
    mapping_rows: list[list[object]] | None = None,
) -> None:
    mapping_rows = mapping_rows or [["Raw", "", "Mapped", "", ""]]
    sheets = {
        "Данные за все время": [RESULT_HEADER, *result_rows],
        "Лист12": [MAPPING_HEADER, *mapping_rows],
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


def run_rating_import_cli(
    *args: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd or PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def strict_distribution_rows() -> list[list[object]]:
    season_two_start = date(2026, 1, 28)
    summer_start = date(2026, 6, 1)
    rows = [
        [(season_two_start + timedelta(days=index)).isoformat(), "Raw", 1, 0, 0, 0, 1, 0]
        for index in range(91)
    ]
    rows.extend(
        [(summer_start + timedelta(days=index)).isoformat(), "Raw", 1, 0, 0, 0, 1, 0]
        for index in range(39)
    )
    return rows


def build_plan(
    tmp_path: Path,
    result_rows: list[list[object]],
    mapping_rows: list[list[object]] | None = None,
    aliases: list[tuple[str, int]] | None = None,
) -> tuple[Path, Path, object]:
    db_path = tmp_path / "gambit.db"
    source_path = tmp_path / "history.xlsx"
    create_database(db_path)
    alias_path = tmp_path / "aliases.csv"
    aliases_path = None
    if aliases is not None:
        write_aliases(alias_path, aliases)
        aliases_path = alias_path
    write_workbook(source_path, result_rows, mapping_rows)
    return (
        db_path,
        source_path,
        import_rating_history.build_import_plan(
            source_path=source_path,
            db_path=db_path,
            aliases_path=aliases_path,
            strict_expectations=False,
        ),
    )


def test_reads_all_eight_result_columns_and_big_knockouts(tmp_path: Path) -> None:
    db_path, _source_path, plan = build_plan(
        tmp_path,
        [[46050, "Raw", 1, 2, 3, 4, 100, 30]],
        [["Raw", "", "Mapped", "", ""]],
    )
    insert_user(db_path, 1, "Mapped")
    plan = import_rating_history.build_import_plan(
        source_path=tmp_path / "history.xlsx",
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    row = plan.resolved_rows[0]
    assert row.place == 1
    assert row.knockouts_count == 2
    assert row.big_knockouts_count == 3
    assert row.bonus_points == import_rating_history.Decimal("4.00")
    assert row.tournament_points == import_rating_history.Decimal("100.00")
    assert row.knockout_points == import_rating_history.Decimal("30.00")


def test_import_rating_history_cli_default_is_dry_run(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    source_path = tmp_path / "history.xlsx"
    create_database(db_path)
    insert_user(db_path, 1, "Mapped")
    write_workbook(source_path, strict_distribution_rows(), [["Raw", "", "Mapped", "", ""]])

    result = run_rating_import_cli(str(source_path), "--db", str(db_path), cwd=PROJECT_ROOT)

    assert result.returncode == 0
    assert "Verdict: SAFE TO APPLY" in result.stdout
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 0
    finally:
        connection.close()


def test_import_rating_history_cli_export_report_and_absolute_paths(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    source_path = tmp_path / "history.xlsx"
    report_dir = tmp_path / "report"
    create_database(db_path)
    insert_user(db_path, 1, "Mapped")
    write_workbook(source_path, strict_distribution_rows(), [["Raw", "", "Mapped", "", ""]])

    result = run_rating_import_cli(
        str(source_path.resolve()),
        "--db",
        str(db_path.resolve()),
        "--export-report",
        str(report_dir.resolve()),
        cwd=tmp_path,
    )

    assert result.returncode == 0
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["blank_player_rows_intentionally_skipped"] == 0
    assert (report_dir / "blank_player_rows.csv").exists()
    assert (report_dir / "blank_players.csv").exists()
    assert (report_dir / "unresolved_users.csv").exists()


def test_import_rating_history_cli_apply_and_second_apply_are_idempotent(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    source_path = tmp_path / "history.xlsx"
    create_database(db_path)
    insert_user(db_path, 1, "Mapped")
    write_workbook(source_path, strict_distribution_rows(), [["Raw", "", "Mapped", "", ""]])

    first = run_rating_import_cli(str(source_path), "--db", str(db_path), "--apply")
    second = run_rating_import_cli(str(source_path), "--db", str(db_path), "--apply")

    assert first.returncode == 0
    assert '"tournaments_created": 130' in first.stdout
    assert '"results_created": 130' in first.stdout
    assert second.returncode == 0
    assert '"tournaments_created": 0' in second.stdout
    assert '"results_created": 0' in second.stdout
    assert '"tournaments_unchanged": 130' in second.stdout
    assert '"results_unchanged": 130' in second.stdout


def test_import_rating_history_cli_missing_db_does_not_create_file(tmp_path: Path) -> None:
    source_path = tmp_path / "history.xlsx"
    missing_db = tmp_path / "missing.db"
    write_workbook(source_path, strict_distribution_rows(), [["Raw", "", "Mapped", "", ""]])

    result = run_rating_import_cli(str(source_path), "--db", str(missing_db), cwd=tmp_path)

    assert result.returncode != 0
    assert "database file does not exist" in result.stderr.lower()
    assert not missing_db.exists()


def test_unicode_cleanup_and_mapping_sheet_resolution(tmp_path: Path) -> None:
    db_path, _source_path, _plan = build_plan(
        tmp_path,
        [[46050, "\u200e Raw \n Name ", "", "", "", "", 10, ""]],
        [["Raw Name", "", "Mapped Name", "", ""]],
    )
    insert_user(db_path, 1, "Mapped Name")

    plan = import_rating_history.build_import_plan(
        source_path=tmp_path / "history.xlsx",
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    assert plan.resolved_rows[0].raw_player_name == "Raw Name"
    assert plan.resolved_rows[0].mapped_name == "Mapped Name"


def test_explicit_alias_resolves_ambiguous_user_without_fuzzy_matching(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Husband", "", "", "", "", 10, ""]],
        [["Husband", "", "Husband", "", ""]],
        aliases=[("Husband", 8)],
    )
    insert_user(db_path, 8, "Husband")
    insert_user(db_path, 12, "husband")

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=tmp_path / "aliases.csv",
        strict_expectations=False,
    )

    assert plan.ambiguous_users == []
    assert plan.resolved_rows[0].user_id == 8


def test_husband_case_pair_is_ambiguous_without_alias(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Husband", "", "", "", "", 10, ""]],
        [["Husband", "", "Husband", "", ""]],
    )
    insert_user(db_path, 8, "Husband")
    insert_user(db_path, 12, "husband")

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    assert len(plan.ambiguous_users) == 1


def test_unresolved_user_blocks_apply(tmp_path: Path) -> None:
    _db_path, _source_path, plan = build_plan(
        tmp_path,
        [[46050, "Missing", "", "", "", "", 10, ""]],
        [["Missing", "", "Missing", "", ""]],
    )

    assert not plan.safe_to_apply
    with pytest.raises(import_rating_history.ImportValidationError):
        import_rating_history.apply_import_plan(plan)


def test_blank_player_report_and_tournament_without_result(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "", 1, 0, 0, 0, 968, 0]],
        [],
    )

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    assert len(plan.source.blank_player_rows) == 1
    assert plan.source.blank_player_rows[0].reason == "blank_player"
    assert plan.safe_to_apply
    stats = import_rating_history.apply_import_plan(plan)
    assert stats.tournaments_created == 1
    assert stats.results_created == 0


def test_single_winner_historical_tournament_imports_fact_points(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Winner", 1, 0, 0, 0, 968, 0]],
        [["Winner", "", "Winner", "", ""]],
    )
    insert_user(db_path, 1, "Winner")

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    import_rating_history.apply_import_plan(plan)

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT tournament_points, knockout_points, bonus_points FROM tournament_results"
        ).fetchone()
        assert row == (968, 0, 0)
    finally:
        connection.close()


def test_exact_season_assignment_at_boundaries_and_no_season_creation(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [
            [46050, "P1", "", "", "", "", 10, ""],
            [46173, "P2", "", "", "", "", 20, ""],
        ],
        [["P1", "", "P1", "", ""], ["P2", "", "P2", "", ""]],
    )
    insert_user(db_path, 1, "P1")
    insert_user(db_path, 2, "P2")

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    import_rating_history.apply_import_plan(plan)
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM seasons").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT season_id FROM tournaments WHERE date = '2026-01-28'"
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT season_id FROM tournaments WHERE date = '2026-05-31'"
            ).fetchone()[0]
            == 2
        )
    finally:
        connection.close()


def test_capacity_column_is_not_required_and_big_field_is_current_schema(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Player", "", 1, 2, "", 10, 15]],
        [["Player", "", "Player", "", ""]],
    )
    insert_user(db_path, 1, "Player")

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    import_rating_history.apply_import_plan(plan)
    connection = sqlite3.connect(db_path)
    try:
        tournament_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(tournaments)")
        ]
        result_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(tournament_results)")
        ]
        assert "capacity" not in tournament_columns
        assert "big_knockouts_count" in result_columns
        assert "boss_knockouts_count" not in result_columns
    finally:
        connection.close()


def test_idempotent_second_import(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Player", "", "", "", "", 10, ""]],
        [["Player", "", "Player", "", ""]],
    )
    insert_user(db_path, 1, "Player")
    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    first = import_rating_history.apply_import_plan(plan)
    second_plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    second = import_rating_history.apply_import_plan(second_plan)

    assert first.results_created == 1
    assert second.results_created == 0
    assert second.results_unchanged == 1


def test_existing_tournament_conflict_blocks_import(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Player", "", "", "", "", 10, ""]],
        [["Player", "", "Player", "", ""]],
    )
    insert_user(db_path, 1, "Player")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO tournament_types (id, code, name, status, created_at, updated_at)
            VALUES (8, 'classic', 'Классика', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.execute(
            """
            INSERT INTO tournaments (
                season_id, tournament_type_id, date, tournament_fund, status, created_at, updated_at
            )
            VALUES (2, 8, '2026-01-28', 10, 'closed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()
    finally:
        connection.close()

    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )

    assert not plan.safe_to_apply
    assert plan.tournament_items[0].action == "conflict"


def test_existing_result_diff_requires_update_mode(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [[46050, "Player", "", "", "", "", 10, ""]],
        [["Player", "", "Player", "", ""]],
    )
    insert_user(db_path, 1, "Player")
    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    import_rating_history.apply_import_plan(plan)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("UPDATE tournament_results SET tournament_points = 11")
        connection.commit()
    finally:
        connection.close()

    conflict_plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    update_plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        update_existing=True,
        strict_expectations=False,
    )

    assert conflict_plan.result_items[0].action == "conflict"
    assert update_plan.result_items[0].action == "update"


def test_apply_rolls_back_whole_import_on_error(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [
            [46050, "P1", "", "", "", "", 10, ""],
            [46051, "P2", "", "", "", "", 20, ""],
        ],
        [["P1", "", "P1", "", ""], ["P2", "", "P2", "", ""]],
    )
    insert_user(db_path, 1, "P1")
    insert_user(db_path, 2, "P2")
    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DROP TABLE tournament_results")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.OperationalError):
        import_rating_history.apply_import_plan(plan)

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == 0
    finally:
        connection.close()


def test_bad_db_path_does_not_create_database(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.db"
    source_path = tmp_path / "history.xlsx"
    write_workbook(source_path, [[46050, "P1", "", "", "", "", 10, ""]])

    with pytest.raises(import_rating_history.ImportValidationError):
        import_rating_history.build_import_plan(
            source_path=source_path,
            db_path=missing_db,
            aliases_path=None,
            strict_expectations=False,
        )

    assert not missing_db.exists()


def test_post_import_rating_aggregation(tmp_path: Path) -> None:
    db_path, source_path, _plan = build_plan(
        tmp_path,
        [
            [46050, "P1", "", "", "", 5, 10, 15],
            [46050, "P2", "", "", "", "", 20, ""],
        ],
        [["P1", "", "P1", "", ""], ["P2", "", "P2", "", ""]],
    )
    insert_user(db_path, 1, "P1")
    insert_user(db_path, 2, "P2")
    plan = import_rating_history.build_import_plan(
        source_path=source_path,
        db_path=db_path,
        aliases_path=None,
        strict_expectations=False,
    )
    import_rating_history.apply_import_plan(plan)
    verification = import_rating_history.verify_post_import(db_path, plan)

    assert verification["top20_plan"] == verification["top20_db"]
    assert verification["plan_points"] == verification["db_points"]
