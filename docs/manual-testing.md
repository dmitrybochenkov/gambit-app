# Manual Testing

## Fresh Environment

1. Create an empty SQLite database path.
2. From `backend/`, run `DATABASE_URL=sqlite+aiosqlite:////path/to/gambit.db uv run alembic upgrade head`.
3. Bootstrap the first superadmin with `uv run python ../scripts/bootstrap_superadmin.py --db /path/to/gambit.db --telegram-id <id> --display-name "<name>"`.
4. Start the bot with the same database.
5. Send `/start` as the bootstrapped superadmin.
6. Open the admin and superadmin panels.

## Configuration

1. In Calendar, create the first season manually.
2. In Calendar, create weekly tournament proposals.
3. Confirm that the weekly preview contains Wednesday, Thursday, Friday, Saturday, and Sunday.
4. Confirm that Sunday type follows `WeeklyTournamentTemplate.rotation_order`.

## Test Users

Use six accounts/identities:

- `S`: SUPERADMIN.
- `A`: ADMIN.
- `P1`: registered PLAYER who attends.
- `P2`: registered PLAYER who does not attend.
- `P3`: existing offline User checked in by admin.
- `P4`: new walk-in User created during check-in.

ADMIN and SUPERADMIN can also play; include both in game-day checks.

## Registration Matrix

- `P1` registers before the tournament and attends.
- `P2` registers before the tournament and does not attend.
- `P3` is found as an existing User during check-in.
- `P4` is created as a new walk-in during check-in.
- `A` registers and plays.
- `S` plays as an existing or walk-in User.

Expected result:

- `TournamentRegistration` represents intent to play.
- `TournamentResult` contains only players who actually checked in.

## Check-In

1. Open Check-in for today's tournament.
2. Confirm registered count matches `tournament_registrations`.
3. Search and confirm registered players.
4. Search existing offline users.
5. Create a new walk-in user.
6. Confirm each check-in creates or reuses a `TournamentResult`.
7. Confirm checked-in players appear in result entry.

## Result Entry

1. Today's ACTIVE tournament is editable.
2. Yesterday or future stale callbacks do not mutate the database.
3. Places are unique; assigning an occupied place moves it to the latest player.
4. KO and big KO values are saved.
5. Bonus points accept integers only.

## Closing

1. Future ACTIVE tournaments are not offered for close.
2. Today or past ACTIVE tournaments are offered for close.
3. Fund must be positive.
4. Fund must be divisible by 10.
5. Closing calculates points atomically.

## Publication Checks

Before close:

- History does not include the tournament.
- Rating does not change.
- Profile does not change.
- Hall of Fame does not change.

After close:

- History includes the tournament and saved result points.
- Rating changes.
- Profile changes.
- Hall of Fame changes only for completed seasons.

## Season Boundary

Create a future season and confirm:

- The current season with future `ends_at` is not in Hall of Fame.
- Completed seasons are those with `ends_at` before the business date.

## Database Checks

After the scenario:

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

Expected:

- `foreign_key_check` returns no rows.
- `integrity_check` returns `ok`.
