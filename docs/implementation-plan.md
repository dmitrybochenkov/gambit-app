# Implementation Plan

## Suggested Stack

Recommended if we want to stay close to the neighboring `poker-app` project:

- Backend: Python 3.12
- Bot framework: aiogram 3
- API/admin backend: FastAPI, when needed
- Database: SQLite for MVP
- ORM: SQLAlchemy 2
- Migrations: Alembic
- Config: pydantic-settings and `.env`
- Admin web app later: Vue 3 + Vite, matching the neighboring webapp

Why this fits:

- The expected bot database is small: about 100-150 members.
- Tournament and rating data volume is also low.
- SQLite is enough for this scale if the bot is the main writer.
- The project can later move to PostgreSQL without changing the domain model if SQLAlchemy and Alembic are used cleanly.

Alternative stack:

- TypeScript + grammY, matching the neighboring `poker-bot-v3` project.
- This is also viable, but the current nearby Python app already has database, migration, bot, and API patterns.

## Database Choice

SQLite is sufficient for the MVP if:

- There are 100-150 players.
- Admins are few.
- Tournament results are entered manually.
- There are no heavy concurrent writes.
- The app runs as one bot process, or writes are coordinated through one backend process.

Use PostgreSQL from day one only if:

- Multiple services will write to the database at the same time.
- A public web app and admin panel must launch immediately.
- Hosting already provides managed PostgreSQL and backups.
- We expect large imports, analytics, or high write concurrency soon.

Recommended path:

1. Start with SQLite.
2. Use SQLAlchemy models and Alembic migrations.
3. Avoid SQLite-specific shortcuts in application code.
4. Keep database access behind repository/service functions.
5. Move to PostgreSQL later only when there is a real operational reason.

## Milestone 1: Product And Data Foundation

- Confirm registration rules.
- Confirm rating formulas.
- Confirm tournament lifecycle.
- Confirm admin workflow.
- Define database schema.
- Define bot command and callback structure.

## Milestone 2: Bot MVP

- Telegram bot bootstrap.
- User onboarding state machine.
- Registration validation.
- Admin approval flow.
- Main keyboard.
- Tournament schedule.
- Tournament self-registration.
- Registration cancellation.
- Profile display.
- Rating display.

## Milestone 3: Admin MVP

- Pending registration list.
- Approve and reject users.
- Tournament CRUD.
- Registration list per tournament.
- Result entry.
- Rating recalculation.

## Milestone 4: Hardening

- Logging.
- Error handling.
- Admin audit trail.
- Backups.
- Rate limits.
- Basic tests.
- Deployment setup.

## Milestone 5: Web App

- Player-facing web app or Telegram Web App.
- Web admin panel.
- Better dashboards and analytics.

## Immediate Next Steps

1. Choose backend stack.
2. Confirm the rating formula and season definition.
3. Decide MVP admin surface: Telegram admin flows or web admin from day one.
4. Create database schema.
5. Scaffold the bot application.
