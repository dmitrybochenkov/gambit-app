from datetime import date

from pydantic import BaseModel, ConfigDict

from app.services.dto.statistics.hall_of_fame import HallOfFameSeasonView


class HallOfFamePlayerResponse(BaseModel):
    id: int
    display_name: str


class HallOfFameSeasonResponse(BaseModel):
    season: "HallOfFameSeasonInfoResponse"
    champion: HallOfFamePlayerResponse | None
    knockout_leader: HallOfFamePlayerResponse | None

    @classmethod
    def from_view(cls, view: HallOfFameSeasonView) -> "HallOfFameSeasonResponse":
        if view.ends_at is None:
            raise ValueError("Hall of Fame season must have ends_at")
        return cls(
            season=HallOfFameSeasonInfoResponse(
                id=view.season_id,
                name=view.season_name,
                starts_at=view.starts_at,
                ends_at=view.ends_at,
            ),
            champion=_player(view.champion_player_id, view.champion_display_name),
            knockout_leader=_player(
                view.knockout_leader_player_id,
                view.knockout_leader_display_name,
            ),
        )


class HallOfFameSeasonInfoResponse(BaseModel):
    id: int
    name: str
    starts_at: date
    ends_at: date


class HallOfFameResponse(BaseModel):
    seasons: list[HallOfFameSeasonResponse]

    model_config = ConfigDict(json_schema_extra={"description": "Manual Hall of Fame."})

    @classmethod
    def from_views(cls, views: list[HallOfFameSeasonView]) -> "HallOfFameResponse":
        return cls(seasons=[HallOfFameSeasonResponse.from_view(view) for view in views])


def _player(player_id: int | None, display_name: str | None) -> HallOfFamePlayerResponse | None:
    if player_id is None or display_name is None:
        return None
    return HallOfFamePlayerResponse(id=player_id, display_name=display_name)
