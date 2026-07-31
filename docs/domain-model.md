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
- `points_pool`: nullable until tournament results are finalized
- `status`: `active`, `closed`, `cancelled`
- `created_at`
- `updated_at`

Rules:

- `points_pool` is set when finalizing the tournament.
- A `closed` tournament must have `points_pool`; an `active` or `cancelled` tournament may leave it empty.

### TournamentRegistration

Player intent to join a tournament before the tournament starts.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `status`: `registered`, `cancelled`
- `registered_at`
- `cancelled_at`

Constraint:

- One active registration per player per tournament.

Rules:

- User self-registration and admin registration create or restore a
  `registered` row.
- User cancellation changes the row to `cancelled`.
- A cancelled row can be restored by a new registration.
- `TournamentRegistration` is not the final tournament composition. It is the
  source list for check-in.

### TournamentParticipant

Actual tournament composition and result-status container.

Fields:

- `id`
- `tournament_id`
- `user_id`
- `source`: `pre_registered`, `database_walk_in`, `admin_created`, `migrated_result`
- `result_status`: `active`, `no_result`
- `checked_in_by_user_id`
- `checked_in_at`

Constraint:

- One participant per user per tournament.

Rules:

- Registered players are moved into the actual composition during check-in.
- An admin can add an existing unregistered player as a walk-in.
- An admin can create an offline player and check them in immediately.
- Removing a participant is allowed only while no result data exists.
- Starting result entry uses `TournamentParticipant` as the actual player list.
- Admin registration for the current tournament also creates the matching
  `pre_registered` participant, keeping check-in and result entry consistent.

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

### User

`active` -> `blocked`

### Tournament

`active` -> `closed`

`active` -> `cancelled`

### Tournament Registration

`registered` -> `cancelled`

`cancelled` -> `registered`

### Tournament Participant

No row -> `active`

`active` -> `no_result`

`no_result` -> `active`

`active` -> row removed
