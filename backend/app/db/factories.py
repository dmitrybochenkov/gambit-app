from app.common.normalization import normalize_display_name
from app.db.models.enums import UserRole, UserStatus
from app.db.models.user import User


def create_user(
    *,
    display_name: str,
    telegram_id: int | None = None,
    status: UserStatus = UserStatus.ACTIVE,
    role: UserRole = UserRole.PLAYER,
) -> User:
    return User(
        telegram_id=telegram_id,
        display_name=display_name,
        display_name_normalized=normalize_display_name(display_name) or display_name,
        status=status,
        role=role,
    )
