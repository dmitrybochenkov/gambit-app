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

## Runtime Configuration

The backend reads `.env` from `backend/.env` and `../.env`; the root `.env` is
the standard local and deployment location.

Relevant database/runtime environment values:

- `DATABASE_URL`: optional explicit async SQLAlchemy URL. Empty value uses
  `data/gambit.db`.
- `CLUB_TIMEZONE`: club timezone, default `Europe/Moscow`.
- `TOURNAMENT_DAY_START_HOUR`: hour when the tournament business day changes,
  default `11`.
- `REWARD_REMINDER_RUN_HOUR`: daily reward-reminder scheduler hour, default
  `12`.
- `TELEGRAM_CLUB_CHAT_ID`: Telegram group destination for public posts.
- `TELEGRAM_CLUB_CHANNEL_ID`: Telegram channel destination for public posts.

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
| `d9e0f1a2b3c4` | Remove persisted season status | Yes | No | No | Season lifecycle became date-driven. |
| `b4c5d6e7f8a9` | Rebuild `TournamentResult` as check-in/result row | Yes | No | No | Migrates old participant/draft data into result rows. |
| `c5d6e7f8a9b0` | Remove result submission/admin-created review tables | Yes | Yes | No | Removed obsolete result submission flow. |
| `d6e7f8a9b0c1` | Simplify tournament registrations | Yes | Yes | No | Leaves create/delete registration model. |
| `e7f8a9b0c1d2` | Rename points pool to tournament fund | Yes | No | No | Establishes `tournament_fund` terminology. |
| `f8a9b0c1d2e3` | Reset pre-production game data | No | Yes | No | Intentional during pre-production; historical data restored from spreadsheets. |
| `f9a0b1c2d3e4` | Strict tournament schema | No | Yes | No | Adds strict fund/place/source/bonus constraints after reset. |
| `e4f5a6b7c8d9` | Drop `admin_prompts` | No | Yes | No | Temporary Telegram planning state moved to FSM. |
| `e5f6a7b8c9d0` | Restrict tournaments to ACTIVE/CLOSED | Yes | No | No | Fails fast if legacy `cancelled` tournament rows exist. |
| `e6f7a8b9c0d1` | Allow null fund for closed historical tournaments | Yes | No | No | Live close still requires a valid fund; imported legacy history may keep it `NULL`. |
| `e8f9a0b1c2d3` | Allow duplicate historical result places | Yes | No | No | Removes DB uniqueness on `(tournament_id, place)`; live service still blocks duplicate places. |
| `e9f0a1b2c3d4` | Add season statistics visibility | Yes | No | No | Adds `seasons.is_statistics_visible`. |
| `f0a1b2c3d4e5` | Add tournament photos | Yes | No | No | Adds photo storage and per-tournament unique Telegram file guard. |
| `f1a2b3c4d5e6` | Add Hall of Fame photo slots | Yes | No | No | Adds optional champion/knockout photo file columns. |
| `f2a3b4c5d6e7` | Add tournament type short names | Yes | No | No | Backfills `tournament_types.short_name`. |
| `f3a4b5c6d7e8` | Add combinations and publications | Yes | No | No | Adds public publication idempotency and combinations. |
| `190f0bbcf1e2` | Add tournament combination rank | Yes | No | No | Restricts rank to four-of-a-kind rows. |
| `f4b5c6d7e8f9` | Add player rewards | Yes | No | No | Adds prize-stack bonus rewards. |
| `f5c6d7e8f9a0` | Add reward expiration reminders | Yes | No | No | Adds `expiration_reminder_sent_at`. |
| `f6d7e8f9a0b1` | Enable Mystery Bounty knockouts | Yes | No | Yes | Sets `mystery_bounty` to `knockout_mode = small`. |
| `3b4c5d6e7f8a` | Add user gender | Yes | No | Yes | Adds nullable `users.gender`; existing users remain unknown. |
| `5d6e7f8a9b0c` | Add tournament-bound scoring v2 | Yes | No | Yes | Adds `tournaments.scoring_config_id`, MAIN KO config fields, v2 tournament formats, assigns old tournaments to v1, assigns the 2026-09-02..2026-09-06 tournaments and current season default to v2, and removes `tournament_types.status`. It does not create concrete calendar tournaments or recalculate result points. |

