from datetime import datetime

from app.common.normalization import normalize_display_name
from app.db.models.enums import PlayerRole, PlayerStatus
from app.db.models.player import Player


def create_player(
    *,
    telegram_id: int,
    display_name: str,
    status: PlayerStatus = PlayerStatus.PENDING,
    role: PlayerRole = PlayerRole.USER,
    approved_at: datetime | None = None,
    approved_by_admin_id: int | None = None,
) -> Player:
    return Player(
        telegram_id=telegram_id,
        display_name=display_name,
        display_name_normalized=normalize_display_name(display_name) or display_name,
        status=status,
        role=role,
        approved_at=approved_at,
        approved_by_admin_id=approved_by_admin_id,
    )
