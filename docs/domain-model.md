# Domain Model

## Entities

### Player

Represents both the Telegram user and club player profile.

Fields:

- `id`
- `telegram_id`
- `full_name`
- `nickname`
- `status`: `pending`, `active`, `rejected`, `blocked`
- `role`: `user`, `admin`, `superadmin`
- `approved_at`
- `approved_by_admin_id`
- `rejected_at`
- `rejected_by_admin_id`
- `rejection_reason`
- `created_at`
- `updated_at`

Uniqueness:

- `nickname` unique when not empty.
- `full_name` unique when not empty.

Display name rule:

- If both `full_name` and `nickname` exist: `Full Name (NICKNAME)`.
- If only `nickname` exists: `NICKNAME`.
- If only `full_name` exists: `Full Name`.

`display_name` should not be stored in MVP. It is derived from `full_name` and `nickname`.

### Admin

Admin is a player with `role` set to `admin` or `superadmin`.

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
- `points_pool`: nullable until tournament results are finalized
- `status`: `active`, `closed`, `cancelled`
- `created_at`
- `updated_at`

Rules:

- `points_pool` is set when finalizing the tournament.
- A `closed` tournament must have `points_pool`; an `active` or `cancelled` tournament may leave it empty.

### TournamentRegistration

Player registration for a tournament.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `status`: `registered`, `cancelled`
- `registered_at`
- `cancelled_at`

Constraint:

- One active registration per player per tournament.

### TournamentResult

Final tournament result for a player.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `place`
- `knockouts_count`
- `boss_knockouts_count`
- `tournament_points`
- `knockout_points`
- `bonus_points`
- `created_at`
- `updated_at`

Constraint:

- One result per player per tournament.

Derived values:

- `tournament_points` = tournament `points_pool` * coefficient for `place`
- `knockout_points` = `knockouts_count` * config `knockout_points` + `big_knockouts_count` * config `big_knockout_points`
- `total_points` = `tournament_points` + `knockout_points` + `bonus_points`
- Tournament date is taken from the related tournament.

## Status Lifecycles

### Player

`pending` -> `active`

`pending` -> `rejected`

`active` -> `blocked`

### Tournament

`active` -> `closed`

`active` -> `cancelled`

### Tournament Registration

`registered` -> `cancelled`
