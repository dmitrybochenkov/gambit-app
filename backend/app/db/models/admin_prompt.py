from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import AdminPromptStatus, database_enum
from app.db.models.mixins import TimestampMixin


class AdminPrompt(TimestampMixin, Base):
    __tablename__ = "admin_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AdminPromptStatus] = mapped_column(
        database_enum(AdminPromptStatus, "admin_prompt_status"),
        default=AdminPromptStatus.PENDING,
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
