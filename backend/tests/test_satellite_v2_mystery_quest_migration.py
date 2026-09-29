import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PREVIOUS_REVISION = "d4e5f6a7b8c9"
TARGET_REVISION = "e5f6a7b8c9d1"


def _alembic(
    db_path: Path,
    *arguments: str,
    check: bool = True,
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


def _config(connection: sqlite3.Connection, code: str) -> tuple:
    return connection.execute(
        """
        SELECT tt.name, tt.short_name, tt.calendar_code, tt.is_creatable,
               ec.entry_fee, ec.entry_stack, ec.addon_fee, ec.addon_stack,
               rules.points_multiplier, rules.prize_place_multiplier,
               rules.knockout_mode, rules.supports_bonus_points
        FROM tournament_types AS tt
        JOIN tournament_economy_configs AS ec ON ec.tournament_type_id = tt.id
        JOIN tournament_type_rules AS rules ON rules.tournament_type_id = tt.id
        WHERE tt.code = ?
        """,
        (code,),
    ).fetchone()


def _insert_target(
    connection: sqlite3.Connection,
    *,
    code: str,
    name: str,
    calendar_code: str,
    entry_fee: int,
    entry_stack: int,
    addon_fee: int,
    addon_stack: int,
    rebuys: tuple[tuple[int, int, int], ...],
    supports_bonus_points: bool,
    description: str | None = None,
) -> int:
    connection.execute(
        """
        INSERT INTO tournament_types (
            code, name, short_name, calendar_code, description, is_creatable,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (code, name, name, calendar_code, description),
    )
    type_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.execute(
        """
        INSERT INTO tournament_economy_configs (
            tournament_type_id, entry_fee, entry_stack, addon_fee, addon_stack,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (type_id, entry_fee, entry_stack, addon_fee, addon_stack),
    )
    connection.execute(
        """
        INSERT INTO tournament_type_rules (
            tournament_type_id, points_multiplier, prize_place_multiplier,
            prize_place_multiplier_places, knockout_mode, supports_bonus_points,
            created_at, updated_at
        ) VALUES (?, 1, 1, NULL, 'none', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (type_id, int(supports_bonus_points)),
    )
    connection.executemany(
        """
        INSERT INTO tournament_rebuy_configs (
            tournament_type_id, rebuy_order, fee, stack, created_at, updated_at
        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        [(type_id, order, fee, stack) for order, fee, stack in rebuys],
    )
    return type_id


def _seed_old_satellite_template(connection: sqlite3.Connection) -> int:
    satellite_id = connection.execute(
        "SELECT id FROM tournament_types WHERE code = 'satellite'"
    ).fetchone()[0]
    connection.execute("DELETE FROM weekly_tournament_templates")
    connection.execute(
        """
        INSERT INTO weekly_tournament_templates (
            weekday, tournament_type_id, rotation_order, is_active,
            created_at, updated_at
        ) VALUES (5, ?, 2, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (satellite_id,),
    )
    return satellite_id


def test_satellite_v2_mystery_quest_migration_preserves_history_and_moves_template(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "formats.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        satellite_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'satellite'"
        ).fetchone()[0]
        season_id = connection.execute("SELECT id FROM seasons ORDER BY id LIMIT 1").fetchone()[0]
        scoring_id = connection.execute(
            "SELECT id FROM scoring_configs ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute("DELETE FROM weekly_tournament_templates")
        connection.execute(
            """
            INSERT INTO weekly_tournament_templates (
                weekday, tournament_type_id, rotation_order, is_active,
                created_at, updated_at
            ) VALUES (5, ?, 2, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (satellite_id,),
        )
        connection.execute(
            """
            INSERT INTO tournaments (
                season_id, date, tournament_fund, status, created_at, updated_at,
                tournament_type_id, registration_open, scoring_config_id
            ) VALUES (?, '2026-09-19', NULL, 'active', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, ?, 0, ?)
            """,
            (season_id, satellite_id, scoring_id),
        )
        historical_tournament_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        mystery_before = connection.execute(
            "SELECT * FROM tournament_types WHERE code = 'mystery_bounty'"
        ).fetchone()
        connection.commit()

    _alembic(db_path, "upgrade", TARGET_REVISION)
    with sqlite3.connect(db_path) as connection:
        satellite_v2_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'satellite_v2'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT calendar_code, is_creatable FROM tournament_types WHERE code = 'satellite'"
        ).fetchone() == ("S1", 0)
        assert _config(connection, "satellite_v2") == (
            "Satellite",
            "Satellite",
            "S2",
            1,
            1000,
            30000,
            1000,
            125000,
            1,
            1,
            "none",
            0,
        )
        assert connection.execute(
            """SELECT rebuy_order, fee, stack FROM tournament_rebuy_configs
               WHERE tournament_type_id = ? ORDER BY rebuy_order""",
            (satellite_v2_id,),
        ).fetchall() == [(1, 1000, 40000), (2, 1000, 50000), (3, 1000, 70000)]

        mystery_quest_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'mystery_quest'"
        ).fetchone()[0]
        assert _config(connection, "mystery_quest") == (
            "Mystery Quest",
            "Mystery Quest",
            "MQ",
            1,
            800,
            20000,
            800,
            125000,
            1,
            1,
            "none",
            1,
        )
        assert connection.execute(
            """SELECT rebuy_order, fee, stack FROM tournament_rebuy_configs
               WHERE tournament_type_id = ? ORDER BY rebuy_order""",
            (mystery_quest_id,),
        ).fetchall() == [
            (1, 800, 30000),
            (2, 800, 50000),
            (3, 800, 60000),
            (4, 1000, 80000),
            (5, 1000, 80000),
        ]
        assert connection.execute(
            """SELECT weekday, tournament_type_id, rotation_order
               FROM weekly_tournament_templates WHERE is_active = 1"""
        ).fetchall() == [(5, satellite_v2_id, 2)]
        assert connection.execute(
            "SELECT tournament_type_id FROM tournaments WHERE id = ?",
            (historical_tournament_id,),
        ).fetchone() == (satellite_id,)
        assert (
            connection.execute(
                "SELECT * FROM tournament_types WHERE code = 'mystery_bounty'"
            ).fetchone()
            == mystery_before
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_format_migration_accepts_matching_preexisting_satellite_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "matching-preexisting.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        description = connection.execute(
            "SELECT description FROM tournament_types WHERE code = 'satellite'"
        ).fetchone()[0]
        type_id = _insert_target(
            connection,
            code="satellite_v2",
            name="Satellite",
            calendar_code="S2",
            entry_fee=1000,
            entry_stack=30000,
            addon_fee=1000,
            addon_stack=125000,
            rebuys=((1, 1000, 40000), (2, 1000, 50000), (3, 1000, 70000)),
            supports_bonus_points=False,
            description=description,
        )
        connection.commit()

    _alembic(db_path, "upgrade", TARGET_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tournament_types WHERE code = 'satellite_v2'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'satellite_v2'"
        ).fetchone() == (type_id,)


def test_format_migration_rejects_conflicting_satellite_before_template_repoint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "conflicting-satellite.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        satellite_id = _seed_old_satellite_template(connection)
        _insert_target(
            connection,
            code="satellite_v2",
            name="Wrong Satellite",
            calendar_code="S2",
            entry_fee=1000,
            entry_stack=30000,
            addon_fee=1000,
            addon_stack=125000,
            rebuys=((1, 1000, 40000), (2, 1000, 50000), (3, 1000, 70000)),
            supports_bonus_points=False,
        )
        connection.commit()

    failed = _alembic(db_path, "upgrade", TARGET_REVISION, check=False)
    assert failed.returncode != 0
    assert "Conflicting or incomplete tournament type configuration: satellite_v2" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT tournament_type_id FROM weekly_tournament_templates WHERE is_active = 1"
        ).fetchone() == (satellite_id,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PREVIOUS_REVISION,
        )


def test_format_migration_rejects_incomplete_preexisting_config(tmp_path: Path) -> None:
    db_path = tmp_path / "incomplete.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO tournament_types (
                code, name, short_name, calendar_code, is_creatable,
                created_at, updated_at
            ) VALUES ('satellite_v2', 'Satellite', 'Satellite', 'S2', 1,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()

    failed = _alembic(db_path, "upgrade", TARGET_REVISION, check=False)
    assert failed.returncode != 0
    assert "Conflicting or incomplete tournament type configuration: satellite_v2" in failed.stderr


def test_format_migration_rejects_conflicting_mystery_quest(tmp_path: Path) -> None:
    db_path = tmp_path / "conflicting-mystery-quest.db"
    _alembic(db_path, "upgrade", PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        satellite_id = _seed_old_satellite_template(connection)
        _insert_target(
            connection,
            code="mystery_quest",
            name="Mystery Quest",
            calendar_code="WRONG",
            entry_fee=800,
            entry_stack=20000,
            addon_fee=800,
            addon_stack=125000,
            rebuys=(
                (1, 800, 30000),
                (2, 800, 50000),
                (3, 800, 60000),
                (4, 1000, 80000),
                (5, 1000, 80000),
            ),
            supports_bonus_points=True,
        )
        connection.commit()

    failed = _alembic(db_path, "upgrade", TARGET_REVISION, check=False)
    assert failed.returncode != 0
    assert "Conflicting or incomplete tournament type configuration: mystery_quest" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT tournament_type_id FROM weekly_tournament_templates WHERE is_active = 1"
        ).fetchone() == (satellite_id,)


def test_format_migration_downgrade_refuses_referenced_new_type(tmp_path: Path) -> None:
    db_path = tmp_path / "referenced.db"
    _alembic(db_path, "upgrade", TARGET_REVISION)
    with sqlite3.connect(db_path) as connection:
        type_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'satellite_v2'"
        ).fetchone()[0]
        season_id = connection.execute("SELECT id FROM seasons ORDER BY id LIMIT 1").fetchone()[0]
        scoring_id = connection.execute(
            "SELECT id FROM scoring_configs ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO tournaments (
                season_id, date, tournament_fund, status, created_at, updated_at,
                tournament_type_id, registration_open, scoring_config_id
            ) VALUES (?, '2026-10-01', NULL, 'active', CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP, ?, 0, ?)
            """,
            (season_id, type_id, scoring_id),
        )
        tournament_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit()

    failed = _alembic(db_path, "downgrade", PREVIOUS_REVISION, check=False)
    assert failed.returncode != 0
    assert "Cannot downgrade: tournaments reference satellite_v2" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            TARGET_REVISION,
        )
        assert connection.execute(
            "SELECT tournament_type_id FROM tournaments WHERE id = ?", (tournament_id,)
        ).fetchone() == (type_id,)
        assert connection.execute(
            "SELECT code FROM tournament_types WHERE id = ?", (type_id,)
        ).fetchone() == ("satellite_v2",)
