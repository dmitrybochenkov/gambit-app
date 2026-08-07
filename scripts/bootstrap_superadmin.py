#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.common.normalization import normalize_display_name  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "gambit.db"


class BootstrapError(ValueError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the first Gambit SUPERADMIN.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Existing SQLite DB path")
    parser.add_argument("--telegram-id", type=int, required=True, help="Telegram user ID")
    parser.add_argument("--display-name", required=True, help="SUPERADMIN display name")
    args = parser.parse_args()

    try:
        result = bootstrap_superadmin(
            db_path=args.db,
            telegram_id=args.telegram_id,
            display_name=args.display_name,
        )
    except BootstrapError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Database: {args.db.expanduser().resolve()}")
    print(result)


def bootstrap_superadmin(db_path: Path, telegram_id: int, display_name: str) -> str:
    if telegram_id <= 0:
        raise BootstrapError("telegram_id must be a positive integer")
    normalized = normalize_display_name(display_name)
    if normalized is None:
        raise BootstrapError("display_name must not be empty")

    resolved_db = db_path.expanduser().resolve()
    if not resolved_db.exists():
        raise BootstrapError(f"Database does not exist: {resolved_db}")

    connection = sqlite3.connect(resolved_db)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        _require_table(connection, "users")
        _require_table(connection, "alembic_version")
        with connection:
            existing = connection.execute(
                """
                SELECT id, display_name, display_name_normalized, telegram_id, role, status
                FROM users
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO users (
                        display_name, display_name_normalized, telegram_id, role, status,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'superadmin', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (display_name.strip(), normalized, telegram_id),
                )
                return "Created ACTIVE SUPERADMIN."

            updates = {
                "display_name": display_name.strip(),
                "display_name_normalized": normalized,
                "role": "superadmin",
                "status": "active",
            }
            if all(existing[field] == value for field, value in updates.items()):
                return "SUPERADMIN already exists; no changes."

            connection.execute(
                """
                UPDATE users
                SET display_name = ?,
                    display_name_normalized = ?,
                    role = 'superadmin',
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (updates["display_name"], updates["display_name_normalized"], existing["id"]),
            )
            return "Existing Telegram user promoted to ACTIVE SUPERADMIN."
    finally:
        connection.close()


def _require_table(connection: sqlite3.Connection, table_name: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if row is None:
        raise BootstrapError(f"Required table is missing: {table_name}")


if __name__ == "__main__":
    main()
