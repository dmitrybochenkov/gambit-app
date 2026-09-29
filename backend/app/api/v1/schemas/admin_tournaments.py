from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import TournamentCombinationType
from app.services.dto.results import TournamentCombinationsView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.result_fields import ResultField

from .media import PhotoDescriptorResponse


class AdminTournamentResponse(BaseModel):
    id: int
    date: date
    tournament_type_id: int
    tournament_type_code: str | None
    tournament_type_name: str | None
    registration_open: bool

    @classmethod
    def from_view(cls, view: TournamentView) -> "AdminTournamentResponse":
        return cls(
            id=view.id,
            date=view.date,
            tournament_type_id=view.tournament_type_id,
            tournament_type_code=view.tournament_type_code,
            tournament_type_name=view.tournament_type_name,
            registration_open=view.registration_open,
        )


class AdminTournamentListResponse(BaseModel):
    items: list[AdminTournamentResponse]


class AdminTournamentResultPlayerResponse(BaseModel):
    result_id: int | None
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int
    tournament_points: Decimal
    knockout_points: Decimal
    total_points: Decimal


class AdminTournamentResultsResponse(BaseModel):
    tournament: AdminTournamentResponse
    tournament_fund: int | None
    knockout_mode: str
    supports_bonus_points: bool
    photo_count: int
    photos: list[PhotoDescriptorResponse]
    players: list[AdminTournamentResultPlayerResponse]

    model_config = ConfigDict(
        json_schema_extra={"description": "Authorized tournament result-entry state."}
    )

    @classmethod
    def from_view(cls, view: TournamentResultsView) -> "AdminTournamentResultsResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            tournament_fund=view.tournament_fund,
            knockout_mode=view.knockout_mode,
            supports_bonus_points=view.supports_bonus_points,
            photo_count=view.photo_count,
            photos=[
                PhotoDescriptorResponse.tournament_photo(
                    photo_id=photo.id,
                    position=photo.position,
                )
                for photo in view.photos
            ],
            players=[
                AdminTournamentResultPlayerResponse(
                    result_id=player.result_id,
                    player_id=player.player_id,
                    display_name=player.display_name,
                    place=player.place,
                    knockouts_count=player.knockouts_count,
                    big_knockouts_count=player.big_knockouts_count,
                    bonus_points=player.bonus_points,
                    tournament_points=player.tournament_points,
                    knockout_points=player.knockout_points,
                    total_points=player.total_points,
                )
                for player in view.players
            ],
        )


class AdminResultFieldUpdateRequest(BaseModel):
    field: ResultField
    value: int


class AdminCombinationCreateRequest(BaseModel):
    player_id: int
    combination_type: TournamentCombinationType
    rank: str | None = None


class AdminCombinationResponse(BaseModel):
    id: int
    tournament_id: int
    player_id: int
    display_name: str
    combination_type: str
    rank: str | None


class AdminCombinationPlayerResponse(BaseModel):
    player_id: int
    display_name: str


class AdminTournamentCombinationsResponse(BaseModel):
    tournament: AdminTournamentResponse
    combinations: list[AdminCombinationResponse]
    players: list[AdminCombinationPlayerResponse]

    @classmethod
    def from_view(
        cls,
        view: TournamentCombinationsView,
    ) -> "AdminTournamentCombinationsResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            combinations=[
                AdminCombinationResponse(
                    id=item.id,
                    tournament_id=item.tournament_id,
                    player_id=item.player_id,
                    display_name=item.display_name,
                    combination_type=item.combination_type,
                    rank=item.rank,
                )
                for item in view.combinations
            ],
            players=[
                AdminCombinationPlayerResponse(
                    player_id=item.player_id,
                    display_name=item.display_name,
                )
                for item in view.players
            ],
        )
