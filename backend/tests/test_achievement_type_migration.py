import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "ce3f4a5b6c7d"
TARGET_REVISION = "d4e5f6a7b8c9"


def _alembic(db_path: Path, *arguments: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_achievement_occurrence(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (991, 991, 'active', 'player', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 'Winner', 'winner', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO seasons (id, name, starts_at, ends_at, scoring_config_id)
            VALUES (991, 'Achievement season', '2026-01-01', '2026-03-31', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO hall_of_fame_achievements (
                id, season_id, player_id, kind, awarded_at, created_at, updated_at
            ) VALUES (991, 991, 991, 'rating_winner', '2026-03-31',
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()


def test_achievement_type_migration_seeds_dictionary_and_preserves_occurrences(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "achievement-types.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_achievement_occurrence(db_path)

    _alembic(db_path, "upgrade", TARGET_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT kind, title, emoji, custom_emoji_id
            FROM achievement_types ORDER BY kind
            """
        ).fetchall() == [
            ("grand_knockout", "Победитель Grand Knockout", "🥊", None),
            ("grand_month", "Победитель Grand Month", "🏅", None),
            ("grand_season", "Победитель Grand Season", "🏆", None),
            ("ko_rating_winner", "Лучший нокаутер сезона", "💥", None),
            ("rating_winner", "Победитель рейтингового сезона", "💍", None),
        ]
        assert connection.execute(
            """
            SELECT id, season_id, player_id, kind, awarded_at
            FROM hall_of_fame_achievements
            """
        ).fetchall() == [(991, 991, 991, "rating_winner", "2026-03-31")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='achievement_types'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT id, kind FROM hall_of_fame_achievements").fetchall() == [
            (991, "rating_winner")
        ]
