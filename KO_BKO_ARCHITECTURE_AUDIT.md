# KO/BKO Architecture Audit

## Current storage and ownership

- Per-player event counts and the already calculated rating value are persisted on
  `tournament_results`: `knockouts_count`, `big_knockouts_count`, and
  `knockout_points` (`backend/app/db/models/tournament_result.py:50-63`). Non-negative
  checks are at `:75-82`.
- Point values are stored on `scoring_configs` as `knockout_small_points` and
  `knockout_big_points`; MAIN KO additionally uses nullable
  `knockout_main_points` and `knockout_main_final_points`
  (`backend/app/db/models/scoring_config.py:30-41`). The schema only enforces
  non-negativity (`:64-79`).
- A `Season` points to one default scoring config
  (`backend/app/db/models/season.py:21-26`). Each `Tournament` snapshots that choice
  through its own non-null `scoring_config_id` (`backend/app/db/models/tournament.py:28-43`).
  Runtime creation copies the season FK into the tournament
  (`backend/app/services/tournament_planning_service.py:486` and `:635`).
- Whether KO/BKO fields are enabled is a format rule, not a scoring-config setting:
  `TournamentTypeRule.knockout_mode` is one of `none`, `small`, `small_big`, or
  `main_ko` (`backend/app/db/models/tournament_type.py:37-80`). Thus the current
  effective policy is the pair `(TournamentTypeRule.knockout_mode,
  Tournament.scoring_config_id)`.
- Current domain defaults are KO 15 / BKO 60
  (`backend/app/domain/scoring.py:1-3`). Scoring v2 persists 15/60 plus MAIN KO
  30/100 (`backend/alembic/versions/5d6e7f8a9b0c_add_tournament_scoring_v2.py:30-40,
  217-239`). Earlier/historical databases may contain other rows (including the
  requested 30/60 combination), because values are data, not an enum.

## Readers and data flow

### Calculation, close, and correction

- `calculate_knockout_points()` is the single pure calculator. `small` uses the
  small value, `small_big` uses small plus big, and `main_ko` uses the dedicated
  MAIN values (`backend/app/services/result_rules.py:79-106`).
- Close preview and close load the tournament's snapshotted config and its type rule,
  then calculate and persist `knockout_points`
  (`backend/app/services/result_service.py:165-205,207-248,465-477`).
- CLOSED correction uses the same pure calculator with the same tournament FKs for
  preview and apply/recalculation
  (`backend/app/services/closed_tournament_correction_service.py:640-665,880-901`).
  It edits both counts independently (`:826-827`) and keeps correction transaction
  ownership in the service.
- Field availability is derived from `knockout_mode`: KO is allowed for `small`,
  `small_big`, and `main_ko`; BKO only for `small_big` and `main_ko`
  (`backend/app/services/result_field_policy.py:7-18`).

### Publication, statistics, history, API, and Telegram

- Publication reads persisted counts, uses type `knockout_mode` to decide whether to
  publish them, and includes both values in content-change hashing
  (`backend/app/services/tournament_publication_service.py:250-282,305-325,403-415`).
- Points rating sums persisted `knockout_points`; KO rating sums persisted KO/BKO
  counts (`backend/app/db/repositories/rating_repository.py:45-70,81-115`). Profile
  aggregation follows the same persisted-result approach
  (`backend/app/db/repositories/profile_repository.py:49-109`).
- Tournament history reads counts and calculated points from `tournament_results`
  (`backend/app/db/repositories/tournament_repository.py:372-435`), then maps them in
  `backend/app/services/user_statistics_service.py:243-288`.
- HTTP exposes persisted values through history, rating, profile, and privileged
  result schemas (`backend/app/api/v1/schemas/history.py:26-70`,
  `ratings.py:80-111`, `profile.py:42-75`, `admin_tournaments.py:43-89`, and
  `admin_tournament_close.py:94-95`). Public tournament details expose only
  `knockout_mode` (`backend/app/api/v1/schemas/tournaments.py:31,84`).
- Telegram result tables/cards consume DTO counts and `knockout_mode`
  (`backend/app/bot/telegram/formatters/results.py:193-196,420-424,515-536,
  571-598`). Publication formatting renders persisted KO/BKO occurrences
  (`backend/app/bot/telegram/formatters/publications.py:167-170`). History renders
  both columns (`backend/app/bot/telegram/formatters/statistics/history.py:93-95`).

