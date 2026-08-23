from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import PlayerRewardType
from app.db.models.mixins import TimestampMixin


class PlayerReward(TimestampMixin, Base):
    __tablename__ = "player_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reward_type: Mapped[PlayerRewardType] = mapped_column(
        String(32),
        default=PlayerRewardType.PRIZE_STACK_BONUS,
        nullable=False,
        index=True,
    )
    chips_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source_tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_place: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_through: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    redeemed_tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    redeemed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    redeemed_tournament_day: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "source_tournament_id",
            "player_id",
            "reward_type",
            name="uq_player_rewards_source_player_type",
        ),
        UniqueConstraint(
            "player_id",
            "redeemed_tournament_day",
            name="uq_player_rewards_player_redeemed_day",
        ),
        CheckConstraint(
            "reward_type IN ('prize_stack_bonus')",
            name="ck_player_rewards_type",
        ),
        CheckConstraint("chips_amount > 0", name="ck_player_rewards_chips_positive"),
        CheckConstraint(
            "source_place >= 1 AND source_place <= 3",
            name="ck_player_rewards_source_place",
        ),
        CheckConstraint(
            "(redeemed_at IS NULL AND redeemed_tournament_id IS NULL "
            "AND redeemed_by_user_id IS NULL AND redeemed_tournament_day IS NULL) "
            "OR (redeemed_at IS NOT NULL AND redeemed_tournament_id IS NOT NULL "
            "AND redeemed_by_user_id IS NOT NULL AND redeemed_tournament_day IS NOT NULL)",
            name="ck_player_rewards_redemption_state",
        ),
    )
