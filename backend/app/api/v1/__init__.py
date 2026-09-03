from fastapi import APIRouter

from app.api.v1 import hall_of_fame, history, me, profile, ratings, rewards, tournaments

router = APIRouter(prefix="/api/v1")
router.include_router(hall_of_fame.router)
router.include_router(history.router)
router.include_router(me.router)
router.include_router(profile.router)
router.include_router(ratings.router)
router.include_router(rewards.router)
router.include_router(tournaments.router)

__all__ = ["router"]
