from datetime import date

from pydantic import BaseModel

from app.services.dto.seasons import (
    SeasonCreationPreviewView,
    SeasonFutureDeletePreviewView,
    SeasonTimelineView,
    SeasonView,
)


class SeasonResponse(BaseModel):
    id: int
    name: str
    starts_at: date
    ends_at: date | None
    lifecycle_state: str
    scoring_config_id: int

    @classmethod
    def from_view(cls, view: SeasonView) -> "SeasonResponse":
        return cls(**view.__dict__)


class SeasonTimelineResponse(BaseModel):
    completed_seasons: list[SeasonResponse]
    current_season: SeasonResponse | None
    future_season: SeasonResponse | None
    suggested_start: date | None
    can_create_next_season: bool
    can_delete_future_season: bool

    @classmethod
    def from_view(cls, view: SeasonTimelineView) -> "SeasonTimelineResponse":
        return cls(
            completed_seasons=[SeasonResponse.from_view(item) for item in view.completed_seasons],
            current_season=(
                SeasonResponse.from_view(view.current_season)
                if view.current_season is not None
                else None
            ),
            future_season=(
                SeasonResponse.from_view(view.future_season)
                if view.future_season is not None
                else None
            ),
            suggested_start=view.suggested_start,
            can_create_next_season=view.can_create_next_season,
            can_delete_future_season=view.can_delete_future_season,
        )


class SeasonCreateNextCommand(BaseModel):
    name: str
    starts_at: date


class SeasonCreationPreviewResponse(BaseModel):
    name: str
    starts_at: date
    scoring_config_id: int
    active_season_ends_at: date | None

    @classmethod
    def from_view(cls, view: SeasonCreationPreviewView) -> "SeasonCreationPreviewResponse":
        return cls(**view.__dict__)


class SeasonFutureDeleteCommand(BaseModel):
    expected_season_id: int


class SeasonFutureDeletePreviewResponse(BaseModel):
    future_season: SeasonResponse
    previous_season: SeasonResponse

    @classmethod
    def from_view(
        cls,
        view: SeasonFutureDeletePreviewView,
    ) -> "SeasonFutureDeletePreviewResponse":
        return cls(
            future_season=SeasonResponse.from_view(view.future_season),
            previous_season=SeasonResponse.from_view(view.previous_season),
        )
