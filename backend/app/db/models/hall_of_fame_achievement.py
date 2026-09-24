from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import HallOfFameAchievementKind, database_enum
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.season import Season
    from app.db.models.user import User


class HallOfFameAchievement(TimestampMixin, Base):
    __tablename__ = "hall_of_fame_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[HallOfFameAchievementKind] = mapped_column(
        database_enum(HallOfFameAchievementKind, "hall_of_fame_achievement_kind", length=16),
        nullable=False,
        index=True,
    )
    awarded_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    season: Mapped[Season] = relationship()
    player: Mapped[User] = relationship()

    __table_args__ = (
        CheckConstraint(
            "kind IN ('rating_winner', 'ko_rating_winner', 'grand_season', "
            "'grand_month', 'grand_knockout')",
            name="hall_of_fame_achievements_kind_values",
        ),
        Index(
            "uq_hall_of_fame_achievements_singleton_kind",
            "season_id",
            "kind",
            unique=True,
            sqlite_where=text("kind IN ('rating_winner', 'ko_rating_winner', 'grand_season')"),
            postgresql_where=text("kind IN ('rating_winner', 'ko_rating_winner', 'grand_season')"),
        ),
    )
