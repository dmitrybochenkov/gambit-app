# Gambit App

Telegram bot and future web app for Gambit poker club.

## Project Structure

```text
gambit-app/
├── backend/   Python application, migrations, and tests
├── data/      SQLite database and runtime data
├── docs/      Product and architecture documentation
├── logs/      Runtime logs
├── scripts/   Operational scripts
├── site/      Public website
└── webapp/    Admin and user web application
```

## Stack

- Python 3.12
- aiogram 3
- FastAPI
- SQLAlchemy 2 with async SQLite
- Alembic

## Local Setup

```bash
cp .env.example .env
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The backend reads both `backend/.env` and the root `../.env`; the root file is the
standard location.

The API health check is available at `http://127.0.0.1:8100/health`.
Telegram sends updates to `POST /webhooks/tg`. The `/start` command currently
answers `Работает`.

The local SQLite database is stored in `data/gambit.db` by default. Database
files, logs, build artifacts, caches, and the real `.env` are ignored by Git.

## Quality Checks

```bash
cd backend
uv run ruff check .
uv run pytest
uv run alembic check
```

## Database

The initial migration creates:

- players
- scoring configs
- seasons
- tournaments
- tournament registrations
- tournament results

It also inserts the initial scoring configuration with place coefficients
`0.45`, `0.25`, `0.15`, `0.10`, `0.05`, knockout value `15`, and boss knockout
value `60`.

## Server Layout

The production project root is `/opt/apps/gambit`:

```text
/opt/apps/gambit/
├── .env
├── backend/
├── data/
│   └── gambit.db
├── logs/
├── scripts/
├── site/
└── webapp/
```

The backend service must run with:

```ini
EnvironmentFile=/opt/apps/gambit/.env
WorkingDirectory=/opt/apps/gambit/backend
ExecStart=/opt/apps/gambit/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Set `PUBLIC_BASE_URL`, `TELEGRAM_BOT_TOKEN`, and a random
`TELEGRAM_WEBHOOK_SECRET` in `/opt/apps/gambit/.env`. On application startup,
the bot registers `${PUBLIC_BASE_URL}/webhooks/tg` with Telegram.

With the default `DATA_DIR=../data`, the database resolves to
`/opt/apps/gambit/data/gambit.db`. The root environment file is loaded from
`/opt/apps/gambit/.env`.

Apply migrations from the backend directory:

```bash
cd /opt/apps/gambit/backend
uv sync --frozen
uv run alembic upgrade head
```

## Product Docs

- `docs/product-brief.md`
- `docs/bot-flows.md`
- `docs/domain-model.md`
- `docs/admin-concept.md`
- `docs/implementation-plan.md`
