import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "7f8a9b0c1d2e"
UNIQUE_CONSTRAINT = "uq_tournament_combinations_tournament_player_type"
EXPECTED_INDEXES = {
    "ix_tournament_combinations_combination_type",
    "ix_tournament_combinations_player_id",
    "ix_tournament_combinations_tournament_id",
}


def _run_alembic(
    backend_root: Path,
    env: dict[str, str],
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend_root,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _seed_existing_combination(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, telegram_id, status, role, created_at, updated_at,
                display_name, display_name_normalized, gender
            ) VALUES (101, NULL, 'active', 'player', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      'Migration player', 'migration player', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO tournaments (
                id, season_id, date, tournament_fund, status, created_at, updated_at,
                tournament_type_id, registration_open, scoring_config_id
            ) VALUES (201, 3, '2026-09-18', NULL, 'active', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, 1, 0, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO tournament_combinations (
                id, tournament_id, player_id, combination_type, created_at, rank
            ) VALUES (301, 201, 101, 'four_of_a_kind', CURRENT_TIMESTAMP, 'A')
            """
        )
        connection.commit()


def test_repeated_tournament_combinations_migration_preserves_schema_and_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "repeated-combinations.db"
    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    _run_alembic(backend_root, env, "upgrade", PREVIOUS_REVISION)
    _seed_existing_combination(db_path)
    _run_alembic(backend_root, env, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        table_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'tournament_combinations'
            """
        ).fetchone()[0]
        indexes = connection.execute("PRAGMA index_list(tournament_combinations)").fetchall()
        columns = connection.execute("PRAGMA table_info(tournament_combinations)").fetchall()
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(tournament_combinations)"
        ).fetchall()
        existing = connection.execute(
            """
            SELECT id, tournament_id, player_id, combination_type, rank
            FROM tournament_combinations
            """
        ).fetchall()

        assert UNIQUE_CONSTRAINT not in table_sql
        assert "ck_tournament_combinations_type" in table_sql
        assert "ck_tournament_combinations_rank" in table_sql
        assert {row[1] for row in indexes} == EXPECTED_INDEXES
        assert all(row[2] == 0 for row in indexes)
        assert next(row for row in columns if row[1] == "id")[5] == 1
        assert {(row[2], row[3], row[4], row[6]) for row in foreign_keys} == {
            ("users", "player_id", "id", "RESTRICT"),
            ("tournaments", "tournament_id", "id", "CASCADE"),
        }
        assert existing == [(301, 201, 101, "four_of_a_kind", "A")]

        connection.execute(
            """
            INSERT INTO tournament_combinations (
                id, tournament_id, player_id, combination_type, created_at, rank
            ) VALUES (302, 201, 101, 'four_of_a_kind', CURRENT_TIMESTAMP, 'A')
            """
        )
        connection.commit()

    failed_downgrade = _run_alembic(
        backend_root,
        env,
        "downgrade",
        PREVIOUS_REVISION,
        check=False,
    )
    assert failed_downgrade.returncode != 0

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT id FROM tournament_combinations ORDER BY id"
        ).fetchall() == [(301,), (302,)]


def test_repeated_tournament_combinations_downgrade_restores_unique_when_valid(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "unique-combinations.db"
    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    _run_alembic(backend_root, env, "upgrade", "head")
    _seed_existing_combination(db_path)
    _run_alembic(backend_root, env, "downgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        table_sql = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'tournament_combinations'
            """
        ).fetchone()[0]
        assert UNIQUE_CONSTRAINT in table_sql
        assert connection.execute("SELECT id FROM tournament_combinations").fetchall() == [(301,)]
