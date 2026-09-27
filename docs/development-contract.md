# Development Contract

This document is the working contract for Codex and human contributors. It
describes current runtime architecture, not an aspirational rewrite plan.

## Layer Contract

Runtime code follows this direction:

```text
Telegram handler -> DTO -> Service -> Repository -> ORM / SQLite
HTTP API dependency/router -> DTO -> Service -> Repository -> ORM / SQLite
```

Handlers:

- read Telegram updates and FSM data;
- call service use-cases;
- map expected service/domain errors to Telegram messages;
- format DTOs with concrete formatter/text/keyboard modules;
- do not query SQLAlchemy, create ORM objects, or decide domain policy.

HTTP API routes and dependencies:

- verify transport credentials at the HTTP boundary;
- call application services to resolve users and execute use-cases;
- return API schemas rather than ORM models;
- do not import repositories or ORM models directly;
- do not pass frontend-provided identity or role into domain decisions.

Services:

- own public use-cases and transaction boundaries;
- open one `AsyncSession` per public use-case;
- call `AccessPolicy` for administrative authorization inside the same session;
- compose repositories and other narrow services when needed;
- commit, flush, and rollback mutations;
- return immutable DTOs, not ORM models.

Repositories:

- receive an existing `AsyncSession`;
- own SQLAlchemy query and persistence details;
- do not open sessions;
- do not commit;
- do not call services;
- do not encode business policy beyond persistence-specific filtering.

ORM models:

- represent persisted schema only;
- do not send Telegram messages;
- do not contain presentation logic.

## Service Composition

Service-to-service composition is allowed only when it preserves one public
transaction boundary. A public mutation use-case may pass its active
`AsyncSession` into a narrow domain service method that is explicitly designed
for that use-case.

Current example: `ResultService` delegates prize-stack-bonus issuance and
correction reconciliation to `PlayerRewardService`, while the result close or
CLOSED-correction use-case still owns the overall transaction and commit.

Avoid direct calls into private methods of another service. If a rule is shared,
promote it into a public narrow use-case, a domain helper, or a repository
contract.

## Transactions

One public mutation use-case should produce one coherent database mutation.
Side effects such as Telegram notifications run only after the data needed for
that side effect has been persisted according to the current use-case contract.
Best-effort notification failures must not undo successful business mutations
unless the task explicitly changes that contract.

Registration review approve/reject commands atomically claim a pending request
inside the service-owned transaction, so concurrent decisions have exactly one
winner and losing commands receive the controlled already-reviewed error. A
successful command returns a transport-neutral canonical outcome. Shared
application orchestration delivers applicant and other-superadmin Telegram
notifications only after commit; delivery is best effort and has no durable
outbox or retry guarantee.

## Authorization

Canonical authorization uses internal `users.id`: the neutral
`AccessPolicy.require_active_user()`, `require_admin()`, and
`require_superadmin()` methods accept `actor_user_id`. All transport-neutral
application actor contracts use internal IDs; Telegram IDs remain valid only
for authentication, delivery, onboarding, linking, and identity mapping.
Telegram handlers may hide buttons for UX, but the service check is
authoritative.

HTTP routes pass
`AuthenticatedActor.user_id`; Telegram handlers resolve raw `from_user.id`
through narrow transport helpers before invoking shared services. Do not add
actor IDs to HTTP payloads or pass raw Telegram IDs directly into migrated
methods.

## Clock And Tournament Day

Domain decisions use injected `Clock` and `resolve_tournament_day()`. Do not use
`date.today()` or `datetime.now()` directly for game-day decisions.

The configured tournament day starts at `TOURNAMENT_DAY_START_HOUR` in
`CLUB_TIMEZONE`. Before that hour, game-day flows still treat the previous
calendar date as the current tournament day.

## FSM And Drafts

Unfinished Telegram planning state lives in aiogram FSM. The database stores
confirmed business facts only. Bot restarts may lose unfinished calendar,
season, result-entry, and repair-flow drafts; handlers must handle stale FSM or
callback state safely.

`admin_prompts` is removed from runtime schema. Do not reintroduce prompt tables
for new planning flows without a separate architecture decision.

## Telegram Presentation

Presentation code is split by role and scenario:

```text
backend/app/bot/telegram/
  handlers/{user,admin,superadmin}/...
  keyboards/{user,admin,superadmin}/...
  texts/...
  formatters/...
```

Role package `__init__.py` files assemble routers only. Scenario handlers import
concrete keyboard, formatter, and text modules. Do not recreate giant flat
keyboard/formatter/text facades.

All message edits should use the shared safe edit helpers. The Telegram server
is the authoritative source for whether a message changed; local message
snapshots may be stale.

## WebApp API

The Telegram WebApp API lives under `/api/v1` and is another transport adapter
over existing services. The current auth contract is:

