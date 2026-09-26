from datetime import date

from app.db.repositories.player_reward_repository import (
    PlayerRewardRepository,
    PlayerRewardSourceRow,
)
from app.services.dto.rewards import PlayerRewardView


async def list_active_reward_views(
    reward_repository: PlayerRewardRepository,
    *,
    player_id: int,
    business_date: date,
) -> tuple[PlayerRewardView, ...]:
    rows = await reward_repository.list_active_for_player(
        player_id=player_id,
        business_date=business_date,
    )
    return tuple(reward_view(row) for row in rows)


def reward_view(row: PlayerRewardSourceRow) -> PlayerRewardView:
    reward_type = row.reward.reward_type
    return PlayerRewardView(
        reward_id=row.reward.id,
        player_id=row.reward.player_id,
        chips_amount=row.reward.chips_amount,
        source_place=row.reward.source_place,
        source_tournament_id=row.reward.source_tournament_id,
        source_tournament_date=row.tournament.date,
        source_tournament_name=row.tournament_type.name,
        valid_through=row.reward.valid_through,
        issued_at=row.reward.issued_at,
        reward_type=reward_type.value if hasattr(reward_type, "value") else str(reward_type),
        status="active",
    )
