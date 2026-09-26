# Deployment

Production project path:

```text
/opt/apps/gambit
```

Python executable:

```text
/opt/apps/gambit/backend/.venv/bin/python
```

Database:

```text
/opt/apps/gambit/data/gambit.db
```

## Standard Deploy

The deployment invariant is that application code requiring a new schema must
not serve traffic before the required migrations complete successfully. The
manual procedure below uses `stop -> update -> migrate -> start` as the current
conservative fail-safe implementation of that invariant. It is not a permanent
architectural requirement for every future deployment: automation may preserve
availability with a different ordering when compatibility and migration safety
have been established.

The preferred operator workflow starts from the local Gambit repository and
uses the thin SSH wrapper:

```bash
# from the local Gambit repository
scripts/deploy.sh
```

The wrapper connects through the existing `dimension-x` SSH host alias and
runs the authoritative server-side entrypoint. It allocates a PTY only so
remote `sudo` can prompt when required; it does not open a persistent
interactive shell, contain credentials, or duplicate deployment steps. Remote
output and exit status are forwarded to the local terminal.

Direct server-side fallback:

```bash
ssh dimension-x
cd /opt/apps/gambit
scripts/deploy-production.sh
```

`scripts/deploy-production.sh` remains the authoritative deployment mechanism.
It validates the checkout and production branch, performs a fast-forward-only
update, creates a consistent SQLite backup, stops `gambit.service`, synchronizes
dependencies, migrates to the single Alembic head, starts the service, and
performs bounded service/health/revision checks.

Failures before the stop phase leave the running service untouched. Dependency
or migration failures after stop leave it stopped. A `systemctl start` failure
means the service was not successfully started. Health or post-start revision
verification failures occur after a start attempt; the script reports failure
and diagnostics but does not automatically stop or roll back the service. The
script never runs an automatic Alembic downgrade, database restore, git
rollback, hard reset, or clean operation.

Backups are created with SQLite's online `.backup` mechanism under
`/opt/apps/gambit/data/backups` and named
`gambit-before-deploy-<UTC timestamp>-<commit>.db`. Existing backups are never
overwritten or pruned automatically.

### Manual Recovery Reference

For diagnosis or a deliberately supervised recovery, the equivalent critical
sequence is:

```bash
cd /opt/apps/gambit
git fetch origin main
git merge --ff-only origin/main
sqlite3 data/gambit.db ".backup 'data/backups/gambit-manual-backup.db'"
sudo systemctl stop gambit
cd backend
uv sync
uv run alembic upgrade head
uv run alembic current
sudo systemctl start gambit
sudo systemctl is-active --quiet gambit
curl --fail --silent http://127.0.0.1:8100/health
```

If migration or startup fails, keep the service stopped and investigate. Restore
the database backup and application revision only as an explicit operator
decision after identifying which steps completed.

When `PUBLIC_BASE_URL` is set, webhook deployment requires
`TELEGRAM_WEBHOOK_SECRET`. Startup fails without it, and webhook updates without
the matching `X-Telegram-Bot-Api-Secret-Token` header are rejected.

Optional Telegram publication destinations can be configured in the environment:

```env
CLUB_TIMEZONE=Europe/Moscow
TOURNAMENT_DAY_START_HOUR=11
REWARD_REMINDER_RUN_HOUR=12
TELEGRAM_CLUB_CHAT_ID=
TELEGRAM_CLUB_CHANNEL_ID=
TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

Empty values mean that the destination is not configured. These settings only
prepare the runtime configuration; schedule/result publication flows send only
to configured destinations.

## WebApp API

The Telegram WebApp player endpoints are:

```text
GET /api/v1/me
GET /api/v1/tournaments/week
GET /api/v1/tournaments/{tournament_id}
GET /api/v1/me/registrations
POST /api/v1/tournaments/{tournament_id}/registration
DELETE /api/v1/tournaments/{tournament_id}/registration
GET /api/v1/ratings
GET /api/v1/ratings/knockouts
GET /api/v1/me/profile
GET /api/v1/me/history
GET /api/v1/me/history/{tournament_id}
GET /api/v1/hall-of-fame
GET /api/v1/me/rewards
```

It requires signed Telegram Mini App initData in one header:

```http
Authorization: tma <raw Telegram WebApp initData>
```

The backend verifies the initData signature with `TELEGRAM_BOT_TOKEN` and
rejects stale auth data older than `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS`
seconds. The endpoint does not trust Telegram ids, user ids, or roles supplied
in request bodies or query parameters.

Example health-style check for routing only, without real auth:

```bash
curl --fail --silent http://127.0.0.1:8100/api/v1/me
```

Expected result without the Authorization header is a JSON `unauthorized`
error. A real WebApp request must provide fresh Telegram initData from the
Telegram client.

Tournament registration endpoints use the same current club business week and
`registration_open` rules as the Telegram bot. Requests do not include
`user_id`, `telegram_id`, or role; the backend derives the actor only from the
signed Telegram initData.

Read-heavy endpoints return structured semantic data for ratings, profile,
history, Hall of Fame, and current active rewards. Hall of Fame photo file ids
remain Telegram-only storage and are not exposed as WebApp media URLs.

## Fresh DB Bootstrap

After `alembic upgrade head` on a clean database, create the first superadmin
without starting Telegram:

```bash
cd /opt/apps/gambit

/opt/apps/gambit/backend/.venv/bin/python \
  scripts/bootstrap_superadmin.py \
  --db /opt/apps/gambit/data/gambit.db \
  --telegram-id <telegram_id> \
  --display-name "Dima Bochenkov"
```

The command is idempotent for the same Telegram user. It requires an existing
SQLite database with `users` and `alembic_version` tables and does not create a
new database if the path is mistyped.

## Safety Before Migrations

Before applying migrations:

1. Check `git status`.
2. Read new migration files.
3. Decide whether a migration is data-preserving or destructive.
4. Backup production-like data before destructive or uncertain migrations.

Manual backup example:

```bash
mkdir -p /opt/apps/gambit/data/backups
sqlite3 /opt/apps/gambit/data/gambit.db \
  ".backup '/opt/apps/gambit/data/backups/gambit-before-deploy-$(date +%Y%m%d-%H%M%S).db'"
sha256sum /opt/apps/gambit/data/backups/gambit-before-deploy-*.db | tail -n 1
```

Rollback for an application/database migration failure is restore the previous
application directory/commit and copy the database backup back into place.
Do not assume `alembic downgrade` is available for irreversible migrations.
