from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.tournaments import public_tournament_type_name
from app.services.dto.statistics.history import (
    HistoricalTournamentResultView,
    PlayerHistoryTournamentView,
)


class HistoryTournamentTypeResponse(BaseModel):
    code: str
    name: str


class PlayerHistoryItemResponse(BaseModel):
    tournament_id: int
    date: date
    type: HistoryTournamentTypeResponse
    place: int | None
    tournament_points: Decimal
    knockout_points: Decimal
    bonus_points: int
    total_points: Decimal
    knockouts_count: int
    big_knockouts_count: int

    @classmethod
    def from_view(cls, view: PlayerHistoryTournamentView) -> "PlayerHistoryItemResponse":
        return cls(
            tournament_id=view.tournament_id,
            date=view.date,
            type=HistoryTournamentTypeResponse(
                code=view.tournament_type_code,
                name=public_tournament_type_name(view.tournament_type_name),
            ),
            place=view.place,
            tournament_points=view.tournament_points,
            knockout_points=view.knockout_points,
            bonus_points=view.bonus_points,
            total_points=view.total_points,
            knockouts_count=view.knockouts_count,
            big_knockouts_count=view.big_knockouts_count,
        )


class PlayerHistoryListResponse(BaseModel):
    items: list[PlayerHistoryItemResponse]

    model_config = ConfigDict(json_schema_extra={"description": "Current player's history."})

    @classmethod
    def from_views(cls, views: list[PlayerHistoryTournamentView]) -> "PlayerHistoryListResponse":
        return cls(items=[PlayerHistoryItemResponse.from_view(view) for view in views])


class HistoricalTournamentPlayerResultResponse(BaseModel):
    player_id: int
    display_name: str
    place: int | None
    tournament_points: Decimal
    knockout_points: Decimal
    bonus_points: int
    total_points: Decimal
    knockouts_count: int
    big_knockouts_count: int


class PlayerHistoryDetailResponse(BaseModel):
    tournament_id: int
    date: date
    type: HistoryTournamentTypeResponse
    my_result: HistoricalTournamentPlayerResultResponse

    model_config = ConfigDict(
        json_schema_extra={"description": "Current player's historical tournament result."}
    )

    @classmethod
    def from_view(
        cls,
        *,
        player_id: int,
        view: HistoricalTournamentResultView,
    ) -> "PlayerHistoryDetailResponse":
        row = next(row for row in view.rows if row.player_id == player_id)
        return cls(
            tournament_id=view.tournament.id,
            date=view.tournament.date,
            type=HistoryTournamentTypeResponse(
                code=view.tournament.tournament_type_code or "",
                name=public_tournament_type_name(
                    view.tournament.tournament_type_name or view.tournament.display_name
                ),
            ),
            my_result=HistoricalTournamentPlayerResultResponse(
                player_id=row.player_id,
                display_name=row.display_name,
                place=row.place,
                tournament_points=row.tournament_points,
                knockout_points=row.knockout_points,
                bonus_points=row.bonus_points,
                total_points=row.total_points,
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
            ),
        )
