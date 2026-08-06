from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import TournamentResultSource
from app.db.models.mixins import TimestampMixin, utc_now


class TournamentResult(TimestampMixin, Base):
    __tablename__ = "tournament_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source: Mapped[TournamentResultSource] = mapped_column(
        String(20),
        default=TournamentResultSource.WALK_IN_EXISTING,
        nullable=False,
        index=True,
    )
    checked_in_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    big_knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tournament_points: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0"),
        nullable=False,
    )
    knockout_points: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0"),
        nullable=False,
    )
    bonus_points: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            name="uq_tournament_results_tournament_player",
        ),
        CheckConstraint("place IS NULL OR place > 0", name="place_positive"),
        CheckConstraint("knockouts_count >= 0", name="knockouts_count_nonnegative"),
        CheckConstraint(
            "big_knockouts_count >= 0",
            name="big_knockouts_count_nonnegative",
        ),
        CheckConstraint("tournament_points >= 0", name="tournament_points_nonnegative"),
        CheckConstraint("knockout_points >= 0", name="knockout_points_nonnegative"),
        CheckConstraint("bonus_points >= 0", name="bonus_points_nonnegative"),
    )

    @property
    def total_points(self) -> Decimal:
        return self.tournament_points + self.knockout_points + self.bonus_points
