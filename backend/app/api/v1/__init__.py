from fastapi import APIRouter

from app.api.v1 import me, tournaments

router = APIRouter(prefix="/api/v1")
router.include_router(me.router)
router.include_router(tournaments.router)

__all__ = ["router"]
