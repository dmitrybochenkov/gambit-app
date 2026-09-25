import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PREVIOUS_REVISION = "bd2e3f4a5b6c"
HEAD_REVISION = "d4e5f6a7b8c9"
FINALIZATION_REVISION = "ce3f4a5b6c7d"


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


def _seed_representable_hall(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (951, 951, 'active', 'superadmin', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 'Hall curator', 'hall curator', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (952, NULL, 'active', 'player', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 'Hall winner', 'hall winner', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO seasons (id, name, starts_at, ends_at, scoring_config_id)
            VALUES (951, 'Hall season', '2026-01-01', '2026-03-31', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO season_hall_of_fame (
                season_id, champion_player_id, knockout_player_id,
                champion_photo_file_id, champion_photo_file_unique_id,
                knockout_photo_file_id, knockout_photo_file_unique_id,
                updated_by_user_id, created_at, updated_at
            ) VALUES (951, 952, NULL, NULL, NULL, NULL, NULL, 951,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.execute(
            """
            INSERT INTO hall_of_fame_achievements (
                season_id, player_id, kind, awarded_at, created_at, updated_at
            ) VALUES (951, 952, 'rating_winner', '2026-03-31',
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.execute(
            """
            INSERT INTO hall_of_fame_photos (
                season_id, telegram_file_id, telegram_file_unique_id,
                uploaded_by_user_id, position, created_at
            ) VALUES (951, 'hall-photo', 'hall-photo-unique', 951, 0,
                      CURRENT_TIMESTAMP)
            """
        )
        connection.commit()


def test_finalization_preserves_canonical_data_and_enforces_kind_semantics(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "hall-finalization.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_representable_hall(db_path)

    _alembic(db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            HEAD_REVISION,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='season_hall_of_fame'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT season_id, player_id, kind, awarded_at FROM hall_of_fame_achievements"
        ).fetchall() == [(951, 952, "rating_winner", "2026-03-31")]
        assert connection.execute(
            "SELECT telegram_file_id FROM hall_of_fame_photos"
        ).fetchall() == [("hall-photo",)]

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO hall_of_fame_achievements (
                    season_id, player_id, kind, awarded_at, created_at, updated_at
                ) VALUES (951, 952, 'rating_winner', '2026-03-30',
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        connection.rollback()

        for _ in range(2):
            connection.execute(
                """
                INSERT INTO hall_of_fame_achievements (
                    season_id, player_id, kind, awarded_at, created_at, updated_at
                ) VALUES (951, 952, 'grand_month', '2026-03-01',
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM hall_of_fame_achievements WHERE kind='grand_month'"
        ).fetchone() == (2,)


def test_finalization_downgrade_restores_representable_legacy_data(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-finalization-downgrade.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_representable_hall(db_path)
    _alembic(db_path, "upgrade", "head")

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT champion_player_id, champion_photo_file_id
            FROM season_hall_of_fame WHERE season_id=951
            """
        ).fetchone() == (952, "hall-photo")
        assert connection.execute("SELECT COUNT(*) FROM hall_of_fame_achievements").fetchone() == (
            1,
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_finalization_downgrade_fails_closed_for_grand_achievement(tmp_path: Path) -> None:
    db_path = tmp_path / "hall-finalization-fail-closed.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_representable_hall(db_path)
    _alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO hall_of_fame_achievements (
                season_id, player_id, kind, awarded_at, created_at, updated_at
            ) VALUES (951, 952, 'grand_season', '2026-03-31',
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()

    failed = _alembic(db_path, "downgrade", PREVIOUS_REVISION, check=False)

    assert failed.returncode != 0
    assert "grand achievements cannot be represented" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            FINALIZATION_REVISION,
        )
        assert connection.execute("SELECT COUNT(*) FROM hall_of_fame_achievements").fetchone() == (
            2,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='season_hall_of_fame'"
        ).fetchone() == (0,)
