from dataclasses import dataclass
from datetime import date

from app.db.models.enums import HallOfFameAchievementKind


@dataclass(frozen=True)
class HallOfFameAchievementView:
    id: int
    player_id: int
    display_name: str
    kind: HallOfFameAchievementKind
    awarded_at: date


@dataclass(frozen=True)
class HallOfFamePhotoView:
    id: int
    telegram_file_id: str
    position: int


@dataclass(frozen=True)
class HallOfFameSeasonView:
    season_id: int
    season_name: str
    starts_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None
    ends_at: date | None = None
    photos: tuple[HallOfFamePhotoView, ...] = ()
    achievements: tuple[HallOfFameAchievementView, ...] = ()
