import os
import sqlite3
import subprocess
import sys
from pathlib import Path

EXPECTED_CODES = {
    "bounty": ("Bounty", "B"),
    "bounty_v2": ("Bounty", "B2"),
    "bounty_v3": ("Bounty", "B3"),
    "classic": ("Classic", "C"),
    "classic_v2": ("Classic", "C2"),
    "classic_v3": ("Freeroll", "FR"),
    "freezeout": ("Freezeout", "F"),
    "freezeout_v2": ("Freezeout", "F2"),
    "deep_stack": ("Deep Stack", "D"),
    "deep_stack_v2": ("Deep Stack", "D2"),
    "double_double": ("Double", "DD"),
    "mystery_bounty": ("Mystery", "MB"),
    "boss_bounty": ("Boss", "BB"),
    "white_party": ("White Party", "WP"),
    "main_ko": ("MAIN KO", "MK"),
    "slow_blinds": ("Slow Blinds", "SB"),
    "satellite": ("Satellite", "ST"),
    "black_party": ("Black Party", "BP"),
    "month_main": ("Month Main Tournament", "MM"),
    "legacy_unknown": ("Турнир", "?"),
}

PRE_MONTH_MAIN_REVISION = "8a9b0c1d2e3f"


def _month_main_alembic(
    db_path: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _insert_existing_tournament(connection: sqlite3.Connection, type_id: int) -> None:
    connection.execute(
        """
        INSERT INTO tournaments (
            id, season_id, date, tournament_fund, status, created_at, updated_at,
            tournament_type_id, registration_open, scoring_config_id
        ) VALUES (901, 3, '2026-09-25', NULL, 'active', CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP, ?, 0, 2)
        """,
        (type_id,),
    )


def test_tournament_type_calendar_code_migration_upgrade_and_downgrade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "calendar-code.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT code, short_name, calendar_code
            FROM tournament_types
            ORDER BY code
            """
        ).fetchall()

    assert {code: (short_name, calendar_code) for code, short_name, calendar_code in rows} == {
        code: expected for code, expected in sorted(EXPECTED_CODES.items())
    }

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "5d6e7f8a9b0c"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tournament_types)").fetchall()
        }
        short_names = dict(
            connection.execute("SELECT code, short_name FROM tournament_types").fetchall()
        )

    assert "calendar_code" not in columns
    for code, (short_name, _calendar_code) in EXPECTED_CODES.items():
        if code in {"classic_v3", "slow_blinds", "satellite", "black_party", "month_main"}:
            continue
        assert short_names[code] == short_name
    assert short_names["classic_v3"] == "Classic"


def test_month_main_migration_preserves_populated_existing_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "month-main.db"
    _month_main_alembic(db_path, "upgrade", PRE_MONTH_MAIN_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_existing_tournament(connection, 1)
        connection.commit()
        before_types = connection.execute("SELECT * FROM tournament_types ORDER BY id").fetchall()
        before_economy = connection.execute(
            "SELECT * FROM tournament_economy_configs ORDER BY id"
        ).fetchall()
        before_rules = connection.execute(
            "SELECT * FROM tournament_type_rules ORDER BY id"
        ).fetchall()
        before_rebuys = connection.execute(
            "SELECT * FROM tournament_rebuy_configs ORDER BY id"
        ).fetchall()
        before_tournaments = connection.execute("SELECT * FROM tournaments ORDER BY id").fetchall()

    _month_main_alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        after_types = connection.execute("SELECT * FROM tournament_types ORDER BY id").fetchall()
        code_index = next(
            index
            for index, column in enumerate(
                connection.execute("PRAGMA table_info(tournament_types)")
            )
            if column[1] == "code"
        )
        month_main_id = next(row[0] for row in after_types if row[code_index] == "month_main")
        assert [row for row in after_types if row[code_index] != "month_main"] == before_types
        assert (
            connection.execute(
                "SELECT * FROM tournament_economy_configs "
                "WHERE tournament_type_id != ? ORDER BY id",
                (month_main_id,),
            ).fetchall()
            == before_economy
        )
        assert (
            connection.execute(
                "SELECT * FROM tournament_type_rules WHERE tournament_type_id != ? ORDER BY id",
                (month_main_id,),
            ).fetchall()
            == before_rules
        )
        assert (
            connection.execute(
                "SELECT * FROM tournament_rebuy_configs WHERE tournament_type_id != ? ORDER BY id",
                (month_main_id,),
            ).fetchall()
            == before_rebuys
        )
        assert (
            connection.execute("SELECT * FROM tournaments ORDER BY id").fetchall()
            == before_tournaments
        )
        row = connection.execute(
            """SELECT id, name, short_name, calendar_code, is_creatable
               FROM tournament_types WHERE code = 'month_main'"""
        ).fetchone()
        assert row is not None
        type_id = row[0]
        assert row[1:] == ("Month Main Tournament", "Month Main Tournament", "MM", 1)
        assert connection.execute(
            """SELECT entry_fee, entry_stack, addon_fee, addon_stack
               FROM tournament_economy_configs WHERE tournament_type_id = ?""",
            (type_id,),
        ).fetchone() == (1000, 30000, 1000, 125000)
        assert connection.execute(
            """SELECT rebuy_order, fee, stack FROM tournament_rebuy_configs
               WHERE tournament_type_id = ? ORDER BY rebuy_order""",
            (type_id,),
        ).fetchall() == [(1, 1000, 40000), (2, 1000, 50000), (3, 1000, 60000)]
        assert connection.execute(
            """SELECT points_multiplier, prize_place_multiplier,
                      prize_place_multiplier_places, knockout_mode, supports_bonus_points
               FROM tournament_type_rules WHERE tournament_type_id = ?""",
            (type_id,),
        ).fetchone() == (1, 1, None, "none", 0)
        connection.execute("DELETE FROM tournaments WHERE id = 901")
        connection.commit()

    _month_main_alembic(db_path, "downgrade", PRE_MONTH_MAIN_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM tournament_types WHERE code = 'month_main'"
            ).fetchone()[0]
            == 0
        )


def test_month_main_downgrade_refuses_referenced_type(tmp_path: Path) -> None:
    db_path = tmp_path / "referenced-month-main.db"
    _month_main_alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        type_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'month_main'"
        ).fetchone()[0]
        _insert_existing_tournament(connection, type_id)
        connection.commit()

    failed = _month_main_alembic(db_path, "downgrade", PRE_MONTH_MAIN_REVISION, check=False)
    assert failed.returncode != 0
    assert "Cannot downgrade: tournaments reference month_main" in failed.stderr
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "9b0c1d2e3f4a"
        )
        assert connection.execute(
            "SELECT tournament_type_id FROM tournaments WHERE id = 901"
        ).fetchone() == (type_id,)
        assert connection.execute(
            "SELECT code FROM tournament_types WHERE id = ?", (type_id,)
        ).fetchone() == ("month_main",)


def test_month_main_migration_skips_preexisting_type_without_overwriting(tmp_path: Path) -> None:
    db_path = tmp_path / "preexisting-month-main.db"
    _month_main_alembic(db_path, "upgrade", PRE_MONTH_MAIN_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO tournament_types
               (code, name, short_name, calendar_code, description, is_creatable,
                created_at, updated_at)
               VALUES ('month_main', 'Existing Month Main', 'Existing', 'XM',
                       'Keep this row', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        type_id = connection.execute(
            "SELECT id FROM tournament_types WHERE code = 'month_main'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO tournament_economy_configs
               (tournament_type_id, entry_fee, entry_stack, addon_fee, addon_stack,
                created_at, updated_at)
               VALUES (?, 123, 456, 789, 1000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (type_id,),
        )
        connection.commit()
        before_type = connection.execute(
            "SELECT * FROM tournament_types WHERE id = ?", (type_id,)
        ).fetchone()
        before_economy = connection.execute(
            "SELECT * FROM tournament_economy_configs WHERE tournament_type_id = ?", (type_id,)
        ).fetchone()

    _month_main_alembic(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tournament_types WHERE code = 'month_main'"
        ).fetchone() == (1,)
        assert (
            connection.execute("SELECT * FROM tournament_types WHERE id = ?", (type_id,)).fetchone()
            == before_type
        )
        assert (
            connection.execute(
                "SELECT * FROM tournament_economy_configs WHERE tournament_type_id = ?", (type_id,)
            ).fetchone()
            == before_economy
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM tournament_type_rules WHERE tournament_type_id = ?", (type_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM tournament_rebuy_configs WHERE tournament_type_id = ?", (type_id,)
        ).fetchone() == (0,)
