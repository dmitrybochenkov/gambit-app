from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import AdminPromptKind, AdminPromptStatus, database_enum
from app.db.models.mixins import TimestampMixin


class AdminPrompt(TimestampMixin, Base):
    __tablename__ = "admin_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    kind: Mapped[AdminPromptKind] = mapped_column(
        database_enum(AdminPromptKind, "admin_prompt_kind"),
        nullable=False,
        index=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AdminPromptStatus] = mapped_column(
        database_enum(AdminPromptStatus, "admin_prompt_status"),
        default=AdminPromptStatus.PENDING,
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("key", name="uq_admin_prompts_key"),
        CheckConstraint(
            "kind IN ('tournaments_proposal', 'season_proposal')",
            name="kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL AND resolved_by_user_id IS NULL) "
            "OR (status IN ('confirmed', 'cancelled') "
            "AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)",
            name="resolution_state",
        ),
        Index("ix_admin_prompts_kind_scope_status", "kind", "scope_key", "status"),
        Index(
            "uq_admin_prompts_pending_scope",
            "kind",
            "scope_key",
            unique=True,
            sqlite_where=text("status = 'pending' AND scope_key IS NOT NULL"),
            postgresql_where=text("status = 'pending' AND scope_key IS NOT NULL"),
        ),
    )
