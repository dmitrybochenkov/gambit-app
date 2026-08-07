# Data Import

Historical data comes from Google Sheets / Excel exports.

Runtime import files on the server:

```text
/opt/apps/gambit/data/import/historical-users.csv
/opt/apps/gambit/data/import/rating-history.xlsx
```

## Historical Users

CLI:

```bash
python scripts/import_historical_users.py \
  --input <csv> \
  --db <db> \
  [--apply] \
  [--export-report <directory>]
```

Default mode is dry-run. Without `--apply`, the database is not changed.

Identity rules:

- `users.id` from CSV is the identity.
- Names are not identities.
- Duplicate display names are allowed in historical import.
- Existing users are not updated automatically.
- Conflicts block apply.

## Historical Ratings

CLI:

```bash
python scripts/import_rating_history.py \
  <xlsx> \
  --db <db> \
  [--apply] \
  [--export-report <directory>]
```

Rules:

- Does not create users, seasons, or tournament types.
- Resolves Excel player names through mapping and existing users.
- Creates historical tournaments as `closed`.
- Uses tournament type `legacy_unknown`.
- Imports only rows with resolved users.
- Creates `TournamentResult.source = walk_in_existing`.
- One transaction is used for apply.
- Repeated apply is idempotent.

## Historical Tournament Fund

For a historical tournament:

```text
tournament_fund =
SUM source field "Количество очков за турнир"
for all source rows on that date,
including blank and unresolved players.
```

The fund belongs to the tournament as a whole, not only to successfully
resolved users.

Validation:

- fund must be integer;
- fund must be positive;
- fund must be divisible by `10`;
- rounding is forbidden;
- invalid fund fails fast.

## Import Validation

Import fails fast on:

- invalid tournament fund;
- fractional bonus points;
- invalid place;
- duplicate place inside a tournament;
- invalid source;
- unresolved or ambiguous users in strict mode;
- identity/FK violations;
- strict-schema violations.

Import scripts report blank, unresolved, ambiguous, create, unchanged, conflict,
and invalid rows. Reports are deterministic and are not committed to Git.

## Production Runbook

```bash
cd /opt/apps/gambit

sudo systemctl stop gambit

mkdir -p /opt/apps/gambit/data/backups /opt/apps/gambit/data/import
cp /opt/apps/gambit/data/gambit.db \
  /opt/apps/gambit/data/backups/gambit-before-import-$(date +%Y%m%d-%H%M%S).db
sha256sum /opt/apps/gambit/data/backups/gambit-before-import-*.db | tail -n 1

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_historical_users.py \
  --input /opt/apps/gambit/data/import/historical-users.csv \
  --db /opt/apps/gambit/data/gambit.db \
  --export-report /opt/apps/gambit/data/import/users-dry-run

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_historical_users.py \
  --input /opt/apps/gambit/data/import/historical-users.csv \
  --db /opt/apps/gambit/data/gambit.db \
  --apply

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_historical_users.py \
  --input /opt/apps/gambit/data/import/historical-users.csv \
  --db /opt/apps/gambit/data/gambit.db \
  --export-report /opt/apps/gambit/data/import/users-after-apply

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_rating_history.py \
  /opt/apps/gambit/data/import/rating-history.xlsx \
  --db /opt/apps/gambit/data/gambit.db \
  --export-report /opt/apps/gambit/data/import/history-dry-run

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_rating_history.py \
  /opt/apps/gambit/data/import/rating-history.xlsx \
  --db /opt/apps/gambit/data/gambit.db \
  --apply

/opt/apps/gambit/backend/.venv/bin/python \
  /opt/apps/gambit/scripts/import_rating_history.py \
  /opt/apps/gambit/data/import/rating-history.xlsx \
  --db /opt/apps/gambit/data/gambit.db \
  --export-report /opt/apps/gambit/data/import/history-after-apply

sqlite3 /opt/apps/gambit/data/gambit.db \
  "PRAGMA foreign_key_check; PRAGMA integrity_check;"

sudo systemctl start gambit
curl --fail --silent http://127.0.0.1:8100/health
sudo journalctl -u gambit -n 100 --no-pager -o cat
```

Compare server dry-run `summary.json` files with local reports before apply.
Apply only when reports are safe and expected counts match.
