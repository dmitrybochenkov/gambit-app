from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import PlayerRole, PlayerStatus, database_enum
from app.db.models.mixins import TimestampMixin


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name_normalized: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nickname_normalized: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
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
    __table_args__ = (
        CheckConstraint(
            "full_name IS NOT NULL OR nickname IS NOT NULL",
            name="identity_present",
        ),
    )

    @property
    def display_name(self) -> str:
        if self.full_name and self.nickname:
            return f"{self.full_name} ({self.nickname})"
        return self.nickname or self.full_name or ""
