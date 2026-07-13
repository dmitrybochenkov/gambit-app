from decimal import Decimal

from sqlalchemy import CheckConstraint, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class ScoringConfig(TimestampMixin, Base):
    __tablename__ = "scoring_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_1_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.45"), nullable=False
    )
    place_2_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.25"), nullable=False
    )
    place_3_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.15"), nullable=False
    )
    place_4_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.10"), nullable=False
    )
    place_5_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.05"), nullable=False
    )
    knockout_small_points: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    knockout_big_points: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "place_1_coefficient >= 0 AND place_1_coefficient <= 1",
            name="place_1_coefficient_range",
        ),
        CheckConstraint(
            "place_2_coefficient >= 0 AND place_2_coefficient <= 1",
            name="place_2_coefficient_range",
        ),
        CheckConstraint(
            "place_3_coefficient >= 0 AND place_3_coefficient <= 1",
            name="place_3_coefficient_range",
        ),
        CheckConstraint(
            "place_4_coefficient >= 0 AND place_4_coefficient <= 1",
            name="place_4_coefficient_range",
        ),
        CheckConstraint(
            "place_5_coefficient >= 0 AND place_5_coefficient <= 1",
            name="place_5_coefficient_range",
        ),
        CheckConstraint(
            """
            place_1_coefficient + place_2_coefficient + place_3_coefficient
            + place_4_coefficient + place_5_coefficient = 1
            """,
            name="place_coefficients_sum",
        ),
        CheckConstraint(
            "knockout_small_points >= 0",
            name="knockout_small_points_nonnegative",
        ),
        CheckConstraint(
            "knockout_big_points >= 0",
            name="knockout_big_points_nonnegative",
        ),
    )
