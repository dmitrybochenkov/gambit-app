from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.tournaments import public_tournament_type_name
from app.services.dto.rewards import PlayerRewardView


class PlayerRewardResponse(BaseModel):
    id: int
    reward_type: str
    chips_amount: int
    source_tournament_id: int
    source_tournament_date: date
    source_tournament_name: str
    source_place: int
    issued_at: datetime | None
    valid_through: date
    status: str

    @classmethod
    def from_view(cls, view: PlayerRewardView) -> "PlayerRewardResponse":
        return cls(
            id=view.reward_id,
            reward_type=view.reward_type,
            chips_amount=view.chips_amount,
            source_tournament_id=view.source_tournament_id,
            source_tournament_date=view.source_tournament_date,
            source_tournament_name=public_tournament_type_name(view.source_tournament_name),
            source_place=view.source_place,
            issued_at=view.issued_at,
            valid_through=view.valid_through,
            status=view.status,
        )


class PlayerRewardListResponse(BaseModel):
    items: list[PlayerRewardResponse]

    model_config = ConfigDict(json_schema_extra={"description": "Current player's rewards."})

    @classmethod
    def from_views(cls, views: tuple[PlayerRewardView, ...]) -> "PlayerRewardListResponse":
        return cls(items=[PlayerRewardResponse.from_view(view) for view in views])
