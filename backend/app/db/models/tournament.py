from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
    from app.db.models.scoring_config import ScoringConfig
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
    scoring_config_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_configs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tournament_fund: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_open: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
        index=True,
    )
    status: Mapped[TournamentStatus] = mapped_column(
        database_enum(TournamentStatus, "tournament_status", length=9),
        default=TournamentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    tournament_type: Mapped[TournamentType] = relationship()
    scoring_config: Mapped[ScoringConfig] = relationship()

    __table_args__ = (
        UniqueConstraint("date", name="uq_tournaments_date"),
        CheckConstraint(
            "tournament_fund IS NULL OR (tournament_fund > 0 AND tournament_fund % 10 = 0)",
            name="tournament_fund",
        ),
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="tournaments_status_values",
        ),
    )
