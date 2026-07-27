from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import SeasonStatus, SeasonStatusType


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    scoring_config_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_configs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    starts_at: Mapped[date] = mapped_column(Date, nullable=False)
    ends_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[SeasonStatus] = mapped_column(
        SeasonStatusType(),
        default=SeasonStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            """
            (status = 'active' AND ends_at IS NULL)
            OR (
                status = 'closed'
                AND ends_at IS NOT NULL
                AND starts_at <= ends_at
            )
            """,
            name="status_dates_consistent",
        ),
        Index(
            "uq_seasons_active",
            "status",
            unique=True,
            sqlite_where=status == SeasonStatus.ACTIVE,
        ),
    )
