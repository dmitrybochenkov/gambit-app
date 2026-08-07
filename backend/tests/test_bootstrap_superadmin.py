import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.db.base import Base

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_superadmin.py"


def _create_db(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('test')"))
    engine.dispose()


def _users(path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute("SELECT * FROM users ORDER BY id"))
    finally:
        connection.close()


def test_bootstrap_superadmin_creates_user(tmp_path: Path) -> None:
    db_path = tmp_path / "bootstrap.db"
    _create_db(db_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db",
            str(db_path),
            "--telegram-id",
            "100",
            "--display-name",
            " Дима   Боченков ",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    users = _users(db_path)
    assert "Created ACTIVE SUPERADMIN." in result.stdout
    assert len(users) == 1
    assert users[0]["telegram_id"] == 100
    assert users[0]["display_name"] == "Дима   Боченков"
    assert users[0]["display_name_normalized"] == "дима боченков"
    assert users[0]["role"] == "superadmin"
    assert users[0]["status"] == "active"


def test_bootstrap_superadmin_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "bootstrap.db"
    _create_db(db_path)
    command = [
        sys.executable,
        str(SCRIPT),
        "--db",
        str(db_path),
        "--telegram-id",
        "100",
        "--display-name",
        "Дима Боченков",
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    assert "no changes" in result.stdout
    assert len(_users(db_path)) == 1


def test_bootstrap_superadmin_requires_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db",
            str(db_path),
            "--telegram-id",
            "100",
            "--display-name",
            "Дима Боченков",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not db_path.exists()
    assert "Database does not exist" in result.stderr
