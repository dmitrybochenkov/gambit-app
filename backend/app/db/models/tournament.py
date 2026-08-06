from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
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
    tournament_fund: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
            "tournament_fund IS NULL OR (tournament_fund > 0 AND tournament_fund % 10 = 0)",
            name="tournament_fund",
        ),
        CheckConstraint(
            "(status = 'closed' AND tournament_fund IS NOT NULL) "
            "OR (status != 'closed' AND tournament_fund IS NULL)",
            name="tournament_fund_status",
        ),
    )
