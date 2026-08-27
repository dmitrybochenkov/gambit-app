# Testing

## Validation Tiers

Use the smallest tier that matches the task. Do not run full project validation
after every small edit; use targeted tests while developing and run the agreed
final checkpoint once.

### Tier A: Read-Only Audit

For questions and audits without code changes:

```bash
rg ...
git diff --stat
git status --short
```

### Tier B: Presentation-Only Change

For Telegram labels, formatters, keyboards, navigation, and DTO presentation
shape when schema and business rules do not change:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest <targeted tests> -q
git diff --check
```

### Tier C: Service Or Domain Change

For use-case rules, service/repository contracts, reward logic, registration,
check-in, results, ratings, publications, imports, or scheduler behavior:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest -q
uv run python -m compileall app
git diff --check
```

### Tier D: Schema Or Migration Change

For ORM model changes, Alembic migrations, DB constraints, indexes, or import
contracts that depend on schema:

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

Add fresh and production-like SQLite upgrade checks when the migration can
behave differently on existing data.

### Tier E: Release Validation

For deploy readiness:

- full automated validation from Tier D;
- manual smoke checklist from `docs/manual-testing.md`;
- backup and rollback plan if data can be affected;
- health check and log check after deployment.

## Important Test Groups

- Repository architecture tests ensure services do not use SQLAlchemy query API
  directly. `session.flush`, `commit`, and `rollback` are allowed in services
  because services own transactions.
- Presentation architecture tests prevent wildcard imports and old flat
  keyboard/text/formatter dependency patterns.
- Telegram dispatcher regression tests exercise real aiogram callback paths.
- SQLite integration tests cover constraints and migration-sensitive behavior.
- Import tests cover dry-run/apply/idempotency and strict validation.
- Reward tests cover issuance, redemption, reminders, correction reconciliation,
  and best-effort Telegram notifications.

## Current Task Tier

Documentation-only refresh is Tier B for formatting/static validation plus full
suite only when explicitly requested by the task. The current documentation
refresh requested one final checkpoint:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pyright app
uv run pytest -q
git diff --check
uv run alembic current
uv run alembic check
```
