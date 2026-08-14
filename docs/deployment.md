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

```bash
cd /opt/apps/gambit

git status
git pull --ff-only origin main

cd backend
uv sync
uv run alembic upgrade head
uv run alembic current

sudo systemctl restart gambit
sudo systemctl status gambit --no-pager
sudo journalctl -u gambit -n 100 --no-pager -o cat
curl --fail --silent http://127.0.0.1:8100/health
```

When `PUBLIC_BASE_URL` is set, webhook deployment requires
`TELEGRAM_WEBHOOK_SECRET`. Startup fails without it, and webhook updates without
the matching `X-Telegram-Bot-Api-Secret-Token` header are rejected.

Optional Telegram publication destinations can be configured in the environment:

```env
TELEGRAM_CLUB_CHAT_ID=
TELEGRAM_CLUB_CHANNEL_ID=
```

Empty values mean that the destination is not configured. These settings only
prepare the runtime configuration; schedule/result publication flows are wired
separately.

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

Backup example:

```bash
mkdir -p /opt/apps/gambit/data/backups
cp /opt/apps/gambit/data/gambit.db \
  /opt/apps/gambit/data/backups/gambit-before-deploy-$(date +%Y%m%d-%H%M%S).db
sha256sum /opt/apps/gambit/data/backups/gambit-before-deploy-*.db | tail -n 1
```

Rollback for an application/database migration failure is restore the previous
application directory/commit and copy the database backup back into place.
Do not assume `alembic downgrade` is available for irreversible migrations.
