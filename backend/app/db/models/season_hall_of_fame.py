from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.season import Season
    from app.db.models.user import User


class SeasonHallOfFame(TimestampMixin, Base):
    __tablename__ = "season_hall_of_fame"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="RESTRICT"),
        nullable=False,
    )
    champion_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    knockout_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    champion_photo_file_id: Mapped[str | None] = mapped_column(nullable=True)
    champion_photo_file_unique_id: Mapped[str | None] = mapped_column(nullable=True)
    knockout_photo_file_id: Mapped[str | None] = mapped_column(nullable=True)
    knockout_photo_file_unique_id: Mapped[str | None] = mapped_column(nullable=True)
    updated_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    season: Mapped[Season] = relationship()
    champion_player: Mapped[User | None] = relationship(foreign_keys=[champion_player_id])
    knockout_player: Mapped[User | None] = relationship(foreign_keys=[knockout_player_id])
    updated_by_user: Mapped[User] = relationship(foreign_keys=[updated_by_user_id])

    __table_args__ = (
        UniqueConstraint(
            "season_id",
            name="uq_season_hall_of_fame_season_id",
        ),
    )
