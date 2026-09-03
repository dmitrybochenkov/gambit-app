from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import AuthenticatedActor, current_actor

router = APIRouter(tags=["webapp"])


class MeResponse(BaseModel):
    id: int
    display_name: str
    role: str
    gender: str | None
    status: str

    model_config = ConfigDict(json_schema_extra={"description": "Current WebApp user."})


@router.get("/me", response_model=MeResponse)
async def get_me(actor: Annotated[AuthenticatedActor, Depends(current_actor)]) -> MeResponse:
    return MeResponse(
        id=actor.user_id,
        display_name=actor.display_name,
        role=actor.role,
        gender=actor.gender,
        status="active",
    )
