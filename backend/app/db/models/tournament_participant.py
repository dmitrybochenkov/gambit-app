from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import (
    TournamentParticipantResultStatus,
    TournamentParticipantSource,
    database_enum,
)
from app.db.models.mixins import TimestampMixin, utc_now


class TournamentParticipant(TimestampMixin, Base):
    __tablename__ = "tournament_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[TournamentParticipantSource] = mapped_column(
        database_enum(TournamentParticipantSource, "tournament_participant_source"),
        nullable=False,
        index=True,
    )
    result_status: Mapped[TournamentParticipantResultStatus] = mapped_column(
        String(20),
        default=TournamentParticipantResultStatus.ACTIVE,
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

    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "user_id",
            name="uq_tournament_participants_tournament_user",
        ),
    )
