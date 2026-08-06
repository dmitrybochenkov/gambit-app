from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import (
    RegistrationRequestStatus,
    RegistrationRequestType,
    database_enum,
)
from app.db.models.mixins import TimestampMixin


class RegistrationRequest(TimestampMixin, Base):
    __tablename__ = "registration_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    request_type: Mapped[RegistrationRequestType] = mapped_column(
        database_enum(RegistrationRequestType, "registration_request_type"),
        nullable=False,
        index=True,
    )
    status: Mapped[RegistrationRequestStatus] = mapped_column(
        database_enum(RegistrationRequestStatus, "registration_request_status"),
        default=RegistrationRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    requested_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_display_name_normalized: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    requested_link_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidate_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            """
            (
                request_type = 'new_player'
                AND requested_display_name IS NOT NULL
                AND requested_display_name_normalized IS NOT NULL
                AND requested_link_name IS NULL
                AND candidate_user_id IS NULL
            )
            OR (
                request_type = 'link_existing_player'
                AND requested_display_name IS NULL
                AND requested_display_name_normalized IS NULL
                AND requested_link_name IS NOT NULL
            )
            """,
            name="registration_request_payload",
        ),
        CheckConstraint(
            """
            (status = 'pending' AND reviewed_at IS NULL)
            OR (status IN ('approved', 'rejected') AND reviewed_at IS NOT NULL)
            """,
            name="registration_request_review_state",
        ),
        Index(
            "uq_registration_requests_pending_telegram_id",
            "telegram_id",
            unique=True,
            sqlite_where=(status == RegistrationRequestStatus.PENDING),
        ),
    )
