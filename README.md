# Gambit App

Telegram bot and future web app for Gambit poker club.

## Stack

- Python 3.12
- aiogram 3
- FastAPI
- SQLAlchemy 2 with async SQLite
- Alembic

## Local Setup

```bash
uv sync --extra dev
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

The API health check is available at `http://127.0.0.1:8000/health`.

The local SQLite database is stored in `gambit.db` by default. Database files and
the real `.env` are ignored by Git.

## Quality Checks

```bash
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

## Product Docs

- `docs/product-brief.md`
- `docs/bot-flows.md`
- `docs/domain-model.md`
- `docs/admin-concept.md`
- `docs/implementation-plan.md`
