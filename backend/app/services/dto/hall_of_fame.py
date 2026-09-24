from dataclasses import dataclass
from datetime import date

from app.db.models.enums import HallOfFameAchievementKind
from app.services.dto.users import UserView


@dataclass(frozen=True)
class HallOfFameAchievementManagementView:
    id: int
    player: UserView
    kind: HallOfFameAchievementKind
    awarded_at: date


@dataclass(frozen=True)
class HallOfFameSeasonListItemView:
    season_id: int
    season_name: str
    starts_at: date
    ends_at: date | None


@dataclass(frozen=True)
class HallOfFamePhotoView:
    id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    position: int


@dataclass(frozen=True)
class HallOfFameEntryView:
    season_id: int
    season_name: str
    starts_at: date
    ends_at: date | None
    champion: UserView | None
    knockout_leader: UserView | None
    photos: tuple[HallOfFamePhotoView, ...] = ()
    achievements: tuple[HallOfFameAchievementManagementView, ...] = ()


@dataclass(frozen=True)
class HallOfFameCandidateView:
    user: UserView
    score: int
    reason: str
