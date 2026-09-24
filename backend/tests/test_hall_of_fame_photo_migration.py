import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "ac1d2e3f4a5b"


def _alembic(
    db_path: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _seed_legacy_photos(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (901, NULL, 'active', 'superadmin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      'Photo curator', 'photo curator', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO seasons (id, name, starts_at, ends_at, scoring_config_id)
            VALUES (901, 'Photo season', '2026-01-01', NULL, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO season_hall_of_fame (
                season_id, champion_player_id, knockout_player_id,
                champion_photo_file_id, champion_photo_file_unique_id,
                knockout_photo_file_id, knockout_photo_file_unique_id,
                updated_by_user_id, created_at, updated_at
            ) VALUES (
                901, NULL, NULL, 'photo-one', 'unique-one',
                'photo-two', 'unique-two', 901, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def test_hall_of_fame_photo_migration_preserves_legacy_photos(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-photos.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_legacy_photos(db_path)

    _alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT season_id, telegram_file_id, telegram_file_unique_id, position
            FROM hall_of_fame_photos ORDER BY position, id
            """
        ).fetchall() == [
            (901, "photo-one", "unique-one", 0),
            (901, "photo-two", "unique-two", 1),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT champion_photo_file_id, champion_photo_file_unique_id,
                   knockout_photo_file_id, knockout_photo_file_unique_id
            FROM season_hall_of_fame WHERE season_id = 901
            """
        ).fetchone() == ("photo-one", "unique-one", "photo-two", "unique-two")
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'hall_of_fame_photos'"
        ).fetchone() == (0,)


def test_hall_of_fame_photo_downgrade_refuses_more_than_two_photos(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-photos-fail-closed.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_legacy_photos(db_path)
    _alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO hall_of_fame_photos (
                season_id, telegram_file_id, telegram_file_unique_id,
                uploaded_by_user_id, position, created_at
            ) VALUES (901, 'photo-three', 'unique-three', 901, 2, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()

    failed = _alembic(db_path, "downgrade", PREVIOUS_REVISION, check=False)

    assert failed.returncode != 0
    assert "more than two photos" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM hall_of_fame_photos").fetchone() == (3,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "ce3f4a5b6c7d",
        )
