from fastapi import APIRouter

from app.api.v1 import me

router = APIRouter(prefix="/api/v1")
router.include_router(me.router)

__all__ = ["router"]
