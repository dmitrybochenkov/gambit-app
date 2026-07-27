import csv
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.base import Base

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_historical_users.py"
HISTORICAL_USERS_CSV = Path("/Users/dmitriybocenkov/Projects/historical_users_with_admins.csv")
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


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["id", "display_name", "role", "status", "telegram_id"],
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
