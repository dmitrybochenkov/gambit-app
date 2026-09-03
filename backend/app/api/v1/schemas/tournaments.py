from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.services.dto.tournaments import PlayerTournamentView


class TournamentTypeResponse(BaseModel):
    code: str | None
    name: str


class TournamentRebuyResponse(BaseModel):
    fee: int
    stack: int


class TournamentEconomyResponse(BaseModel):
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: list[TournamentRebuyResponse]


class TournamentRulesResponse(BaseModel):
    points_multiplier: Decimal
    prize_place_multiplier: Decimal
    prize_place_multiplier_places: str | None
    knockout_mode: str
    supports_bonus_points: bool


class PlayerTournamentResponse(BaseModel):
    id: int
    date: date
    type: TournamentTypeResponse
    description: str | None
    registration_open: bool
    my_registration_status: str
    is_registered: bool
    can_register: bool
    can_cancel_registration: bool
    economy: TournamentEconomyResponse | None = None
    rules: TournamentRulesResponse | None = None

    model_config = ConfigDict(json_schema_extra={"description": "Player-facing tournament."})

    @classmethod
    def from_view(cls, view: PlayerTournamentView) -> "PlayerTournamentResponse":
        return cls(
            id=view.id,
            date=view.date,
            type=TournamentTypeResponse(
                code=view.tournament_type_code,
                name=public_tournament_type_name(view.tournament_type_name),
            ),
            description=view.description,
            registration_open=view.registration_open,
            my_registration_status=view.my_registration_status,
            is_registered=view.is_registered,
            can_register=view.can_register,
            can_cancel_registration=view.can_cancel_registration,
            economy=(
                TournamentEconomyResponse(
                    entry_fee=view.economy.entry_fee,
                    entry_stack=view.economy.entry_stack,
                    addon_fee=view.economy.addon_fee,
                    addon_stack=view.economy.addon_stack,
                    rebuys=[
                        TournamentRebuyResponse(fee=rebuy.fee, stack=rebuy.stack)
                        for rebuy in view.economy.rebuys
                    ],
                )
                if view.economy is not None
                else None
            ),
            rules=(
                TournamentRulesResponse(
                    points_multiplier=view.rules.points_multiplier,
                    prize_place_multiplier=view.rules.prize_place_multiplier,
                    prize_place_multiplier_places=view.rules.prize_place_multiplier_places,
                    knockout_mode=view.rules.knockout_mode,
                    supports_bonus_points=view.rules.supports_bonus_points,
                )
                if view.rules is not None
                else None
            ),
        )


class PlayerTournamentListResponse(BaseModel):
    items: list[PlayerTournamentResponse]


def public_tournament_type_name(name: str) -> str:
    return name.removesuffix(" v2").removesuffix(" V2")
