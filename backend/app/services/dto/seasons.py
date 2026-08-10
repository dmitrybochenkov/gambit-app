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
class SeasonCreationPreviewView:
    name: str
    starts_at: date
    scoring_config_id: int
    active_season_ends_at: date | None = None


@dataclass(frozen=True)
class SeasonTimelineView:
    completed_seasons: list[SeasonView]
    current_season: SeasonView | None
    future_seasons: list[SeasonView]
    suggested_start: date | None

    @property
    def nearest_future_season(self) -> SeasonView | None:
        return self.future_seasons[0] if self.future_seasons else None

    @property
    def last_future_season(self) -> SeasonView | None:
        return self.future_seasons[-1] if self.future_seasons else None

    @property
    def future_season(self) -> SeasonView | None:
        return self.nearest_future_season

    @property
    def has_future_season(self) -> bool:
        return self.future_season is not None


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


@dataclass(frozen=True)
class SeasonOptionView:
    id: int
    name: str
    starts_at: date
    ends_at: date | None
