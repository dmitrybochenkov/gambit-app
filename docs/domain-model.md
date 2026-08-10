# Domain Model

## Identity Naming

- `telegram_id` is the external Telegram user ID. It is used at Telegram
  boundaries, public service use-cases, actor lookup, and notifications. It is
  not a gameplay foreign key.
- `user_id` is internal `users.id` in account, access, audit, and system-user
  contexts.
- `player_id` is internal `users.id` in gameplay contexts, such as
  `TournamentRegistration.player_id`, `TournamentResult.player_id`, ratings,
  history, and profile statistics.

`Player` is not a separate ORM entity. Any `ACTIVE User` can act as a player;
`role` controls access level, not play eligibility.

## User

Represents a Telegram user, historical player, or offline player profile.

Fields:

- `id`
- `telegram_id`
- `display_name`
- `display_name_normalized`
- `role`: `player`, `admin`, `superadmin`
- `status`: `active`, `blocked`
- `created_at`
- `updated_at`

Rules:

- `id` is the stable internal identity.
- `telegram_id` is nullable for historical/offline users.
- `display_name_normalized` is used for search and matching, not as a database
  identity.
- Duplicate normalized display names are allowed at database level.
- Public self-registration blocks accidental duplicate names as a business
  rule.

## Season

Rating period selected by tournament date.

Fields:

- `id`
- `name`
- `scoring_config_id`
- `starts_at`
- `ends_at`

Rules:

- Season lifecycle is date-driven; there is no persisted `Season.status`.
- `ends_at IS NULL` means the open-ended current/future season range.
- Tournament creation assigns the season found for that tournament date.
- Season creation drafts live only in Telegram FSM until confirmation.
- Technical `created_at` and `updated_at` timestamps are not part of the
  current season domain contract.

## RegistrationRequest

Telegram-originated request to create a new player profile or link a Telegram
account to an existing historical user.

Fields:

- `id`
- `telegram_id`
- `request_type`: `new_player`, `link_existing_player`
- `status`: `pending`, `approved`, `rejected`
- `requested_display_name`
- `requested_display_name_normalized`
- `requested_link_name`
- `candidate_user_id`
- `reviewed_at`
- `created_at`
- `updated_at`

Rules:

- `telegram_id` is required and stores the Telegram actor/source identity.
- `candidate_user_id` stores internal `users.id` for the historical user the
  actor wants to link.
- Rejection has no persisted free-text reason in the current UX.

## ScoringConfig

Scoring rules linked from a season.

Fields:

- `id`
- `place_1_coefficient`
- `place_2_coefficient`
- `place_3_coefficient`
- `place_4_coefficient`
- `place_5_coefficient`
- `knockout_small_points`
- `knockout_big_points`
- `created_at`
- `updated_at`

Rules:

- Coefficients are stored as decimals.
- Knockout values are stored in the season's `ScoringConfig`; calculations use
  the tournament season config, not hardcoded defaults.
- New scoring rules require a new configuration.

## Tournament

Poker tournament in the club schedule.

Fields:

- `id`
- `season_id`
- `tournament_type_id`
- `date`
- `tournament_fund`
- `status`: `active`, `closed`
- `created_at`
- `updated_at`

Rules:

- `active` is editable/operational.
- `closed` is the only published result state.
- Cancelled tournaments are deleted rather than status-tracked.
- Live close workflow requires a positive integer `tournament_fund` divisible by
  `10` before moving a tournament to `closed`.
- Historical/imported closed tournaments may have `tournament_fund = NULL`
  because old rating sheets contain calculated rating points, not the original
  tournament fund.
- One tournament date is allowed in the database.
- A created gaming week has no required number of tournaments. If a day is
  removed before confirmation, no tournament row is created for that day.
- Weekly tournament planning drafts live only in Telegram FSM until
  confirmation. The database stores only created tournaments.

## TournamentRegistration

Pre-registration intent before check-in.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `created_at`

Rules:

- Row exists means the player is registered.
- Cancellation deletes the row.
- Registration rows are immutable after creation.
- Cancellation is blocked after check-in because `TournamentResult` is already
  the actual tournament composition.
- One registration row per player per tournament.

## TournamentResult

Actual check-in row and final result for a tournament player.

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

Rules:

- Check-in creates the row.
- Admin result entry edits fields on this same row.
- One result/check-in row per player per tournament.
- `place` is empty or `1..5`.
- Prize places are unique inside a tournament.
- Knockout counts and point fields are nonnegative.
- `bonus_points` is an integer, `NOT NULL`, default `0`, and `>= 0`.
- `total_points` is derived as
  `tournament_points + knockout_points + bonus_points`.

## TournamentType / TournamentTypeRule

Tournament type stores reusable game/economy configuration. Weekly schedule
templates define default planning presets only. Management selects only date
and tournament type; public schedule formatting reads details from the type
configuration. A confirmed tournament stores its concrete `tournament_type_id`;
later template changes do not rewrite or re-evaluate existing weeks.

Rules:

- `prize_place_multiplier_places` is persisted as JSON only through the domain
  codec in `backend/app/domain/prize_multiplier_places.py`.
- `NULL` means prize-place multiplier is disabled.
- Non-empty values are sorted unique integer places from `1` to `5`.
- `mystery_bounty` uses `knockout_mode = none` and
  `supports_bonus_points = true`.
- Mystery Bounty result entry does not use KO or Boss KO fields. The
  `bonus_points` field is shown to administrators as "Доп. очки".
- Mystery Bounty scoring still uses saved result fields only:
  `total_points = tournament_points + knockout_points + bonus_points`; because
  `knockout_mode = none`, `knockout_points` remains `0`.

## SeasonHallOfFame

Manual authoritative Hall of Fame entry for one completed season.

Fields:

- `id`
- `season_id`
- `champion_player_id`
- `knockout_player_id`
- `updated_by_user_id`
- `created_at`
- `updated_at`

Rules:

- One row per season.
- `champion_player_id` and `knockout_player_id` are nullable.
- The same player may be both season champion and knockout leader.
- All foreign keys use `ON DELETE RESTRICT`.
- User Hall of Fame and rating honours read this table; they do not derive
  winners mathematically from rating rows.

## Import Semantics

Historical result import creates closed `legacy_unknown` tournaments and
`TournamentResult` rows with `source = walk_in_existing`.

For historical tournaments:

- `tournament_fund = NULL`; importer must not reconstruct, round, or fake a fund
  from calculated rating points.
- `Количество очков за турнир`, `Количество очков за КО`, and `Доп.очки` are
  imported as authoritative historical result points.
- Bonus points must be integer; fractional values fail fast.
