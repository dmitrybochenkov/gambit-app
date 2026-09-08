# Domain Model

## Identity Naming

- `telegram_id` is the external Telegram user ID. It is used at Telegram
  boundaries, public service use-cases, actor lookup, and notifications.
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
- `gender`: `male`, `female`, or `NULL`
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
- `gender = NULL` means unknown or not specified. Gender is never inferred from
  a name and is not requested during online registration.
- ADMIN may fill missing gender during in-person check-in; SUPERADMIN may
  correct it from the user management flow.
- Public result publication may decorate female players in the five prize/result
  rows with `🌸`. The stored `display_name` remains unchanged.

## Season

Rating period selected by tournament date.

Fields:

- `id`
- `name`
- `scoring_config_id`
- `starts_at`
- `ends_at`
- `is_statistics_visible`

Rules:

- Season lifecycle is date-driven; there is no persisted `Season.status`.
- `ends_at IS NULL` means the only open-ended season range.
- SQLite enforces at most one open-ended season through
  `uq_seasons_open_ended`.
- Tournament creation assigns the season found for that tournament date.
- Season creation drafts live only in Telegram FSM until confirmation.
- Hall of Fame and season statistics only expose seasons whose statistics are
  visible and whose date range is completed for the current business date.
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

- `telegram_id` stores the Telegram actor/source identity.
- `candidate_user_id` stores internal `users.id` for the historical user the
  actor wants to link.
- Registration review is a SUPERADMIN use-case.
- Result notifications for registration review go to active SUPERADMIN users
  with real Telegram IDs, not ordinary ADMIN users.

## ScoringConfig

Versioned scoring rules linked from seasons and copied to tournaments.

Fields:

- `id`
- `place_1_coefficient`
- `place_2_coefficient`
- `place_3_coefficient`
- `place_4_coefficient`
- `place_5_coefficient`
- `knockout_small_points`
- `knockout_big_points`
- `knockout_main_points`
- `knockout_main_final_points`
- `created_at`
- `updated_at`

Rules:

- Coefficients are stored as decimals.
- Place coefficients are not required to sum to `1`; v2 uses
  `0.45/0.30/0.20/0.15/0.10`.
- `knockout_main_points` and `knockout_main_final_points` are nullable for v1
  configurations.
- New tournament creation copies `Season.scoring_config_id` into
  `Tournament.scoring_config_id`.
- Tournament calculation and recalculation use `Tournament.scoring_config_id`;
  later season-default changes do not affect existing tournaments.
- New scoring rules require a new configuration row.

## Tournament

Poker tournament in the club schedule.

Fields:

- `id`
- `season_id`
- `tournament_type_id`
- `scoring_config_id`
- `date`
- `tournament_fund`
- `status`: `active`, `closed`
- `created_at`
- `updated_at`

Rules:

- `active` is editable/operational.
- `closed` is the only published result state.
- `scoring_config_id` is fixed when the tournament is created and is the
  authoritative scoring configuration for that tournament.
- Cancelled tournaments are deleted rather than status-tracked.
- Live close workflow requires a positive integer `tournament_fund` divisible by
  `10` before moving a tournament to `closed`.
- Historical/imported closed tournaments may have `tournament_fund = NULL`
  because old rating sheets contain calculated rating points, not the original
  tournament fund.
- If `tournament_fund` is set, the database requires it to be positive and
  divisible by `10`.
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
- Database allows duplicate places for historical ties.
- Live `ResultService` prevents duplicate assigned places in ordinary
  result-entry flows.
- Knockout counts and point fields are nonnegative.
- `bonus_points` is an integer, `NOT NULL`, default `0`, and `>= 0`.
- `total_points` is derived as
  `tournament_points + knockout_points + bonus_points`.

## TournamentType

Reusable tournament identity and public naming.

Fields:

- `id`
- `code`
- `name`
- `short_name`
- `description`
- `is_creatable`

Rules:

- `is_creatable = true` means administrators may create new tournaments of
  this type.
- `is_creatable = false` keeps historical/existing tournaments readable and
  correctable, but removes the type from new tournament creation choices.

## TournamentTypeRule

Reusable tournament scoring capabilities.

Fields:

- `id`
- `tournament_type_id`
- `points_multiplier`
- `prize_place_multiplier`
- `prize_place_multiplier_places`
- `knockout_mode`: `none`, `small`, `small_big`, `main_ko`
- `supports_bonus_points`

Rules:

- `prize_place_multiplier_places` is persisted as JSON only through the domain
  codec in `backend/app/domain/prize_multiplier_places.py`.
