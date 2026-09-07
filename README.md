# Gambit

Gambit is a Telegram application and async Python backend for managing a private
poker club.

It supports the operational tournament lifecycle: player registration and
approval, tournament planning and registration, check-in, results, ratings,
player history, rewards, publications, and Hall of Fame management.

The application is used for real club operations and has evolved together with
the club's workflows and historical data.

## Highlights

- Telegram bot built with **aiogram 3**
- Async HTTP API built with **FastAPI**
- Async persistence with **SQLAlchemy 2** and **aiosqlite**
- Schema evolution managed with **Alembic**
- Layered application architecture with explicit service and repository boundaries
- Service-owned transactions and service-level authorization
- Player, admin, and superadmin workflows
- Telegram Mini App authentication with server-side `initData` signature verification
- Tournament planning, registration, check-in, results, ratings, rewards, and history
- Historical data import and migration utilities
- Scheduled reward-expiration reminders
- Telegram webhook deployment with webhook-secret validation
- Automated unit, integration, architecture, API, and Telegram dispatcher tests
- Production-style deployment with systemd, migrations, health checks, logs, and rollback procedures

## Tech Stack

- **Python 3.12**
- **aiogram 3**
- **FastAPI**
- **SQLAlchemy 2**
- **Alembic**
- **SQLite / aiosqlite**
- **Pydantic Settings**
- **Uvicorn**
- **pytest / pytest-asyncio**
- **Ruff**
- **Pyright**
- **uv**

## Architecture

The main application flow follows explicit boundaries:

```text
Telegram handler
    ↓
Service use-case
    ↓
Repository
    ↓
ORM / SQLite
```

The HTTP API uses the same application layer:

```text
HTTP router / dependency
    ↓
Service use-case
    ↓
Repository
    ↓
ORM / SQLite
```

Telegram handlers and HTTP routes are transport adapters. Business rules live
in services and domain modules, while repositories are responsible for
persistence operations.

Public mutation use-cases own their `AsyncSession` and transaction boundary.
Repositories receive an existing session and do not commit independently.

Administrative authorization is enforced inside services through
`AccessPolicy`, rather than relying only on Telegram UI visibility.

Service-to-presentation data is passed through immutable DTOs instead of
exposing ORM models directly.

For a detailed description, see
[docs/architecture.md](docs/architecture.md).

Contributor and development rules are documented in
[docs/development-contract.md](docs/development-contract.md).

## Main Features

### Players

Players can:

- register in the club;
- view the current tournament schedule;
- register for and cancel tournament participation;
- view ratings and knockout ratings;
- view their profile and statistics;
- browse tournament history;
- view active rewards;
- access Hall of Fame information.

### Tournament Operations

Administrative flows cover:

- tournament planning and scheduling;
- player check-in;
- result entry and correction;
- tournament lifecycle management;
- tournament publications;
- scoring and rating updates;
- reward handling;
- season management.

Business-date logic is timezone-aware and supports club sessions that continue
past midnight.

### Roles and Access

The application has player, admin, and superadmin scenarios.

Administrative permissions are checked at the service layer, so authorization
does not depend on which buttons or commands are visible in Telegram.

### Telegram Mini App API

The backend exposes versioned player-facing endpoints under `/api/v1`.

Current API areas include:

- authenticated player bootstrap;
- weekly tournament schedule;
- tournament details;
- tournament registration;
- ratings;
- profile;
- tournament history;
- Hall of Fame;
- rewards.

Telegram Mini App requests use signed Telegram `initData`:

```http
Authorization: tma <raw Telegram WebApp initData>
```

The backend verifies the signature and authentication age server-side and
derives the trusted Telegram identity from the verified data. User IDs, Telegram
IDs, and roles supplied by the frontend are not trusted.

## Reliability and Testing

The project contains automated coverage for business rules and application
boundaries, including:

- service and repository architecture constraints;
- database constraints;
- tournament scheduling and business-day rules;
- registration and check-in flows;
- result processing and corrections;
- scoring and ratings;
- rewards and expiration reminders;
- historical data imports and idempotency;
- Telegram dispatcher and callback scenarios;
- Telegram Mini App authentication and API endpoints;
- migration-sensitive SQLite behavior.

The normal release validation includes linting, formatting, static type checks,
the full pytest suite, Python compilation, and Alembic validation.

```bash
cd backend

uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest -q
uv run python -m compileall app
uv run alembic check
```

More details are available in
[docs/testing.md](docs/testing.md).

## Local Development

Create the local environment file:

```bash
cp .env.example .env
```

Install dependencies and prepare the database:

```bash
cd backend

uv sync --extra dev
uv run alembic upgrade head
```

Start the backend:

```bash
uv run uvicorn app.main:app --reload
```

The health endpoint is available at:

```text
http://127.0.0.1:8100/health
```

The root `.env` is the standard local configuration location. The backend also
supports `backend/.env`.

## Database and Migrations

Gambit currently uses SQLite with asynchronous SQLAlchemy access.

Database schema changes are managed through Alembic. Migration procedures are
designed to account for existing production-like data rather than assuming an
empty database.

See [docs/database.md](docs/database.md) for details.

## Historical Data

The repository contains utilities for importing and maintaining historical club
data, including player and rating history.

Import workflows support validation and operational safeguards such as dry-run
and idempotency where applicable.

See [docs/data-import.md](docs/data-import.md).

## Deployment

The application is designed to run as a long-lived Linux service.

The deployment workflow includes:

- fast-forward Git updates;
- dependency synchronization;
- Alembic migrations;
- systemd service restart;
- journal log inspection;
- HTTP health checks;
- database backup before potentially destructive migrations;
- explicit rollback procedures.

Telegram updates are delivered through the FastAPI webhook endpoint:

```text
POST /webhooks/tg
```

When public webhook deployment is enabled, startup requires a configured
Telegram webhook secret and incoming updates are validated against it.

See [docs/deployment.md](docs/deployment.md).

## Documentation

Additional project documentation:

- [Architecture](docs/architecture.md)
- [Domain model](docs/domain-model.md)
- [Bot flows](docs/bot-flows.md)
- [Admin concept](docs/admin-concept.md)
- [Database and migrations](docs/database.md)
- [Data import](docs/data-import.md)
- [Testing](docs/testing.md)
- [Deployment](docs/deployment.md)
- [Development contract](docs/development-contract.md)