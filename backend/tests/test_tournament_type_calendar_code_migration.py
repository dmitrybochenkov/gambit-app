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
    "classic_v3": ("Classic", "C3"),
    "freezeout": ("Freezeout", "F"),
    "freezeout_v2": ("Freezeout", "F2"),
    "deep_stack": ("Deep Stack", "D"),
    "deep_stack_v2": ("Deep Stack", "D2"),
    "double_double": ("Double", "DD"),
    "mystery_bounty": ("Mystery", "MB"),
    "boss_bounty": ("Boss", "BB"),
    "white_party": ("White Party", "WP"),
    "main_ko": ("MAIN KO", "MK"),
    "legacy_unknown": ("Турнир", "?"),
}


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
        assert short_names[code] == short_name
