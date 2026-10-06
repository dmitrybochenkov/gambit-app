import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "f6a7b8c9d0e2"
TARGET_REVISION = "0a1b2c3d4e5f"


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


def _type_snapshot(connection: sqlite3.Connection, code: str) -> tuple[object, ...]:
    return connection.execute(
        """
        SELECT t.id, t.name, t.short_name, t.calendar_code, t.description, t.is_creatable,
               e.entry_fee, e.entry_stack, e.addon_fee, e.addon_stack,
               r.points_multiplier, r.prize_place_multiplier,
               r.prize_place_multiplier_places, r.knockout_mode, r.supports_bonus_points
        FROM tournament_types AS t
        JOIN tournament_economy_configs AS e ON e.tournament_type_id = t.id
        JOIN tournament_type_rules AS r ON r.tournament_type_id = t.id
        WHERE t.code = ?
        """,
        (code,),
    ).fetchone()


def _rebuys(connection: sqlite3.Connection, code: str) -> list[tuple[int, int, int]]:
    return connection.execute(
        """
        SELECT rebuy_order, fee, stack
        FROM tournament_rebuy_configs
        WHERE tournament_type_id = (SELECT id FROM tournament_types WHERE code = ?)
        ORDER BY rebuy_order
        """,
        (code,),
    ).fetchall()


def _seed_historical_freeroll_tournament(connection: sqlite3.Connection) -> int:
    freeroll_id = connection.execute(
        "SELECT id FROM tournament_types WHERE code = 'classic_v3'"
    ).fetchone()[0]
    season_id = connection.execute("SELECT id FROM seasons ORDER BY id LIMIT 1").fetchone()[0]
    scoring_id = connection.execute(
        "SELECT scoring_config_id FROM seasons WHERE id = ?", (season_id,)
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO tournaments (
            id, season_id, scoring_config_id, tournament_type_id, date,
            tournament_fund, status, registration_open, created_at, updated_at
        ) VALUES (990, ?, ?, ?, '2026-10-31', NULL, 'active', 0,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (season_id, scoring_id, freeroll_id),
    )
    connection.commit()
    return freeroll_id


def test_upgrade_preserves_freeroll_identity_and_clones_classic_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "freeroll-classic-v3.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)

    with sqlite3.connect(db_path) as connection:
        old_freeroll = _type_snapshot(connection, "classic_v3")
        classic_v2 = _type_snapshot(connection, "classic_v2")
        classic_v2_rebuys = _rebuys(connection, "classic_v2")
        old_freeroll_rebuys = _rebuys(connection, "classic_v3")
        old_freeroll_id = _seed_historical_freeroll_tournament(connection)

    _alembic(db_path, "upgrade", TARGET_REVISION)

    with sqlite3.connect(db_path) as connection:
        freeroll = _type_snapshot(connection, "freeroll")
        classic_v3 = _type_snapshot(connection, "classic_v3")
        assert freeroll == old_freeroll
        assert _rebuys(connection, "freeroll") == old_freeroll_rebuys
        assert connection.execute(
            """
            SELECT t.tournament_type_id, tt.code, tt.name
            FROM tournaments AS t
            JOIN tournament_types AS tt ON tt.id = t.tournament_type_id
            WHERE t.id = 990
            """
        ).fetchone() == (old_freeroll_id, "freeroll", "Freeroll")
        assert classic_v3[0] != old_freeroll_id
        assert classic_v3[1:6] == (
            "Классика 3",
            "Классика 3",
            "C3",
            classic_v2[4],
            1,
        )
        assert classic_v3[6] == 800
        assert classic_v3[7:] == classic_v2[7:]
        assert _rebuys(connection, "classic_v3") == classic_v2_rebuys
        assert _type_snapshot(connection, "classic_v2") == classic_v2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    _alembic(db_path, "downgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert _type_snapshot(connection, "classic_v3") == old_freeroll
        assert connection.execute(
            "SELECT tournament_type_id FROM tournaments WHERE id = 990"
        ).fetchone() == (old_freeroll_id,)


def test_downgrade_refuses_referenced_new_classic_v3(tmp_path: Path) -> None:
    db_path = tmp_path / "referenced-classic-v3.db"
    _alembic(db_path, "upgrade", TARGET_REVISION)
    with sqlite3.connect(db_path) as connection:
        season_id = connection.execute("SELECT id FROM seasons ORDER BY id LIMIT 1").fetchone()[0]
        scoring_id = connection.execute(
            "SELECT scoring_config_id FROM seasons WHERE id = ?", (season_id,)
        ).fetchone()[0]
        classic_v3_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'classic_v3'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO tournaments (
                id, season_id, scoring_config_id, tournament_type_id, date,
                tournament_fund, status, registration_open, created_at, updated_at
            ) VALUES (991, ?, ?, ?, '2026-11-01', NULL, 'active', 0,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (season_id, scoring_id, classic_v3_id),
        )
        connection.commit()

    failed = _alembic(db_path, "downgrade", PREVIOUS_REVISION, check=False)

    assert failed.returncode != 0
    assert "Cannot downgrade while Classic v3 is referenced" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT code FROM tournament_types WHERE id = ?", (classic_v3_id,)
        ).fetchone() == ("classic_v3",)
        assert connection.execute(
            "SELECT tournament_type_id FROM tournaments WHERE id = 991"
        ).fetchone() == (classic_v3_id,)
