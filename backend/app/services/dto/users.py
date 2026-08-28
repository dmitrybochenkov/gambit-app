from dataclasses import dataclass
from enum import StrEnum

from app.db.models.enums import UserGender, UserRole, UserStatus


class UserStartStatusView(StrEnum):
    REGISTERED = "registered"
    PENDING_REGISTRATION = "pending_registration"
    BLOCKED = "blocked"
    NEEDS_REGISTRATION = "needs_registration"


@dataclass(frozen=True)
class UserView:
    id: int
    telegram_id: int | None
    display_name: str
    status: UserStatus
    role: UserRole
    gender: UserGender | None = None

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def is_blocked(self) -> bool:
        return self.status == UserStatus.BLOCKED

    @property
    def is_admin(self) -> bool:
        return self.role in {UserRole.ADMIN, UserRole.SUPERADMIN}


@dataclass(frozen=True)
class UserStartView:
    status: UserStartStatusView
    user: UserView | None = None

    def __post_init__(self) -> None:
        user_required = self.status in {
            UserStartStatusView.REGISTERED,
            UserStartStatusView.BLOCKED,
        }
        if user_required and self.user is None:
            raise ValueError(f"{self.status.value} start view requires user")
        if not user_required and self.user is not None:
            raise ValueError(f"{self.status.value} start view cannot include user")

    @classmethod
    def registered(cls, user: UserView) -> "UserStartView":
        return cls(status=UserStartStatusView.REGISTERED, user=user)

    @classmethod
    def blocked(cls, user: UserView) -> "UserStartView":
        return cls(status=UserStartStatusView.BLOCKED, user=user)

    @classmethod
    def pending_registration(cls) -> "UserStartView":
        return cls(status=UserStartStatusView.PENDING_REGISTRATION)

    @classmethod
    def needs_registration(cls) -> "UserStartView":
        return cls(status=UserStartStatusView.NEEDS_REGISTRATION)

    @property
    def required_user(self) -> UserView:
        if self.user is None:
            raise ValueError(f"{self.status.value} start view has no user")
        return self.user
