from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class TournamentResultDraft(TimestampMixin, Base):
    __tablename__ = "tournament_result_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    big_knockouts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            name="uq_tournament_result_drafts_tournament_player",
        ),
        CheckConstraint("place IS NULL OR place > 0", name="place_positive"),
        CheckConstraint("knockouts_count >= 0", name="knockouts_count_nonnegative"),
        CheckConstraint(
            "big_knockouts_count >= 0",
            name="big_knockouts_count_nonnegative",
        ),
        CheckConstraint("bonus_points >= 0", name="bonus_points_nonnegative"),
    )