Pre-production destructive resets were intentional for the current development
stage. They are not a permanent production rule: future destructive migrations
must be reviewed independently and backed up.

## Current Domain Tables

- `users`: identity, roles, statuses, Telegram binding.
- `registration_requests`: pending/approved/rejected user registration review.
- `scoring_configs`: versioned scoring coefficients and knockout point values.
- `seasons`: date ranges, scoring config, statistics visibility.
- `season_hall_of_fame`: manual season champion/knockout leader and photos.
- `tournament_types`: tournament names, short names, descriptions, creatability.
- `tournament_type_rules`: scoring capabilities, KO mode, bonus support.
- `tournament_economy_configs`: buy-in/addon/stacks by tournament type.
- `tournament_rebuy_configs`: rebuy rows by tournament type.
- `weekly_tournament_templates`: default weekly planning rows.
- `tournaments`: created tournament facts, unique date, active/closed status.
- `tournament_registrations`: user intent to play.
- `tournament_results`: check-in/result rows and authoritative saved points.
- `tournament_photos`: Telegram photos for close/publication.
- `tournament_combinations`: evening combinations.
- `tournament_publications`: idempotency records for public posts.
- `player_rewards`: prize-stack bonuses and redemption/reminder state.

Removed runtime tables include `players`, `admin_prompts`,
`tournament_participants`, `tournament_result_drafts`,
`result_submissions`, and admin result review tables.

## Important Constraints

- `users.telegram_id` is unique when present.
- `users.display_name_normalized` is not unique.
- `users.gender` is nullable and restricted to `male` or `female` when set.
- `seasons.name` is unique.
- `uq_seasons_open_ended` allows at most one open-ended season.
- `tournaments.date` is unique through `uq_tournaments_date`.
- `tournaments.scoring_config_id` stores the scoring config fixed for that
  tournament.
- `tournaments.status` is restricted to `active` and `closed`.
- `tournament_fund` may be `NULL`; when set, it must be positive and divisible
  by `10`.
- Place coefficients are independent per-place multipliers of
  `tournament_fund`; they are not a 100% prize-pool distribution and are not
  required to sum to `1`.
- `tournament_results` has unique `(tournament_id, player_id)`.
- `tournament_results.place` may duplicate across players at DB level.
- `tournament_registrations` has unique `(tournament_id, player_id)`.
- `tournament_photos` has unique `(tournament_id, telegram_file_unique_id)`.
- `tournament_publications` has unique
  `(publication_type, destination_type, destination_chat_id, content_hash)`.
- `player_rewards` has unique
  `(source_tournament_id, player_id, reward_type)`.
- `player_rewards` has unique `(player_id, redeemed_tournament_day)` for the
  one-reward-per-business-day rule.

## Import-Specific Schema Notes

Historical closed tournaments may have `tournament_fund = NULL`. This is not a
license for live close workflows to omit the fund: `ResultService` still
requires and records a valid fund when closing a live tournament.

Historical result rows preserve authoritative imported points. The importer
must not reconstruct tournament funds or recalculate old result points.

Scoring v2 one-off operational changes are intentionally outside Alembic:

- `scripts/create_september_2026_tournaments.py` previews/applies the concrete
  2026-09-09..2026-09-13 week.
- `scripts/recalculate_september_2026_points.py` previews/applies
  `tournament_points` recalculation for 2026-09-02..2026-09-06 using the
  runtime scoring logic.

Both scripts default to dry-run and require explicit `--apply` to write.
