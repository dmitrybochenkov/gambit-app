from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.dto.rewards import PlayerRewardView
from app.services.dto.statistics.titles import PlayerTitleKind, PlayerTitleOccurrenceView

PlayerProfileHonourView = PlayerTitleOccurrenceView
PlayerProfileHonourKind = PlayerTitleKind


@dataclass(frozen=True)
class PlayerProfileView:
    display_name: str
    total_points: Decimal
    knockouts_count: int
    big_knockouts_count: int
    tournaments_count: int
    first_places_count: int
    second_places_count: int
    third_places_count: int
    fourth_places_count: int
    fifth_places_count: int
    rating_position: int | None
    rating_participants_count: int
    prize_percent: int | None
    honours: tuple[PlayerProfileHonourView, ...] = ()
    active_rewards: tuple[PlayerRewardView, ...] = ()

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class PlayerPrizeTournamentView:
    tournament_id: int
    date: date
    display_name: str
    place: int
