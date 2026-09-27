from pydantic import BaseModel, ConfigDict

from app.db.models.enums import UserGender
from app.services.dto.users import UserView


class AdminUserResponse(BaseModel):
    id: int
    display_name: str
    status: str
    role: str
    gender: UserGender | None
    telegram_linked: bool

    @classmethod
    def from_view(cls, view: UserView) -> "AdminUserResponse":
        return cls(
            id=view.id,
            display_name=view.display_name,
            status=view.status.value,
            role=view.role.value,
            gender=view.gender,
            telegram_linked=view.telegram_id is not None,
        )


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]


class AdminUserRenameCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    expected_old_display_name: str


class AdminUserGenderCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gender: UserGender | None
