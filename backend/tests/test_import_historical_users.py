import csv
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.base import Base

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_historical_users.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
HISTORICAL_USERS_CSV = FIXTURES_DIR / "historical_users_with_admins.csv"
PROJECT_ROOT = SCRIPT_PATH.parents[1]
spec = importlib.util.spec_from_file_location("import_historical_users", SCRIPT_PATH)
assert spec is not None
import_historical_users = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = import_historical_users
spec.loader.exec_module(import_historical_users)


def create_database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version (version_num) VALUES ('test-head')")
        connection.commit()
    finally:
        connection.close()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["id", "display_name", "role", "status", "telegram_id"]
    if any("display_name_normalized" in row for row in rows):
        fieldnames.append("display_name_normalized")
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)


def read_users(path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute("SELECT * FROM users ORDER BY id"))
    finally:
        connection.close()


def count_users(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    finally:
        connection.close()


def build_plan(db_path: Path, csv_path: Path) -> import_historical_users.ImportPlan:
    return import_historical_users.build_import_plan(source=csv_path, db_path=db_path)


def run_user_import_cli(
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


def test_import_historical_users_success(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859.0",
            },
            {
                "id": "2",
                "display_name": "Antony Easy",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )

    rows = import_historical_users.load_rows(csv_path)
    stats = import_historical_users.import_users(db_path=db_path, rows=rows)
    users = read_users(db_path)

    assert stats.rows_read == 2
    assert stats.users_created == 2
    assert stats.users_skipped == 0
    assert stats.max_imported_id == 2
    assert [(user["id"], user["display_name"]) for user in users] == [
        (1, "Дима Боченков"),
        (2, "Antony Easy"),
    ]
    assert users[0]["role"] == "superadmin"
    assert users[0]["telegram_id"] == 754076859


def test_import_historical_users_dry_run_does_not_change_database(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "SAFE TO APPLY"
    assert len(plan.creates) == 1
    assert count_users(db_path) == 0


def test_import_historical_users_cli_default_is_dry_run(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )

    result = run_user_import_cli("--input", str(csv_path), "--db", str(db_path), cwd=PROJECT_ROOT)

    assert result.returncode == 0
    assert "create: 1" in result.stdout
    assert "verdict: SAFE TO APPLY" in result.stdout
    assert count_users(db_path) == 0


def test_import_historical_users_cli_apply_changes_database(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )

    result = run_user_import_cli(
        "--input",
        str(csv_path),
        "--db",
        str(db_path),
        "--apply",
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 0
    assert "Users created: 1" in result.stdout
    assert count_users(db_path) == 1


def test_import_historical_users_cli_export_report_accepts_absolute_paths(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    report_dir = tmp_path / "report"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    result = run_user_import_cli(
        "--input",
        str(csv_path.resolve()),
        "--db",
        str(db_path.resolve()),
        "--export-report",
        str(report_dir.resolve()),
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert {path.name for path in report_dir.iterdir()} == {
        "summary.json",
        "creates.csv",
        "unchanged.csv",
        "conflicts.csv",
        "invalid.csv",
    }
    assert count_users(db_path) == 0


def test_import_historical_users_cli_missing_db_does_not_create_file(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "users.csv"
    missing_db = tmp_path / "missing.db"
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    result = run_user_import_cli("--input", str(csv_path), "--db", str(missing_db), cwd=tmp_path)

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert not missing_db.exists()


def test_import_historical_users_reports_create_and_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=1,
                display_name="Дима Боченков",
                display_name_normalized="дима боченков",
                role=import_historical_users.UserRole.SUPERADMIN,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=754076859,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            },
            {
                "id": "2",
                "display_name": "Antony Easy",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "SAFE TO APPLY"
    assert [action.row.id for action in plan.unchanged] == [1]
    assert [action.row.id for action in plan.creates] == [2]
    assert plan.role_distribution == {"player": 1, "superadmin": 1}
    assert plan.status_distribution == {"active": 2}
    assert plan.telegram_ids_count == 1


def test_import_historical_users_rejects_missing_database_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "users.csv"
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    with pytest.raises(import_historical_users.ImportValidationError, match="does not exist"):
        build_plan(tmp_path / "missing.db", csv_path)

    assert not (tmp_path / "missing.db").exists()


def test_import_historical_users_rejects_missing_users_table(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    csv_path = tmp_path / "users.csv"
    sqlite3.connect(db_path).close()
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    with pytest.raises(import_historical_users.ImportValidationError, match="users"):
        build_plan(db_path, csv_path)


def test_import_historical_users_rejects_missing_alembic_version(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    with pytest.raises(import_historical_users.ImportValidationError, match="alembic_version"):
        build_plan(db_path, csv_path)


def test_import_historical_users_keeps_empty_telegram_id_as_null(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Antony Easy",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    import_historical_users.import_users(
        db_path=db_path,
        rows=import_historical_users.load_rows(csv_path),
    )

    assert read_users(db_path)[0]["telegram_id"] is None


def test_import_historical_users_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )
    rows = import_historical_users.load_rows(csv_path)

    first = import_historical_users.import_users(db_path=db_path, rows=rows)
    second = import_historical_users.import_users(db_path=db_path, rows=rows)

    assert first.users_created == 1
    assert second.users_created == 0
    assert second.users_skipped == 1
    assert len(read_users(db_path)) == 1


def test_import_historical_users_allows_husband_case_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "8",
                "display_name": "Husband",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "12",
                "display_name": "husband",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )

    stats = import_historical_users.import_users(
        db_path=db_path,
        rows=import_historical_users.load_rows(csv_path),
    )
    users = read_users(db_path)

    assert stats.users_created == 2
    assert [(user["id"], user["display_name_normalized"]) for user in users] == [
        (8, "husband"),
        (12, "husband"),
    ]


def test_import_historical_users_allows_yo_e_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "108",
                "display_name": "Журавлев Антон",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "109",
                "display_name": "Журавлёв Антон",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )

    import_historical_users.import_users(
        db_path=db_path,
        rows=import_historical_users.load_rows(csv_path),
    )

    assert [user["display_name_normalized"] for user in read_users(db_path)] == [
        "журавлев антон",
        "журавлев антон",
    ]


def test_import_historical_users_imports_attached_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    create_database(db_path)
    rows = import_historical_users.load_rows(HISTORICAL_USERS_CSV)

    stats = import_historical_users.import_users(db_path=db_path, rows=rows)

    assert stats.rows_read == len(rows)
    assert stats.users_created == len(rows)
    assert stats.users_skipped == 0
    assert len(read_users(db_path)) == len(rows)


def test_import_historical_users_default_input_path_is_project_relative() -> None:
    assert import_historical_users.default_input_path() == (
        SCRIPT_PATH.parents[1] / "data" / "historical_users_with_admins.csv"
    )


def test_import_historical_users_resolves_custom_input_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "custom.csv"

    assert (
        import_historical_users.resolve_input_path(
            positional_source=csv_path,
            option_source=None,
        )
        == csv_path
    )
    assert (
        import_historical_users.resolve_input_path(
            positional_source=None,
            option_source=csv_path,
        )
        == csv_path
    )


def test_import_historical_users_rejects_two_input_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "custom.csv"

    with pytest.raises(import_historical_users.ImportValidationError, match="either"):
        import_historical_users.resolve_input_path(
            positional_source=csv_path,
            option_source=csv_path,
        )


def test_import_historical_users_detects_id_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )
    rows = import_historical_users.load_rows(csv_path)
    import_historical_users.import_users(db_path=db_path, rows=rows)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Другой Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    with pytest.raises(import_historical_users.ImportValidationError, match="different data"):
        import_historical_users.import_users(
            db_path=db_path,
            rows=import_historical_users.load_rows(csv_path),
        )


def test_import_historical_users_reports_same_id_display_name_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=1,
                display_name="Дима Боченков",
                display_name_normalized="дима боченков",
                role=import_historical_users.UserRole.SUPERADMIN,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=754076859,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Другой Игрок",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.conflicts[0].reason == "same id exists with different data"
    assert plan.conflicts[0].diff == {
        "display_name": {"existing": "Дима Боченков", "incoming": "Другой Игрок"},
        "display_name_normalized": {
            "existing": "дима боченков",
            "incoming": "другой игрок",
        },
    }


def test_import_historical_users_reports_same_id_telegram_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=1,
                display_name="Дима Боченков",
                display_name_normalized="дима боченков",
                role=import_historical_users.UserRole.SUPERADMIN,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=754076859,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "SUPERADMIN",
                "status": "ACTIVE",
                "telegram_id": "123",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.conflicts[0].diff == {"telegram_id": {"existing": 754076859, "incoming": 123}}


def test_import_historical_users_reports_new_id_occupied_telegram_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=1,
                display_name="Дима Боченков",
                display_name_normalized="дима боченков",
                role=import_historical_users.UserRole.SUPERADMIN,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=754076859,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "2",
                "display_name": "Другой Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "754076859",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.conflicts[0].reason == "new id uses occupied telegram_id"
    assert plan.conflicts[0].existing["id"] == 1
    assert len(plan.creates) == 0


def test_import_historical_users_reports_duplicate_id_in_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "1",
                "display_name": "Второй Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.duplicate_ids[0].source_rows == (2, 3)
    assert plan.conflicts[0].reason == "duplicate id in CSV"


def test_import_historical_users_reports_duplicate_telegram_id_in_csv(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "111",
            },
            {
                "id": "2",
                "display_name": "Второй Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "111",
            },
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.duplicate_telegram_ids[0].source_rows == (2, 3)
    assert plan.conflicts[0].reason == "duplicate telegram_id in CSV"


def test_import_historical_users_rejects_invalid_role(tmp_path: Path) -> None:
    csv_path = tmp_path / "users.csv"
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "OWNER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    with pytest.raises(import_historical_users.ImportValidationError, match="invalid role"):
        import_historical_users.load_rows(csv_path)


def test_import_historical_users_reports_invalid_role_in_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "OWNER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert plan.rows_read == 1
    assert len(plan.invalid) == 1
    assert "invalid role" in plan.invalid[0].reason


def test_import_historical_users_reports_invalid_status_in_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Дима Боченков",
                "role": "PLAYER",
                "status": "PENDING",
                "telegram_id": "",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert len(plan.invalid) == 1
    assert "invalid status" in plan.invalid[0].reason


def test_import_historical_users_reports_invalid_normalized_name(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Ёж",
                "display_name_normalized": "ёж",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    plan = build_plan(db_path, csv_path)

    assert plan.verdict == "NOT SAFE TO APPLY"
    assert len(plan.invalid) == 1
    assert "display_name_normalized" in plan.invalid[0].reason


def test_import_historical_users_apply_blocked_by_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=1,
                display_name="Дима Боченков",
                display_name_normalized="дима боченков",
                role=import_historical_users.UserRole.PLAYER,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=None,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Другой Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )
    plan = build_plan(db_path, csv_path)

    with pytest.raises(import_historical_users.ImportValidationError, match="NOT SAFE"):
        import_historical_users.apply_import_plan(plan)

    assert read_users(db_path)[0]["display_name"] == "Дима Боченков"


def test_import_historical_users_rolls_back_on_error(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    import_historical_users.import_users(
        db_path=db_path,
        rows=[
            import_historical_users.ImportUserRow(
                source_row=2,
                id=10,
                display_name="Занятый Игрок",
                display_name_normalized="занятый игрок",
                role=import_historical_users.UserRole.PLAYER,
                status=import_historical_users.UserStatus.ACTIVE,
                telegram_id=None,
            )
        ],
    )
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "10",
                "display_name": "Другой Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )
    rows = import_historical_users.load_rows(csv_path)

    with pytest.raises(import_historical_users.ImportValidationError, match="different data"):
        import_historical_users.import_users(db_path=db_path, rows=rows)

    assert [(user["id"], user["display_name"]) for user in read_users(db_path)] == [
        (10, "Занятый Игрок")
    ]


def test_import_historical_users_apply_plan_success(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "2",
                "display_name": "Второй Игрок",
                "role": "ADMIN",
                "status": "ACTIVE",
                "telegram_id": "222",
            },
        ],
    )
    plan = build_plan(db_path, csv_path)

    stats = import_historical_users.apply_import_plan(plan)

    assert stats.users_created == 2
    assert count_users(db_path) == 2
    assert read_users(db_path)[1]["role"] == "admin"


def test_import_historical_users_second_apply_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )

    first_plan = build_plan(db_path, csv_path)
    first = import_historical_users.apply_import_plan(first_plan)
    second_plan = build_plan(db_path, csv_path)
    second = import_historical_users.apply_import_plan(second_plan)

    assert first.users_created == 1
    assert second_plan.verdict == "SAFE TO APPLY"
    assert len(second_plan.creates) == 0
    assert len(second_plan.unchanged) == 1
    assert second.users_created == 0
    assert second.users_skipped == 1
    assert count_users(db_path) == 1


def test_import_historical_users_apply_rolls_back_whole_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "2",
                "display_name": "Второй Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )
    plan = build_plan(db_path, csv_path)
    original_insert = import_historical_users.insert_user

    def failing_insert(
        connection: sqlite3.Connection,
        row: import_historical_users.ImportUserRow,
    ) -> None:
        original_insert(connection, row)
        if row.id == 2:
            raise RuntimeError("boom")

    monkeypatch.setattr(import_historical_users, "insert_user", failing_insert)

    with pytest.raises(RuntimeError, match="boom"):
        import_historical_users.apply_import_plan(plan)

    assert count_users(db_path) == 0


def test_import_historical_users_exports_deterministic_report(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    first_report = tmp_path / "report-1"
    second_report = tmp_path / "report-2"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            }
        ],
    )
    plan = build_plan(db_path, csv_path)

    import_historical_users.export_report(plan, first_report)
    import_historical_users.export_report(plan, second_report)

    report_names = {
        "summary.json",
        "creates.csv",
        "unchanged.csv",
        "conflicts.csv",
        "invalid.csv",
    }
    assert {path.name for path in first_report.iterdir()} == report_names
    for name in report_names:
        assert (first_report / name).read_text(encoding="utf-8") == (
            second_report / name
        ).read_text(encoding="utf-8")


def test_import_historical_users_next_auto_id_after_import(tmp_path: Path) -> None:
    db_path = tmp_path / "gambit.db"
    csv_path = tmp_path / "users.csv"
    create_database(db_path)
    write_csv(
        csv_path,
        [
            {
                "id": "1",
                "display_name": "Первый Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
            {
                "id": "2",
                "display_name": "Второй Игрок",
                "role": "PLAYER",
                "status": "ACTIVE",
                "telegram_id": "",
            },
        ],
    )
    import_historical_users.import_users(
        db_path=db_path,
        rows=import_historical_users.load_rows(csv_path),
    )

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO users (
                    display_name,
                    display_name_normalized,
                    role,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    'Третий Игрок',
                    'третий игрок',
                    'player',
                    'active',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            )
        )
        next_id = result.scalar_one()
    engine.dispose()

    assert next_id == 3
