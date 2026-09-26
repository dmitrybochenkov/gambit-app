# Architecture

Contributor guardrails, validation tiers, and known cleanup candidates are
maintained in [development-contract.md](development-contract.md).

## Layers

```text
Telegram handler
-> Service use-case
-> Repository
-> ORM / SQLite
```

HTTP WebApp routes follow the same application boundary:

```text
HTTP router/dependency
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

### HTTP API

- Exposes versioned routes under `/api/v1`.
- Authenticates Telegram Mini App requests by verifying signed initData from
  `Authorization: tma <raw_init_data>`.
- Resolves the trusted Telegram identity through application services.
- Returns API schemas, not ORM models.
- Does not import repositories or ORM models directly.

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

- `AdminManagementService`
- `HallOfFameManagementService`
- `PlayerRewardService`
- `ProfileService`
- `RatingService`
- `RegistrationReviewService`
- `RegistrationService`
- `ResultService`
- `SeasonService`
- `TournamentCheckInService`
- `TournamentPlanningService`
- `TournamentPublicationService`
- `TournamentScheduleService`
- `TournamentService`
- `UserAccessService`
- `UserRenameService`
- `UserStatisticsService`

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

`hall_of_fame_achievements` is the authoritative occurrence store. Each row
identifies one achievement by `kind`, player, season, and `awarded_at`;
`achievement_types` supplies the canonical `title`, fallback `emoji`, and
nullable Telegram `custom_emoji_id`. Presentation metadata is joined by kind
instead of being duplicated in services or DTO construction.

`rating_winner`, `ko_rating_winner`, and `grand_season` are singleton kinds per
season. `grand_month` and `grand_knockout` may have repeated occurrences. The
legacy `season_hall_of_fame` table was the source for champion/knockout data and
photo slots during migration history, but it is no longer part of the current
runtime schema. Season photos are retained separately in `hall_of_fame_photos`.

`HallOfFameManagementService` owns superadmin mutation use-cases.
`HallOfFameRepository` supplies occurrence-based reads to Hall of Fame, rating,
and profile services; those consumers do not calculate winners from rating
totals or knockout totals.

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
- Telegram WebApp bootstrap uses `GET /api/v1/me`; frontend-provided
  `telegram_id`, `user_id`, and role values are ignored because identity comes
  only from verified Telegram initData.
- Expected domain errors are handled near the scenario and mapped to Telegram
  text.
- Unexpected errors are logged by the Telegram error boundary and receive a
  safe fallback.
- Stale callbacks must not repeat mutations; services validate prompt/result
  lifecycle before applying changes.

## WebApp API

The WebApp API is a second transport adapter over the same services, not a
separate business layer. Player-facing endpoints currently include:

- `GET /api/v1/me`
- `GET /api/v1/tournaments/week`
- `GET /api/v1/tournaments/{tournament_id}`
- `GET /api/v1/me/registrations`
- `POST /api/v1/tournaments/{tournament_id}/registration`
- `DELETE /api/v1/tournaments/{tournament_id}/registration`
- `GET /api/v1/ratings`
- `GET /api/v1/ratings/knockouts`
- `GET /api/v1/me/profile`
- `GET /api/v1/me/history`
- `GET /api/v1/me/history/{tournament_id}`
- `GET /api/v1/hall-of-fame`
- `GET /api/v1/me/rewards`

Authentication contract:

```http
Authorization: tma <raw Telegram WebApp initData>
```

The backend verifies the Telegram signature server-side using the configured
bot token, checks `auth_date` against
`TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS`, and extracts the trusted Telegram user
id only after signature validation. The API never trusts identity or role from
request bodies, query parameters, or frontend state.

Current `/me` response contains only bootstrap-safe fields: internal user id,
display name, role, gender, and active status. It intentionally omits
`telegram_id`, normalized names, timestamps, and statistics.

Tournament endpoints use `TournamentService`, the same player registration
use-cases used by Telegram. The current week is derived from the configured
club business day through `resolve_tournament_day()`, not from frontend state.
Only active tournaments in the current business week with
`registration_open=true` are shown or accepted for registration. Duplicate
registration requests are idempotent; stale or unavailable tournament actions
are rejected by the service. Player-facing responses expose public schedule
data and the authenticated user's own registration state, but not admin-only
readiness, result-entry, or fund fields.

Rating, profile, history, Hall of Fame, and reward endpoints expose semantic
data from the existing read services. Hall of Fame responses include occurrence
id, kind, award date, canonical title, fallback emoji, nullable custom emoji id,
and player. Rating responses expose the same occurrence metadata and preserve
the service ordering and multiplicity. Profile responses retain the existing
ordered kind list and legacy-compatible winner counts while also exposing full
honour occurrences and service-computed lifetime poker-combination totals.
Player history detail exposes independently identified tournament-combination
occurrences in repository order. Unicode emoji are presentation metadata, not
achievement identity. Hall of Fame photos are not exposed in the WebApp API
because stored values are Telegram `file_id` values, not browser-ready media
URLs.

### Known API Contract Gaps / Follow-up

- Hall of Fame and tournament photos require a browser-media delivery contract
  before they can be exposed to WebApp clients. Stored Telegram `file_id`
  values are transport-specific references, not browser URLs.
- The current HTTP surface is player-facing. Administrative check-in, result
  entry, planning, correction, season management, Hall of Fame management, and
  registration review remain real application use-cases without HTTP adapters;
  adding them requires explicit mutation schemas and role-equivalent API tests,
  not repository access from routes.
- Initial player onboarding remains Telegram-specific while WebApp
  authentication requires an existing active user resolved from signed initData.

Application/auth API errors use a top-level JSON contract:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Invalid Telegram WebApp initData"
  }
}
```

CORS is not enabled yet because no cross-origin frontend deployment has been
chosen. If the WebApp frontend is served from another origin, add an explicit
allowlist setting instead of using `*`.

WebApp endpoints rely on verified Telegram initData for the current actor.
If future endpoints are exposed outside Telegram WebApp context, make an
explicit session/CSRF decision before enabling those transports.
