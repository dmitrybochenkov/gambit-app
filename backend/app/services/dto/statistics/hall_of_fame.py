from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HallOfFameSeasonView:
    season_id: int
    season_name: str
    starts_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None
    champion_photo_file_id: str | None = None
    knockout_photo_file_id: str | None = None
    ends_at: date | None = None
