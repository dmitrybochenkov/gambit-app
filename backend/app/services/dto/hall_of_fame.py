from dataclasses import dataclass
from datetime import date

from app.services.dto.users import UserView


@dataclass(frozen=True)
class HallOfFameSeasonListItemView:
    season_id: int
    season_name: str
    starts_at: date
    ends_at: date


@dataclass(frozen=True)
class HallOfFameEntryView:
    season_id: int
    season_name: str
    starts_at: date
    ends_at: date
    champion: UserView | None
    knockout_leader: UserView | None


@dataclass(frozen=True)
class HallOfFameCandidateView:
    user: UserView
    score: int
    reason: str
