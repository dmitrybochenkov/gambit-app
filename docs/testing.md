# Testing

Common validation commands:

```bash
cd backend
uv run ruff check .
uv run ruff format . --check
uv run pytest -q
uv run python -m compileall app
git diff --check
uv run alembic check
```

Important test groups:

- repository architecture tests ensure services do not use SQLAlchemy query API
  directly;
- presentation architecture tests prevent wildcard imports and old flat
  keyboard/text dependency patterns;
- Telegram dispatcher regression tests exercise real aiogram callback paths;
- SQLite integration tests cover constraints and migration-sensitive behavior;
- import tests cover dry-run/apply/idempotency and strict validation.
