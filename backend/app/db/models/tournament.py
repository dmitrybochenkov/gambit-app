from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import TournamentStatus, database_enum
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.tournament_type import TournamentType


class Tournament(TimestampMixin, Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tournament_type_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tournament_fund: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[TournamentStatus] = mapped_column(
        database_enum(TournamentStatus, "tournament_status"),
        default=TournamentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    tournament_type: Mapped[TournamentType] = relationship()

    __table_args__ = (
        UniqueConstraint("date", name="uq_tournaments_date"),
        CheckConstraint(
            "tournament_fund IS NULL OR tournament_fund >= 0",
            name="tournament_fund_nonnegative",
        ),
        CheckConstraint(
            "status != 'closed' OR tournament_fund IS NOT NULL",
            name="closed_has_tournament_fund",
        ),
    )
