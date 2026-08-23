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


@dataclass(frozen=True)
class PlayerRewardCorrectionNotificationView:
    player_id: int
    telegram_id: int | None
    source_tournament_id: int
    source_tournament_date: date
    source_tournament_name: str
    valid_through: date
    old_chips_amount: int | None = None
    new_chips_amount: int | None = None


@dataclass(frozen=True)
class PlayerRewardCorrectionChangeView:
    player_id: int
    display_name: str
    old_chips_amount: int | None
    new_chips_amount: int | None
    used: bool = False


@dataclass(frozen=True)
class PrizeStackBonusSourceResultView:
    player_id: int
    display_name: str
    telegram_id: int | None
    place: int | None


@dataclass(frozen=True)
class PlayerRewardCorrectionResultView:
    reward_changes: tuple[PlayerRewardCorrectionChangeView, ...]
    used_reward_warnings: tuple[PlayerRewardCorrectionChangeView, ...]
    player_notifications: tuple[PlayerRewardCorrectionNotificationView, ...]


@dataclass(frozen=True)
class PlayerRewardExpirationReminderItemView:
    reward_id: int
    chips_amount: int
    valid_through: date


@dataclass(frozen=True)
class PlayerRewardExpirationReminderGroupView:
    player_id: int
    telegram_id: int
    rewards: tuple[PlayerRewardExpirationReminderItemView, ...]
