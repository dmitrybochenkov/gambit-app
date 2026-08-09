# Database

## Engine

The project uses SQLite through SQLAlchemy 2 async ORM. Alembic migrations and
ORM metadata together define the authoritative schema.

## Common Commands

```bash
cd backend
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
uv run alembic check
```

SQLite integrity checks:

```bash
sqlite3 ../data/gambit.db "PRAGMA foreign_key_check; PRAGMA integrity_check;"
```

## Migration Rules

- Do not edit production database schema manually.
- Do not use `alembic stamp` instead of `upgrade` without a separate recovery
  procedure.
- Do not rewrite migrations that have already been applied outside local
  development.
- Destructive migrations require an explicit backup and rollback plan.

## Significant Migration History

| Revision | Purpose | Data-preserving | Destructive | Downgrade | Notes |
| --- | --- | --- | --- | --- | --- |
| `e7a9c1d4f2b6` | Replace `players` with `users` | Partly | Yes | No | Player-to-User release rollback is app dir + DB backup. |
| `b4c5d6e7f8a9` | Rebuild `TournamentResult` as check-in/result row | Yes | No | No | Migrates old participant/draft data into result rows. |
| `c5d6e7f8a9b0` | Remove result submission/admin-created review tables | Yes | Yes | No | Removed obsolete result submission flow. |
| `d6e7f8a9b0c1` | Simplify tournament registrations | Yes | Yes | No | Leaves create/delete registration model. |
| `e7f8a9b0c1d2` | Rename points pool to tournament fund | Yes | No | No | Establishes `tournament_fund` terminology. |
| `f8a9b0c1d2e3` | Reset pre-production game data | No | Yes | No | Intentional during pre-production; historical data restored from spreadsheets. |
| `f9a0b1c2d3e4` | Strict tournament schema | No | Yes | No | Adds strict fund/place/source/bonus constraints after reset. |
| `a0b1c2d3e4f5` | Strict `admin_prompts` lifecycle | Yes | No | No | Removes obsolete prompt states and duplicate prompt key index. |
| `b0c1d2e3f4a5` | Cleanup registration schema | Yes | Yes for invalid rows | No | Removes unused registration fields and requires Telegram actor ID. |
| `c0d1e2f3a4b5` | Enforce integer bonus points | Yes | No | No | Strengthens `bonus_points` SQLite check. |
| `e3f4a5b6c7d8` | Add manual Season Hall of Fame | Yes | No | No | Adds `season_hall_of_fame` and marks Mystery Bounty as bonus-only. |
| `e4f5a6b7c8d9` | Drop `admin_prompts` | No | Yes | No | Temporary Telegram planning state moved to FSM; DB keeps only confirmed business state. |

Pre-production destructive resets were intentional for the current development
stage. They are not a permanent production rule: future destructive migrations
must be reviewed independently and backed up.
