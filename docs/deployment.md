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
