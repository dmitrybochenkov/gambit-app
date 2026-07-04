from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import RegistrationStatus, database_enum
from app.db.models.mixins import utc_now


class TournamentRegistration(Base):
    __tablename__ = "tournament_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RegistrationStatus] = mapped_column(
        database_enum(RegistrationStatus, "registration_status"),
        default=RegistrationStatus.REGISTERED,
        nullable=False,
        index=True,
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            name="uq_tournament_registrations_tournament_player",
        ),
        CheckConstraint(
            """
            (status = 'registered' AND cancelled_at IS NULL)
            OR (status = 'cancelled' AND cancelled_at IS NOT NULL)
            """,
            name="cancellation_state",
        ),
    )