- `NULL` means prize-place multiplier is disabled.
- Non-empty values are sorted unique integer places from `1` to `5`.
- `mystery_bounty` currently uses `knockout_mode = small` and
  `supports_bonus_points = true`.
- Mystery Bounty result entry uses KO, does not use Boss KO, and supports bonus
  points.
- Mystery Bounty scoring uses saved result fields:
  `total_points = tournament_points + knockout_points + bonus_points`.
- `main_ko` uses the same result fields as `small_big`, but reads
  `ScoringConfig.knockout_main_points` and
  `ScoringConfig.knockout_main_final_points`.

## TournamentEconomyConfig / TournamentRebuyConfig

Economy configuration belongs to the tournament type, not to a weekly planning
draft. Admin weekly planning selects tournament day and tournament type only.
Public schedule formatting reads buy-in, stack, rebuy, addon, and description
from tournament type configuration.

## WeeklyTournamentTemplate

Default planning row for a weekday.

Fields:

- `weekday`
- `tournament_type_id`
- `rotation_order`
- `is_active`

Rules:

- Weekly planning supports Wednesday, Thursday, Friday, Saturday, and Sunday.
- Sunday rotation is DB-driven by active template rows with `rotation_order`.
- Templates are defaults for new planning only. Created tournaments keep their
  concrete `tournament_type_id`.

## TournamentPhoto

Telegram photo attached to a tournament.

Fields:

- `id`
- `tournament_id`
- `telegram_file_id`
- `telegram_file_unique_id`
- `uploaded_by_user_id`
- `position`
- `created_at`

Rules:

- One Telegram unique file can be stored once per tournament.
- Photos are part of close readiness and public result preview.
- Admin and SUPERADMIN photo presentation uses a control-message pattern:
  the control panel is restored after media is sent.

## TournamentCombination

Manual tournament combinations of the evening.

Fields:

- `id`
- `tournament_id`
- `player_id`
- `combination_type`: `four_of_a_kind`, `straight_flush`, `royal_flush`
- `rank`
- `created_at`

Rules:

- One row per tournament/player/combination type.
- `rank` is allowed only for four of a kind and stores the card rank.
- Combination publication uses these rows; result scoring is independent.

## TournamentPublication

Idempotency record for public Telegram publications.

Fields:

- `id`
- `tournament_id`
- `publication_type`: `results`, `schedule`
- `destination_type`: `group`, `channel`
- `destination_chat_id`
- `content_hash`
- `telegram_message_id`
- `published_at`
- `published_by_user_id`

Rules:

- Results and schedule can be published to configured group/channel
  destinations.
- Idempotency identity is
  `publication_type + destination_type + destination_chat_id + content_hash`.
- Publishing is independent from closing. Result notifications and reward
  notifications are also independent from public publication.

## PlayerReward

Prize-stack bonus granted to players in places 1-3 after tournament close.

Fields:

- `id`
- `player_id`
- `reward_type`: `prize_stack_bonus`
- `chips_amount`
- `source_tournament_id`
- `source_place`
- `issued_at`
- `valid_through`
- `redeemed_at`
- `redeemed_tournament_id`
- `redeemed_by_user_id`
- `redeemed_tournament_day`
- `expiration_reminder_sent_at`

Rules:

- Place 1 receives `40_000`, place 2 receives `30_000`, place 3 receives
  `20_000`.
- Validity is `7` business days from the source tournament lifecycle.
- Expiration reminder becomes due `4` days before `valid_through`; scheduler run
  hour is configured by `REWARD_REMINDER_RUN_HOUR`.
- One reward can be redeemed per player per tournament day.
- Reward issuance is idempotent by
  `source_tournament_id + player_id + reward_type`.
- Reward correction for CLOSED tournaments is reconciled by
  `PlayerRewardService`; corrected rewards keep source-tournament lifecycle
  semantics rather than correction-time semantics.

## Closed Tournament Correction

SUPERADMIN can correct CLOSED tournament data. Current implementation edits
result fields/player replacement in the stored result rows, then a finish step
validates readiness, recalculates points, reconciles player rewards, updates the
correction snapshot, and sends best-effort notifications.

This is the current contract. It is not a fully staged, reversible draft model.

## SeasonHallOfFame

Manual authoritative Hall of Fame entry for one completed season.

Fields:

- `id`
- `season_id`
- `champion_player_id`
- `knockout_player_id`
- `champion_photo_file_id`
- `champion_photo_file_unique_id`
- `knockout_photo_file_id`
- `knockout_photo_file_unique_id`
- `updated_by_user_id`
- `created_at`
- `updated_at`

Rules:

- One row per season.
- `champion_player_id` and `knockout_player_id` are nullable.
- Champion and knockout photos are optional.
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
