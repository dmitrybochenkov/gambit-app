from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PlayerProfileView:
    display_name: str
    total_points: Decimal
    knockout_points: Decimal
    knockouts_count: int
    big_knockouts_count: int
    tournaments_count: int
    first_places_count: int
    second_places_count: int
    third_places_count: int
    fourth_places_count: int
    fifth_places_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count
