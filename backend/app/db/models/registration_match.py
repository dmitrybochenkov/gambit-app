from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import RegistrationMatchStatus, database_enum
from app.db.models.mixins import TimestampMixin


class RegistrationMatch(TimestampMixin, Base):
    __tablename__ = "registration_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pending_player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    historical_player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[RegistrationMatchStatus] = mapped_column(
        database_enum(RegistrationMatchStatus, "registration_match_status"),
        default=RegistrationMatchStatus.CANDIDATE,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "pending_player_id",
            "historical_player_id",
            name="uq_registration_matches_pending_historical",
        ),
        CheckConstraint(
            "pending_player_id != historical_player_id",
            name="different_players",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
    )
