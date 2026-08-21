from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PlayerProfileHonourView:
    season_name: str
    season_starts_at: date
    kind: str


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

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class PlayerPrizeTournamentView:
    tournament_id: int
    date: date
    display_name: str
    place: int
