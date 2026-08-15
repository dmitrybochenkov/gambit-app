# Gambit

Telegram bot and backend for Gambit poker club: player registration, tournament
schedule, check-in, results, ratings, tournament history, and hall of fame.

## Architecture

See [docs/architecture.md](docs/architecture.md).

## Domain Model

See [docs/domain-model.md](docs/domain-model.md).

## Local Development

```bash
cp .env.example .env
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The backend reads `backend/.env` and `../.env`; the root `.env` is the standard
local location. The health check is available at `http://127.0.0.1:8100/health`.
Tournament operations use `TOURNAMENT_DAY_START_HOUR` in the club timezone:
before that hour, check-in/results/close still treat the tournament day as
yesterday.

## Tests

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pytest -q
uv run alembic check
```

More testing notes: [docs/testing.md](docs/testing.md).

## Deployment

See [docs/deployment.md](docs/deployment.md).

## Data Import

See [docs/data-import.md](docs/data-import.md).

## Database / Migrations

See [docs/database.md](docs/database.md).
