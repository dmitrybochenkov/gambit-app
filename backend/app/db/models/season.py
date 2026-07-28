from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, literal_column
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


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

    __table_args__ = (
        CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at",
            name="date_range",
        ),
        Index(
            "uq_seasons_open_ended",
            literal_column("1"),
            unique=True,
            sqlite_where=ends_at.is_(None),
        ),
    )
