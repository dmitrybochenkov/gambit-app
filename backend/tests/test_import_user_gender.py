import importlib.util
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.base import Base

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_user_gender.py"
spec = importlib.util.spec_from_file_location("import_user_gender", SCRIPT_PATH)
assert spec is not None
import_user_gender = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = import_user_gender
spec.loader.exec_module(import_user_gender)


def create_database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()


def insert_user(
    path: Path,
    user_id: int,
    display_name: str,
    *,
    gender: str | None = None,
) -> None:
    normalized = import_user_gender.normalize_display_name(display_name)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, display_name_normalized, gender,
                role, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'player', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id, display_name, normalized, gender),
        )
        connection.commit()
    finally:
        connection.close()


def user_gender(path: Path, user_id: int) -> str | None:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT gender FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()[0]
    finally:
        connection.close()


def write_gender_workbook(path: Path, rows: list[list[object]]) -> None:
    sheet_rows = [["user", "Пол"], *rows]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/xl/workbook.xml" ContentType="application/xml"/>
              <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/xml"/>
            </Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="officeDocument" Target="xl/workbook.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <workbook
              xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets>
                <sheet name="Лист12" sheetId="1" r:id="rId1"/>
              </sheets>
            </workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
            </Relationships>""",
        )
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(sheet_rows))


def _worksheet_xml(rows: list[list[object]]) -> str:
    rendered_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(values):
            reference = f"{chr(ord('A') + column_index)}{row_index}"
            text = "" if value is None else str(value)
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t>{_xml_escape(text)}</t></is></c>'
            )
        rendered_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rendered_rows)}</sheetData>"
        "</worksheet>"
    )


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def test_parse_source_gender_values() -> None:
    assert import_user_gender.parse_source_gender("м") == "male"
    assert import_user_gender.parse_source_gender("ж") == "female"
    assert import_user_gender.parse_source_gender(" ") is None
    with pytest.raises(import_user_gender.ImportValidationError):
        import_user_gender.parse_source_gender("x")


def test_gender_workbook_parser_reads_sheet12(tmp_path: Path) -> None:
    workbook = tmp_path / "rating.xlsx"
    write_gender_workbook(workbook, [["Анна", "ж"], ["Иван", "м"], ["Боба", ""]])

    rows = import_user_gender.load_source_rows(workbook)

    assert [(row.display_name, row.display_name_normalized, row.gender) for row in rows] == [
        ("Анна", "анна", "female"),
        ("Иван", "иван", "male"),
        ("Боба", "боба", None),
    ]


def test_gender_import_plan_categories_and_safe_updates() -> None:
    source_rows = (
        import_user_gender.SourceGenderRow(2, "Анна", "анна", "female"),
        import_user_gender.SourceGenderRow(3, "Иван", "иван", "male"),
        import_user_gender.SourceGenderRow(4, "Боба", "боба", None),
        import_user_gender.SourceGenderRow(5, "Нет В Базе", "нет в базе", "male"),
        import_user_gender.SourceGenderRow(6, "Дубль", "дубль", "female"),
    )
    users = (
        import_user_gender.DatabaseUser(1, "Анна", "анна", None),
        import_user_gender.DatabaseUser(2, "Иван", "иван", "female"),
        import_user_gender.DatabaseUser(3, "Боба", "боба", None),
        import_user_gender.DatabaseUser(4, "Дубль Один", "дубль", None),
        import_user_gender.DatabaseUser(5, "Дубль Два", "дубль", None),
        import_user_gender.DatabaseUser(6, "Новый", "новый", None),
    )

    plan = import_user_gender.build_plan(source_rows, users)

    assert plan.counts == {
        "matched": 1,
        "conflict": 1,
        "unknown_source": 1,
        "not_in_database": 1,
        "ambiguous": 1,
        "not_in_source": 1,
    }
    assert [(item.user.id, item.source.gender) for item in plan.safe_updates] == [(1, "female")]


def test_gender_import_dry_run_and_apply(tmp_path: Path) -> None:
    db_path = tmp_path / "gender.db"
    create_database(db_path)
    insert_user(db_path, 1, "Анна")
    insert_user(db_path, 2, "Иван", gender="male")
    source_rows = (
        import_user_gender.SourceGenderRow(2, "Анна", "анна", "female"),
        import_user_gender.SourceGenderRow(3, "Иван", "иван", "male"),
    )

    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        plan = import_user_gender.build_plan(source_rows, import_user_gender.load_users(connection))
    finally:
        connection.close()

    assert len(plan.safe_updates) == 1
    assert user_gender(db_path, 1) is None

    connection = sqlite3.connect(db_path)
    try:
        import_user_gender.apply_plan(connection, plan)
    finally:
        connection.close()

    assert user_gender(db_path, 1) == "female"
    assert user_gender(db_path, 2) == "male"
