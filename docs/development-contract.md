# Development Contract

This document is the working contract for Codex and human contributors. It
describes current runtime architecture, not an aspirational rewrite plan.

## Layer Contract

Runtime code follows this direction:

```text
Telegram handler -> DTO -> Service -> Repository -> ORM / SQLite
```

Handlers:

- read Telegram updates and FSM data;
- call service use-cases;
- map expected service/domain errors to Telegram messages;
- format DTOs with concrete formatter/text/keyboard modules;
- do not query SQLAlchemy, create ORM objects, or decide domain policy.

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

## Authorization

Every public administrative service method must receive `actor_telegram_id` and
call `AccessPolicy.require_admin()` or `AccessPolicy.require_superadmin()`
inside the service. Telegram handlers may hide buttons for UX, but the service
check is authoritative.

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

- `ResultService` and `handlers/superadmin/tournament_close.py` remain large.
  They are current runtime code, not a signal to broaden unrelated tasks.
- CLOSED tournament correction mutates draft changes before the final finish
  step. Finish validates, recalculates points, reconciles rewards, and sends
  notifications. A future task may introduce a more explicit staged correction
  model if needed.
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
