from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import utc_now


class HallOfFamePhoto(Base):
    __tablename__ = "hall_of_fame_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "telegram_file_unique_id",
            name="uq_hall_of_fame_photos_season_unique_file",
        ),
        CheckConstraint("position >= 0", name="ck_hall_of_fame_photos_position_nonnegative"),
    )
