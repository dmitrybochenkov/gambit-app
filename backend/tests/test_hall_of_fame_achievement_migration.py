import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "9b0c1d2e3f4a"


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


def test_hall_of_fame_occurrence_migration_preserves_legacy_data(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-of-fame-occurrences.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES
                (901, NULL, 'active', 'player', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                 'Champion', 'champion', NULL),
                (902, NULL, 'active', 'player', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                 'Knockout', 'knockout', NULL),
                (903, NULL, 'active', 'superadmin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                 'Curator', 'curator', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO seasons (
                id, name, starts_at, ends_at, scoring_config_id
            ) VALUES
            (
                901, 'Migration season', '2026-01-01', '2026-03-31', 1
            ),
            (
                902, 'Empty season', '2026-04-01', '2026-06-30', 1
            )
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
                901, 901, 902, 'champion-photo', 'champion-unique',
                'knockout-photo', 'knockout-unique', 903,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO season_hall_of_fame (
                season_id, champion_player_id, knockout_player_id,
                updated_by_user_id, created_at, updated_at
            ) VALUES (902, NULL, NULL, 903, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()

    _alembic(db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT season_id, player_id, kind, awarded_at
            FROM hall_of_fame_achievements
            WHERE season_id = 901
            ORDER BY id
            """
        ).fetchall() == [
            (901, 901, "rating_winner", "2026-03-31"),
            (901, 902, "ko_rating_winner", "2026-03-31"),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM hall_of_fame_achievements WHERE season_id = 902"
        ).fetchone() == (0,)
        assert connection.execute(
            """
            SELECT champion_photo_file_id, champion_photo_file_unique_id,
                   knockout_photo_file_id, knockout_photo_file_unique_id
            FROM season_hall_of_fame WHERE season_id = 901
            """
        ).fetchone() == (
            "champion-photo",
            "champion-unique",
            "knockout-photo",
            "knockout-unique",
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT champion_player_id, knockout_player_id,
                   champion_photo_file_id, knockout_photo_file_id
            FROM season_hall_of_fame WHERE season_id = 901
            """
        ).fetchone() == (901, 902, "champion-photo", "knockout-photo")
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'hall_of_fame_achievements'"
        ).fetchone() == (0,)


def test_hall_of_fame_downgrade_refuses_unrepresented_legacy_slot(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-of-fame-open-season.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (901, NULL, 'active', 'player', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      'Open champion', 'open champion', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO season_hall_of_fame (
                season_id, champion_player_id, knockout_player_id,
                updated_by_user_id, created_at, updated_at
            ) VALUES (3, 901, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()

    _alembic(db_path, "upgrade", "head")
    failed = _alembic(db_path, "downgrade", PREVIOUS_REVISION, check=False)

    assert failed.returncode != 0
    assert "cannot be represented by legacy slots" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT champion_player_id FROM season_hall_of_fame WHERE season_id = 3"
        ).fetchone() == (901,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "ac1d2e3f4a5b",
        )
