import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PRE_DISPLAY_NAME_REVISION = "b8c2e4f6a9d1"


def run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def upgrade_to_pre_display_name(db_path: Path) -> None:
    result = run_alembic(db_path, "upgrade", PRE_DISPLAY_NAME_REVISION)
    assert result.returncode == 0, result.stderr


def insert_legacy_player(
    db_path: Path,
    *,
    telegram_id: int,
    full_name: str | None,
    nickname: str | None,
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO players (
                telegram_id,
                full_name,
                full_name_normalized,
                nickname,
                nickname_normalized,
                status,
                role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'active', 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                telegram_id,
                full_name,
                full_name.casefold() if full_name else None,
                nickname,
                nickname.casefold() if nickname else None,
            ),
        )


def test_display_name_migration_transfers_single_legacy_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "display_name_success.db"
    upgrade_to_pre_display_name(db_path)
    insert_legacy_player(
        db_path,
        telegram_id=100,
        full_name="  Ёж   Troy ",
        nickname=None,
    )
    insert_legacy_player(
        db_path,
        telegram_id=200,
        full_name=None,
        nickname="Ace",
    )

    result = run_alembic(db_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_path) as connection:
        players = connection.execute(
            """
            SELECT telegram_id, display_name, display_name_normalized
            FROM players
            ORDER BY telegram_id
            """
        ).fetchall()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(players)").fetchall()}
    assert players == [
        (100, "  Ёж   Troy ", "еж troy"),
        (200, "Ace", "ace"),
    ]
    assert "display_name" in columns
    assert "display_name_normalized" in columns
    assert "full_name" not in columns
    assert "nickname" not in columns


@pytest.mark.parametrize(
    ("full_name", "nickname", "message"),
    [
        (
            "Иван Иванов",
            "Ace",
            "Cannot migrate players with both full_name and nickname set",
        ),
        (
            None,
            None,
            "Cannot migrate players without full_name or nickname",
        ),
    ],
)
def test_display_name_migration_rejects_ambiguous_legacy_identity(
    tmp_path: Path,
    full_name: str | None,
    nickname: str | None,
    message: str,
) -> None:
    db_path = tmp_path / "display_name_error.db"
    upgrade_to_pre_display_name(db_path)
    insert_legacy_player(
        db_path,
        telegram_id=100,
        full_name=full_name,
        nickname=nickname,
    )

    result = run_alembic(db_path, "upgrade", "head")

    assert result.returncode != 0
    assert message in result.stderr
