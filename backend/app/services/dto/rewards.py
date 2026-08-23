from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PlayerRewardView:
    reward_id: int
    player_id: int
    chips_amount: int
    source_place: int
    source_tournament_id: int
    source_tournament_date: date
    source_tournament_name: str
    valid_through: date


@dataclass(frozen=True)
class PlayerRewardNotificationView:
    reward_id: int
    player_id: int
    telegram_id: int | None
    chips_amount: int
    source_place: int
    source_tournament_id: int
    source_tournament_date: date
    source_tournament_name: str
    valid_through: date
