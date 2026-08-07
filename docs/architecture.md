# Architecture

## Layers

```text
Telegram handler
-> Service use-case
-> Repository
-> ORM / SQLite
```

## Responsibilities

### Telegram Handler

- Reads Telegram updates.
- Calls one service use-case.
- Maps expected domain errors to Telegram messages.
- Uses formatter and scenario keyboard modules.
- Does not run SQLAlchemy queries or make business decisions.

### Service

- Owns public use-cases.
- Opens the `AsyncSession` and transaction boundary.
- Calls `AccessPolicy` for administrative authorization.
- Applies domain rules.
- Commits or rolls back mutations.

### Repository

- Receives an existing `AsyncSession`.
- Performs SQLAlchemy query and persistence operations.
- Does not open sessions.
- Does not call services.
- Does not commit or encode business policy.

### Domain

Pure rules, enums, value-object codecs, and policy helpers live under
`backend/app/domain` and small service-adjacent policy modules.

### DTO

DTOs in `backend/app/services/dto.py` are immutable service-to-presentation
contracts. Presentation code should format DTOs, not ORM models.

## Transactions

One public mutation use-case owns one `AsyncSession` and one transaction.
Repositories used inside that use-case share the same session.

## Authorization

Every public administrative service use-case checks the actor inside the
service through `AccessPolicy`. Telegram handlers may hide buttons for UX, but
service-level authorization is authoritative.

## Clock

Business-date operations use `Clock`, `ClubClock`, or `FixedClock`. Code should
not call `date.today()` directly for domain decisions.

## Services

Current service classes include:

- `UserService`
- `TournamentService`
- `TournamentCheckInService`
- `ResultService`
- `RatingService`
- `ProfileService`
- `UserStatisticsService`
- `CalendarService`
- `SeasonService`
- `AdminPromptService`

This list documents the current tree, not a future split plan.

## Repository Pattern

Architecture tests enforce that services do not use direct SQLAlchemy query
APIs such as `select`, `insert`, `update`, `delete`, `session.execute`,
`scalar`, or `scalars`. Session lifecycle methods such as `flush`, `commit`,
and `rollback` are allowed in services because services own transactions.

Repositories:

- accept `AsyncSession`;
- never create a session;
- never commit;
- never call services.

## Telegram Presentation

Presentation modules are organized by role and scenario:

```text
backend/app/bot/telegram/
  handlers/
    user/
    admin/
    superadmin/
  keyboards/
    user/
    admin/
    superadmin/
  texts/
  formatters/
```

Handler packages expose facade routers only. Scenario handlers import concrete
keyboard modules such as `keyboards.admin.results`, not the old flat keyboard
facade. Shared handler helper modules must stay small and must not become
dependency aggregators.

## Runtime Error Model

- aiogram dispatches Telegram updates through FastAPI webhook endpoint
  `POST /webhooks/tg`.
- Expected domain errors are handled near the scenario and mapped to Telegram
  text.
- Unexpected errors are logged by the Telegram error boundary and receive a
  safe fallback.
- Stale callbacks must not repeat mutations; services validate prompt/result
  lifecycle before applying changes.
