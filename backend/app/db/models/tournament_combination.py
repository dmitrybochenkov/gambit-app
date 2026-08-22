from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import TournamentCombinationType
from app.db.models.mixins import utc_now


class TournamentCombination(Base):
    __tablename__ = "tournament_combinations"

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
    combination_type: Mapped[TournamentCombinationType] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            "combination_type",
            name="uq_tournament_combinations_tournament_player_type",
        ),
        CheckConstraint(
            "combination_type IN ('four_of_a_kind', 'straight_flush', 'royal_flush')",
            name="ck_tournament_combinations_type",
        ),
    )
