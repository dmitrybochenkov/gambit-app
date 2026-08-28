from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import UserGender, UserRole, UserStatus, database_enum
from app.db.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(
        database_enum(UserRole, "user_role"),
        default=UserRole.PLAYER,
        nullable=False,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        database_enum(UserStatus, "user_status"),
        default=UserStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    gender: Mapped[UserGender | None] = mapped_column(
        database_enum(UserGender, "user_gender"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_users_display_name_normalized", "display_name_normalized"),
        CheckConstraint("role IN ('player', 'admin', 'superadmin')", name="users_role_values"),
        CheckConstraint("status IN ('active', 'blocked')", name="users_status_values"),
        CheckConstraint(
            "gender IN ('male', 'female') OR gender IS NULL",
            name="users_gender_values",
        ),
    )
