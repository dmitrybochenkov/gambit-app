from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class SeasonLifecycleStateView(StrEnum):
    SCHEDULED = "scheduled"
    CURRENT = "current"
    COMPLETED = "completed"


@dataclass(frozen=True)
class SeasonView:
    id: int
    name: str
    starts_at: date
    ends_at: date | None
    lifecycle_state: SeasonLifecycleStateView
    scoring_config_id: int


@dataclass(frozen=True)
class SeasonProposalView:
    id: int
    name: str
    starts_at: date
    scoring_config_id: int
    active_season_ends_at: date | None = None


@dataclass(frozen=True)
class ScoringConfigView:
    id: int
    place_1_coefficient: Decimal
    place_2_coefficient: Decimal
    place_3_coefficient: Decimal
    place_4_coefficient: Decimal
    place_5_coefficient: Decimal
    knockout_small_points: int
    knockout_big_points: int
