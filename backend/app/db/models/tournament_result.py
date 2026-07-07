from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class TournamentResult(TimestampMixin, Base):
    __tablename__ = "tournament_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    boss_knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
            "boss_knockouts_count >= 0",
            name="boss_knockouts_count_nonnegative",
        ),
        CheckConstraint("tournament_points >= 0", name="tournament_points_nonnegative"),
        CheckConstraint("knockout_points >= 0", name="knockout_points_nonnegative"),
    )

    @property
    def total_points(self) -> Decimal:
        return self.tournament_points + self.knockout_points + self.bonus_points