```http
Authorization: tma <raw Telegram WebApp initData>
```

The server verifies the initData signature with the Telegram bot token and
checks `auth_date` freshness before extracting a trusted Telegram user id.
Frontend-provided `telegram_id`, `user_id`, and role values are never trusted.

`GET /api/v1/me` is the bootstrap endpoint for future WebApp UI. Player
tournament endpoints expose current-week schedule and self-registration:

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

Privileged check-in and participant routes are application-service adapters:

- `GET /api/v1/admin/tournaments/{tournament_id}/check-in`
- `GET /api/v1/admin/tournaments/{tournament_id}/check-in/players`
- `GET /api/v1/admin/tournaments/{tournament_id}/check-in/registered`
- `GET /api/v1/admin/tournaments/{tournament_id}/check-in/users`
- `GET /api/v1/admin/tournaments/{tournament_id}/check-in/players/{player_id}/decision`
- `POST /api/v1/admin/tournaments/{tournament_id}/check-ins`
- `GET /api/v1/admin/tournaments/{tournament_id}/participants/candidates`
- `POST /api/v1/admin/tournaments/{tournament_id}/participants`
- `DELETE /api/v1/admin/tournaments/{tournament_id}/participants/{player_id}`

Privileged tournament finalization and correction routes are also thin
application-service adapters:

- `GET /api/v1/admin/tournaments/{tournament_id}/close-readiness`
- `POST /api/v1/admin/tournaments/{tournament_id}/close-preview`
- `POST /api/v1/admin/tournaments/{tournament_id}/close`
- `GET /api/v1/admin/tournaments/{tournament_id}/correction`
- `POST /api/v1/admin/tournaments/{tournament_id}/correction-preview`
- `POST /api/v1/admin/tournaments/{tournament_id}/correction`

SUPERADMIN registration-review routes expose the same application boundary as
Telegram:

- `GET /api/v1/admin/registrations/pending`
- `GET /api/v1/admin/registrations/{request_id}`
- `POST /api/v1/admin/registrations/{request_id}/candidate`
- `POST /api/v1/admin/registrations/{request_id}/approve`
- `POST /api/v1/admin/registrations/{request_id}/reject`

Candidate selection is validation-only and is revalidated during approval.
Approve/reject mutations use `RegistrationReviewUseCases`, so their Telegram
notifications run after commit with the same best-effort semantics as Telegram
initiated reviews. Stale/already-reviewed decisions map to HTTP conflict. This
surface does not provide general user, administrator, or role management.

`ResultService` owns close validation, scoring, status transition, reward
issuance, and commit. `ClosedTournamentCorrectionService` owns canonical
snapshots, fail-closed draft validation, stale detection, rescoring, reward
reconciliation, and commit. Correction clients may submit proposed persisted
fields, but never calculated points or reward outcomes. Both use-cases enforce
SUPERADMIN authorization inside the service. Telegram notifications happen
after a successful commit and remain best-effort transport effects; publication
is a separate explicit use-case.

Privileged tournament-planning routes live under `/api/v1/admin/planning` and
delegate all calendar rules and persistence to `TournamentPlanningService`.
The surface provides month/week reads, type options/details, create preview and
apply, week autofill preview and apply, week approval preview and apply, future
type-change preview and apply, and future deletion preview and apply. HTTP does
not infer editability, assign seasons/scoring configs, open registration, or
delete registrations directly. Cancellation recipients are a semantic
post-commit outcome; Telegram delivery remains best effort.

Privileged season-management routes live under `/api/v1/admin/seasons` and
delegate the date-derived timeline to `SeasonService`. At most one future
season may exist. Creating it atomically closes the current season on the prior
day; deleting it atomically reopens the previous season and is rejected while
tournaments reference the future season. The service derives the scoring
configuration and revalidates authoritative state on apply. No generic season
CRUD, client-selected lifecycle state, explicit finish command, or achievement
side effect belongs in this boundary.

The existing-player check-in mutation keeps gender completion, optional reward
redemption, and result creation in one service-owned transaction. A failed
reward/check-in must not persist a partial gender change. New walk-in user and
result creation are likewise atomic. HTTP and Telegram must call this shared
boundary; neither transport may own a session or reproduce reward, source, or
duplicate policy.

These endpoints resolve the current active user through `UserAccessService` and
delegate registration rules to `TournamentService`. The HTTP layer must not
duplicate current-week, `registration_open`, duplicate-registration, or
ownership policy. Frontend input never selects another user; the actor always
comes from verified initData.

Read-heavy player endpoints must keep transport-specific presentation out of
the API contract. Return semantic achievement fields, persisted point values,
and reward lifecycle fields; do not return Telegram emoji strings as the only
source of meaning. WebApp media URLs require a separate media endpoint or proxy;
Telegram `file_id` values are not exposed as browser URLs.