The important preservation property is that historical UI and ratings do not
recompute old points from today's config. They read persisted counts and points.
Only explicit close/correction recalculates.

## What format and tournament layers can know today

`TournamentType` owns identity and presentation; `TournamentTypeRule` owns only the
KO mode. It cannot truthfully provide KO/BKO point values. A concrete `Tournament`
can: its `scoring_config_id` is an immutable selection made at creation. Therefore a
format-only screen can say which KO modes are enabled but cannot state 15/60 or
30/100 without a season/tournament context. A concrete-tournament screen can join
the tournament's scoring config and display exact values.

## Architecture options

### A. Tournament-level override with season fallback

Add nullable KO/BKO (and MAIN KO) override columns to `tournaments`; effective values
are override-or-snapshotted-scoring-config.

- **Pros:** smallest schema extension; historical tournaments keep current config;
  one-off tournament values are easy.
- **Risks:** two sources of truth and fallback branching in every calculator/view;
  partial overrides need strict all-or-none constraints; correction must resolve the
  same fallback forever.
- **Migration:** add nullable columns, leave old rows null, centralize one resolver,
  optionally materialize overrides only for new tournaments.
- **Cost:** medium. It solves instances well but not reusable format versioning.

### B. Values on TournamentType plus immutable Tournament snapshot

Store KO/BKO policy on each versioned `TournamentType`, and copy all effective values
to the concrete tournament at creation.

- **Pros:** format cards are fully truthful; format versions naturally express
  different KO economies; tournaments remain immutable for correction.
- **Risks:** duplicates scoring fields; MAIN KO requires a complete four-value model;
  changing a type must never mutate historical meaning; creation/import paths all
  need snapshot logic.
- **Migration:** add nullable/validated type fields and non-null/conditional snapshot
  fields on tournaments, derive existing tournament snapshots from their current
  scoring config plus mode, then make the resolver use only the snapshot.
- **Cost:** medium-high, but aligns best with the versioned-format model.

### C. Separate versioned scoring configuration

Keep `Tournament.scoring_config_id`, but split/configure place coefficients and KO
policy as explicitly versioned immutable records (or add a stable version identity
and lifecycle to the existing table). Formats may reference a default scoring
version; tournaments still snapshot the selected FK.

- **Pros:** one calculation source; no duplicated numeric columns; arbitrary 30/60
  and 30/100 versions are representable; strongest auditability.
- **Risks:** larger model/service/admin change; format default versus season default
  precedence must be explicit; existing configs currently lack a stable semantic
  code/version.
- **Migration:** assign stable identities to existing content-matched configs, add
  format defaults if wanted, retain every tournament FK, and prohibit mutation of
  referenced configs.
- **Cost:** high, but most extensible.

## History, correction, transactions, and four states

All options must preserve every existing `Tournament.scoring_config_id`, persisted
count, and persisted `knockout_points`. There should be no bulk recalculation during
schema migration. CLOSED correction must resolve values from the tournament snapshot,
recalculate inside its existing transaction, and update publication/reward side
effects only through current correction orchestration. Normal close likewise keeps
calculation and persistence in one service-owned transaction. Re-closing remains
forbidden by current status rules.

The four requested states are representable as immutable policy versions:

1. disabled: `knockout_mode=none`;
2. KO 30: `small`, small=30;
3. KO 30/BKO 60: `small_big`, small=30, big=60;
4. KO 30/BKO 100: `small_big`, small=30, big=100.

Schema constraints should be mode-aware: disabled policy has no active values;
`small` requires a positive small value and no active big value; `small_big` requires
both positive; `main_ko` requires both dedicated MAIN values. A uniqueness/content
identity rule is also needed if configs are version records. Current non-negative
checks alone do not guarantee these combinations.

## Recommendation

Choose **B** if KO/BKO values are genuinely part of a named tournament format's
rules, which current product wording strongly suggests. Keep immutable numeric
snapshots on `Tournament`; do not calculate historical values through the mutable
format row. This gives truthful format cards and safe CLOSED correction with a
moderate migration.

Choose **C** instead if place coefficients and KO values must continue to evolve as
one independently managed scoring package shared across many formats/seasons. Before
that choice, add an explicit stable config identity rather than relying on numeric PKs
or content heuristics. **A** is acceptable only for rare one-off overrides and is not
recommended as the primary long-term model because its fallback semantics remain
permanent architectural complexity.
