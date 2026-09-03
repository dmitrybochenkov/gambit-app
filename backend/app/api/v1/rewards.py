from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.rewards import PlayerRewardListResponse
from app.services.player_reward_service import player_reward_service

router = APIRouter(tags=["webapp"])


@router.get("/me/rewards", response_model=PlayerRewardListResponse)
async def get_my_rewards(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerRewardListResponse:
    rewards = await player_reward_service.list_current_active_rewards_for_player(
        player_id=actor.user_id,
    )
    return PlayerRewardListResponse.from_views(rewards)
