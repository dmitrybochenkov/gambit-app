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

DTOs under `backend/app/services/dto/` are immutable service-to-presentation
contracts. Presentation code should format DTOs, not ORM models.

DTO packages are grouped by domain or scenario. `dto/__init__.py` may expose
modules, but it must not become a flat facade of every DTO symbol.

Persisted domain enums are used directly in service DTOs when the view state is
identical to storage state. Separate `*View` enums are reserved for actual
presentation/use-case state, such as start or lifecycle screens.

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

- `UserAccessService`
- `RegistrationService`
- `RegistrationReviewService`
- `AdminManagementService`
- `TournamentService`
- `TournamentScheduleService`
- `TournamentPlanningService`
- `TournamentCheckInService`
- `ResultService`
- `RatingService`
- `ProfileService`
- `UserStatisticsService`
- `SeasonService`

This list documents the current tree, not a future split plan.

`UserService`, `CalendarService`, and the old `services/dto.py` module are
retired runtime monoliths.

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

Repository projection objects are persistence-layer records. Services map them
explicitly into service DTOs before returning data to Telegram handlers.

## Calendar Drafts

Calendar and season planning use Telegram FSM for unfinished drafts. The
database stores only confirmed business state: seasons, tournaments, templates,
and results. If the bot restarts, unfinished drafts disappear and the
administrator starts the flow again.

Tournament rows are either `active` or `closed`. Cancelled tournaments are
deleted rather than status-tracked. Existing gaming weeks are not checked
against templates for completeness: a week is in progress iff at least one real
tournament row in that week is `active`. The next week becomes plannable only
after the latest created week contains no active tournaments.

Weekly tournament Sunday rotation is configured by active
`WeeklyTournamentTemplate` rows with `rotation_order`. The planning flow sorts
Sunday templates by `rotation_order`; if an earlier Sunday tournament exists,
the next template after its type is selected, otherwise the first configured
Sunday template is used. Adding another Sunday template in the database changes
the default rotation without Python code changes. Templates are defaults for
new planning only; after tournaments are created, later template changes do not
change the meaning of existing weeks.

## Hall of Fame

Hall of Fame winners are manually curated in `season_hall_of_fame`.
`UserStatisticsService` and rating honours read this table through
`HallOfFameRepository`; they do not calculate winners from rating totals or
knockout totals. Superadmin management goes through
`HallOfFameManagementService`, which performs service-level authorization and
persists the selected champion and knockout leader.

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
