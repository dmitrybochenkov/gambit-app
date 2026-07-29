from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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
    points_pool: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    results_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    results_submitted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
            "points_pool IS NULL OR points_pool >= 0",
            name="points_pool_nonnegative",
        ),
        CheckConstraint(
            "status != 'closed' OR points_pool IS NOT NULL",
            name="closed_has_points_pool",
        ),
    )
