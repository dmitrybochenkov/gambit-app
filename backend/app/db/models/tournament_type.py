from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import (
    KnockoutMode,
    TournamentTypeStatus,
    database_enum,
)
from app.db.models.mixins import TimestampMixin


class TournamentType(TimestampMixin, Base):
    __tablename__ = "tournament_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TournamentTypeStatus] = mapped_column(
        database_enum(TournamentTypeStatus, "tournament_type_status"),
        default=TournamentTypeStatus.ACTIVE,
        nullable=False,
        index=True,
    )


class TournamentTypeRule(TimestampMixin, Base):
    __tablename__ = "tournament_type_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_type_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_types.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    points_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("1.00"),
        nullable=False,
    )
    prize_place_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("1.00"),
        nullable=False,
    )
    prize_place_multiplier_places: Mapped[str | None] = mapped_column(Text, nullable=True)
    knockout_mode: Mapped[KnockoutMode] = mapped_column(
        database_enum(KnockoutMode, "knockout_mode"),
        default=KnockoutMode.NONE,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("points_multiplier > 0", name="points_multiplier_positive"),
        CheckConstraint(
            "prize_place_multiplier > 0",
            name="prize_place_multiplier_positive",
        ),
    )


class TournamentEconomyConfig(TimestampMixin, Base):
    __tablename__ = "tournament_economy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_type_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_types.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    entry_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    addon_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    addon_stack: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("entry_fee >= 0", name="entry_fee_nonnegative"),
        CheckConstraint("entry_stack > 0", name="entry_stack_positive"),
        CheckConstraint("addon_fee >= 0", name="addon_fee_nonnegative"),
        CheckConstraint("addon_stack > 0", name="addon_stack_positive"),
    )


class TournamentRebuyConfig(TimestampMixin, Base):
    __tablename__ = "tournament_rebuy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_type_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rebuy_order: Mapped[int] = mapped_column(Integer, nullable=False)
    fee: Mapped[int] = mapped_column(Integer, nullable=False)
    stack: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("rebuy_order > 0", name="rebuy_order_positive"),
        CheckConstraint("fee >= 0", name="fee_nonnegative"),
        CheckConstraint("stack > 0", name="stack_positive"),
    )


class WeeklyTournamentTemplate(TimestampMixin, Base):
    __tablename__ = "weekly_tournament_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tournament_type_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rotation_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    tournament_type: Mapped[TournamentType] = relationship()

    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="weekday_range"),
        CheckConstraint(
            "rotation_order IS NULL OR rotation_order > 0",
            name="rotation_order_positive",
        ),
    )