## Naming Rules

- `telegram_id`: external Telegram user identity.
- `user_id`: internal `users.id` in account/access/audit contexts.
- `player_id`: internal `users.id` in gameplay contexts.
- `Player` is not a runtime ORM entity.
- Physical FK columns named `player_id` may still point to `users.id` in
  gameplay tables. Do not rename them casually.
- Internal `big_*` names remain the storage/domain contract. User-facing text
  uses "Босс КО" or compact table labels where appropriate.

## Current Domain Guardrails

- `User.display_name_normalized` is not unique in the database.
- Public self-registration still blocks accidental duplicate normalized names.
- `Tournament.date` is unique.
- `Tournament.status` is only `active` or `closed`.
- Cancelled tournaments are deleted rather than status-tracked.
- `TournamentResult` is both check-in row and final result row.
- One player can have one result per tournament.
- Database allows tied places for historical data; live result service prevents
  duplicate assigned places in ordinary editing.
- `tournament_fund` may be `NULL`; live close requires a valid fund, imported
  legacy CLOSED tournaments may keep it null.
- Mystery Bounty supports ordinary KO and does not support Boss KO.
- Prize-stack rewards are issued from places 1-3 by `PlayerRewardService`.

## Validation Tiers

Choose the smallest validation tier that matches the task.

Tier A, read-only audit:

```bash
rg ...
git diff --stat
git status --short
```

Tier B, presentation-only change:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest <targeted tests> -q
git diff --check
```

Tier C, service/domain change:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest -q
uv run python -m compileall app
git diff --check
```

Tier D, schema/migration change:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest -q
uv run alembic upgrade head
uv run alembic current
uv run alembic check
git diff --check
```

Add fresh/prod-like SQLite upgrade checks when a migration can behave
differently on existing data.

Tier E, release validation:

- full automated validation from Tier D;
- manual smoke checklist from `docs/manual-testing.md`;
- production backup and rollback plan when deployment touches data.

Do not run broad validation after every small edit. During implementation use
targeted tests, then run the agreed final tier once.

## Known Tech Debt

- `TournamentPlanningService` owns calendar reads, weekly planning, type
  details, approval, edit, and deletion in one large service. The responsibilities
  are real and tested, but their size deserves a separate responsibility-cluster
  audit before any decomposition.
- `ClosedTournamentCorrectionService` owns correction snapshots, validation,
  point recalculation, reward reconciliation, photos, combinations, and
  notifications. It now uses repositories for its in-transaction CLOSED-result
  reads and scoring/capability dependencies rather than private `ResultService`
  methods.
- `ResultService` remains responsible for normal result editing and tournament
  close orchestration. Shared validation and point calculations are explicit
  public result contracts, while service-specific view assembly remains private.
- Application-service actor interfaces use internal `actor_user_id` across
  player, ADMIN, and SUPERADMIN operations. Telegram identity mapping remains a
  transport concern in `UserAccessService`.
- `UserRepository` currently contains query and persistence primitives only;
  the audited tree has no commit-owning compatibility methods. User/admin HTTP
  commands must continue through `UserRenameService`, `AdminManagementService`,
  or an explicit use-case boundary rather than acquiring repository workflow
  methods. Registration review remains a separate service/use-case boundary.
- Hall of Fame management mutations go through `HallOfFameManagementService`.
  Singleton awards are replaced in place, repeatable awards remain independent
  rows, and deletion must use `HallOfFameAchievement.id`; transports must not
  reproduce those rules or accept canonical achievement metadata from clients.
- Deployment and migration ordering is operational documentation rather than
  repository automation. Operators must keep new-schema-dependent application
  code stopped until `alembic upgrade head` succeeds.

Architecture tests enforce presentation package boundaries and prohibit direct
SQLAlchemy query APIs in services while allowing transaction lifecycle methods.
The preferred handler/API -> service -> repository -> ORM direction is also a
documented convention; it is not exhaustively proven for every dependency by a
single architecture test.
- Tournament-specific public copy still exists in presentation formatters for
  schedule descriptions and some labels. Capability decisions should remain
  DB/service-driven.
- FSM state is intentionally ephemeral; there is no durable recovery for
  unfinished admin flows after bot restart.
- Historical import scripts encode import policy and reporting. They are
  operational tools, not runtime services.

## Cleanup Candidates

These are not part of ordinary feature work unless a task explicitly says so:

- further split `ResultService`;
- further split `superadmin/tournament_close.py`;
- make CLOSED correction fully staged before persistence;
- normalize remaining tournament-specific presentation copy;
- add durable admin draft persistence if bot-restart recovery becomes required.

## Current vs Future

Document and implement only current behavior. Mark future ideas as future ideas.
Do not describe target-state work as already implemented, and do not change
runtime behavior while refreshing documentation.
