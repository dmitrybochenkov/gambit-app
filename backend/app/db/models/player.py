from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import PlayerRole, PlayerStatus, database_enum
from app.db.models.mixins import TimestampMixin


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name_normalized: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    status: Mapped[PlayerStatus] = mapped_column(
        database_enum(PlayerStatus, "player_status"),
        default=PlayerStatus.PENDING,
        nullable=False,
        index=True,
    )
    role: Mapped[PlayerRole] = mapped_column(
        database_enum(PlayerRole, "player_role"),
        default=PlayerRole.USER,
        nullable=False,
    )

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
    )
