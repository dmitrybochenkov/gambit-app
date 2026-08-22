from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import (
    TournamentPublicationDestination,
    TournamentPublicationType,
)
from app.db.models.mixins import utc_now


class TournamentPublication(Base):
    __tablename__ = "tournament_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    publication_type: Mapped[TournamentPublicationType] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )
    destination_type: Mapped[TournamentPublicationDestination] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )
    destination_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    published_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "publication_type",
            "destination_type",
            "destination_chat_id",
            "content_hash",
            name="uq_tournament_publications_identity",
        ),
        CheckConstraint(
            "publication_type IN ('results', 'schedule')",
            name="ck_tournament_publications_type",
        ),
        CheckConstraint(
            "destination_type IN ('group', 'channel')",
            name="ck_tournament_publications_destination",
        ),
    )
