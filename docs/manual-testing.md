# Manual Testing

Manual smoke testing is release validation, not required for every small task.
Use it before server deploy or after broad changes across registration,
tournaments, results, rewards, and publication flows.

## Fresh Environment

1. Create an empty SQLite database path.
2. From `backend/`, run
   `DATABASE_URL=sqlite+aiosqlite:////path/to/gambit.db uv run alembic upgrade head`.
3. Bootstrap the first superadmin with
   `uv run python ../scripts/bootstrap_superadmin.py --db /path/to/gambit.db --telegram-id <id> --display-name "<name>"`.
4. Start the bot with the same database.
5. Send `/start` as the bootstrapped superadmin.
6. Open ADMIN and SUPERADMIN panels.

## Configuration Smoke

- Confirm `.env` has `CLUB_TIMEZONE`, `TOURNAMENT_DAY_START_HOUR`,
  `REWARD_REMINDER_RUN_HOUR`, `TELEGRAM_CLUB_CHAT_ID`, and
  `TELEGRAM_CLUB_CHANNEL_ID`.
- In Calendar, create the first season manually.
- Create a future season and confirm the current season `ends_at` is adjusted.
- Delete the future season before it starts and confirm previous season becomes
  open-ended again.
- Create weekly tournament proposals.
- Confirm weekly preview contains Wednesday, Thursday, Friday, Saturday, and
  Sunday unless a day was intentionally removed.
- Confirm Sunday type follows active `WeeklyTournamentTemplate.rotation_order`.
- Remove one day from the draft and confirm only remaining tournament rows are
  created.
- Confirm the next week is blocked while any tournament in the latest created
  week is `active`.

## Registration And Access

Use at least these identities:

- `S`: SUPERADMIN.
- `A`: ADMIN.
- `P1`: registered PLAYER who attends.
- `P2`: registered PLAYER who does not attend.
- `P3`: existing offline User checked in by admin.
- `P4`: new walk-in User created during check-in.

Smoke:

- New registration request notifies active SUPERADMIN users only.
- SUPERADMIN registration hub shows pending request count and active Telegram
  user count.
- Approve, reject, and link-existing flows update pending list.
- Ordinary ADMIN receives no registration-review notifications.
- `A` and `S` can still play; role controls access, not play eligibility.
- Assign ADMIN flow lists active `PLAYER` users only and does not mutate
  SUPERADMIN roles.

## User Tournament Registration

- User tournament list shows only active tournaments whose date is greater than
  or equal to the resolved tournament day.
- Before `TOURNAMENT_DAY_START_HOUR`, yesterday's game day is still visible.
- At and after the configured hour, yesterday disappears.
- CLOSED tournaments are not offered.
- Register and cancel a future tournament.
- If no active registration targets exist, the SUPERADMIN registration hub does
  not create a tournament-registration branch.

## Check-In

- Open Check-in for today's tournament.
- Confirm registered count matches `tournament_registrations`.
- Check in a registered player.
- Search and check in an existing offline user.
- Create and check in a new walk-in user.
- Confirm checked-in players appear in result entry.
- Confirm active rewards can be skipped or redeemed during check-in.
- Confirm one reward per player per tournament day is enforced.
- Confirm already checked-in users are shown in the already-attended screen.

## Result Entry

- Today's ACTIVE tournament is editable.
- Past ACTIVE tournament branch allows adding an existing user or a new user to
  `TournamentResult`.
- Places, KO, Boss KO, and bonus fields follow tournament type capabilities.
- Mystery Bounty allows KO and bonus points but does not allow Boss KO.
- Duplicate live assigned place is rejected or moved according to current
  result-entry UX.
- Duplicate player in one tournament is rejected.
- Result preview table stays compact on narrow Telegram screens.
- Uploaded photos use the control-message pattern.
- Add combinations of the evening, including four-of-a-kind rank.

## Closing

- Future ACTIVE tournaments are not offered for close.
- Today or past ACTIVE tournaments are offered for close.
- Fund is required for live close, must be positive, and must be divisible by
  `10`.
- Close readiness requires required result fields and photos according to the
  current tournament type.
- Closing calculates points atomically.
- Places 1-3 receive prize-stack rewards: `40_000`, `30_000`, `20_000`.
- Players with real Telegram IDs receive reward notification best-effort.
- Historical/offline users without real Telegram IDs do not block close.
- After close, SUPERADMIN sees full public results/schedule preview.
- Publishing results is independent from closing and from reward notification.
- Publishing to group/channel is idempotent for unchanged content.

## Reward Lifecycle

- Profile shows active prize-stack bonuses.
- During check-in, reward can be used or skipped.
- One reward per business day can be redeemed.
- Expiration reminders are due four days before `valid_through`.
- Reminder sending marks `expiration_reminder_sent_at` and does not resend the
  same due reward group.

## Public Screens

Before close:

- History does not include the tournament.
- Rating does not change.
- Profile result statistics do not change.
- Hall of Fame does not change.

After close:

- History includes the tournament and saved result points.
- Rating changes and displayed points are rounded for Telegram UI.
- Profile statistics and prize history update.
- Hall of Fame does not change automatically.
- SUPERADMIN fills completed seasons manually through Hall of Fame flow.
- Tournament photos are viewable in history/profile where supported.

## CLOSED Tournament Correction

- SUPERADMIN opens closed tournament repair.
- Edit place/KO/Boss KO/bonus fields.
- Replace an incorrectly selected player with another valid user.
- Duplicate player in the same tournament is rejected.
- Finish recalculates points and reconciles rewards.
- Reward correction notifications are best-effort and do not depend on public
  result publication.
- Existing redeemed rewards do not block correction; warnings are shown.
- Correction validity uses source tournament lifecycle, not correction time.

## Season Boundary And Hall Of Fame

- A current season with future `ends_at` is not in Hall of Fame.
- Completed seasons are those with `ends_at` before the business date.
- Hidden seasons do not appear in public season statistics.
- Selecting champion and knockout leader updates user Hall of Fame and rating
  honour markers.
- Hall of Fame photos upload and preview work for both champion and knockout
  slots.

## Database Checks

After the scenario:

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

Expected:

- `foreign_key_check` returns no rows.
- `integrity_check` returns `ok`.
