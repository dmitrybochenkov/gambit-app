# Domain Model

## Entities

### User

Represents a Telegram user, historical player, or offline player profile.

Fields:

- `id`
- `telegram_id`
- `display_name`
- `display_name_normalized`
- `status`: `active`, `blocked`
- `role`: `player`, `admin`, `superadmin`
- `approved_at`
- `approved_by_admin_id`
- `created_at`
- `updated_at`

Identity:

- `id` is the stable internal identity.
- `telegram_id` links a Telegram account when it exists.
- `display_name_normalized` is used for search and matching, not as a database identity.

### Admin

Admin is a user with `role` set to `admin` or `superadmin`.

### Season

Rating period.

Fields:

- `id`
- `name`
- `scoring_config_id`
- `starts_at`
- `ends_at`
- `status`: `active`, `closed`

### ScoringConfig

Scoring rules for a season.

Fields:

- `id`
- `place_1_coefficient`: `0.45`
- `place_2_coefficient`: `0.25`
- `place_3_coefficient`: `0.15`
- `place_4_coefficient`: `0.10`
- `place_5_coefficient`: `0.05`
- `knockout_points`: `15`
- `big_knockout_points`: `60`
- `created_at`
- `updated_at`

Authoritative default knockout values live in
`backend/app/domain/scoring.py::TournamentScoring`.

Constraint:

- Coefficients are stored as decimal values, not floating-point values.
- A scoring configuration can be shared by multiple seasons.
- Once a configuration is used for tournament results, it is immutable. New rules require a new configuration.

### Tournament

Poker tournament in the club schedule.

Fields:

- `id`
- `season_id`
- `type`: `1`, `2`, `3`
- `date`
- `capacity`
- `tournament_fund`: nullable until tournament results are finalized
- `status`: `active`, `closed`, `cancelled`
- `created_at`
- `updated_at`

Rules:

- `tournament_fund` is set when finalizing the tournament.
- A `closed` tournament must have `tournament_fund`; an `active` or `cancelled` tournament may leave it empty.

### TournamentRegistration

Player intent to join a tournament before the tournament starts.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `created_at`
- `updated_at`

Constraint:

- One registration row per player per tournament.

Rules:

- User self-registration and admin registration create the row.
- User cancellation deletes the row.
- Repeated registration and cancellation are idempotent from the user flow.
- `TournamentRegistration` is not the final tournament composition. It is the
  source list for check-in.

### TournamentResult

Actual check-in row and final tournament result for a player.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `source`: `registered`, `walk_in_existing`, `walk_in_new`
- `checked_in_at`
- `checked_in_by_user_id`
- `place`
- `knockouts_count`
- `big_knockouts_count`
- `bonus_points`
- `tournament_points`
- `knockout_points`
- `created_at`
- `updated_at`

Constraint:

- One result/check-in row per player per tournament.

Rules:

- Check-in creates the row.
- Admins edit result fields directly on this row.
- Superadmin closing calculates rating points and closes the tournament.

Derived values:

- `tournament_points` = tournament `tournament_fund` * coefficient for `place`
- `knockout_points` = `knockouts_count` * config `knockout_points` + `big_knockouts_count` * config `big_knockout_points`
- `total_points` = `tournament_points` + `knockout_points` + `bonus_points`
- Tournament date is taken from the related tournament.

## Status Lifecycles

### User

`active` -> `blocked`

### Tournament

`active` -> `closed`

`active` -> `cancelled`

### Tournament Registration

No persisted status lifecycle.

Row exists -> user is registered.

Row absent -> user is not registered.
