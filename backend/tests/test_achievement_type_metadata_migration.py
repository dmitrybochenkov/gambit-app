import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "e5f6a7b8c9d1"
TARGET_REVISION = "f6a7b8c9d0e2"

CANONICAL_METADATA = [
    ("grand_knockout", "Победитель Grand Knockout", "🥊"),
    ("grand_month", "Победитель Grand Month", "🏅"),
    ("grand_season", "Победитель Grand Season", "💍"),
    ("ko_rating_winner", "Победитель KO Season Rating", "💥"),
    ("rating_winner", "Победитель Season Rating", "🏆"),
]

PREVIOUS_METADATA = [
    ("grand_knockout", "Победитель Grand Knockout", "🥊"),
    ("grand_month", "Победитель Grand Month", "🏅"),
    ("grand_season", "Победитель Grand Season", "🏆"),
    ("ko_rating_winner", "Лучший нокаутер сезона", "💥"),
    ("rating_winner", "Победитель рейтингового сезона", "💍"),
]


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


def _metadata(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT kind, title, emoji FROM achievement_types ORDER BY kind"
    ).fetchall()


def _seed_existing_data(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (981, 981, 'active', 'player', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 'Winner', 'winner', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO seasons (id, name, starts_at, ends_at, scoring_config_id)
            VALUES (981, 'Metadata season', '2026-01-01', '2026-03-31', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO hall_of_fame_achievements (
                id, season_id, player_id, kind, awarded_at, created_at, updated_at
            ) VALUES (981, 981, 981, 'rating_winner', '2026-03-31',
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        for index, (kind, _title, _emoji) in enumerate(PREVIOUS_METADATA, start=1):
            connection.execute(
                "UPDATE achievement_types SET custom_emoji_id = ? WHERE kind = ?",
                (f"custom-{index}", kind),
            )
        connection.commit()


def test_metadata_upgrade_and_downgrade_preserve_occurrence_identity_and_custom_emoji(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "achievement-metadata-upgrade.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    _seed_existing_data(db_path)

    _alembic(db_path, "upgrade", TARGET_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert _metadata(connection) == CANONICAL_METADATA
        assert connection.execute(
            "SELECT kind, custom_emoji_id FROM achievement_types ORDER BY kind"
        ).fetchall() == [
            (kind, f"custom-{index}")
            for index, (kind, _title, _emoji) in enumerate(PREVIOUS_METADATA, start=1)
        ]
        assert connection.execute(
            """
            SELECT id, season_id, player_id, kind, awarded_at
            FROM hall_of_fame_achievements
            """
        ).fetchall() == [(981, 981, 981, "rating_winner", "2026-03-31")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert _metadata(connection) == PREVIOUS_METADATA
        assert connection.execute(
            "SELECT kind, custom_emoji_id FROM achievement_types ORDER BY kind"
        ).fetchall() == [
            (kind, f"custom-{index}")
            for index, (kind, _title, _emoji) in enumerate(PREVIOUS_METADATA, start=1)
        ]
        assert connection.execute(
            "SELECT id, season_id, player_id, kind FROM hall_of_fame_achievements"
        ).fetchall() == [(981, 981, 981, "rating_winner")]


def test_fresh_head_has_canonical_achievement_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "achievement-metadata-fresh.db"

    _alembic(db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        assert _metadata(connection) == CANONICAL_METADATA
