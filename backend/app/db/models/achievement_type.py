from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AchievementType(Base):
    __tablename__ = "achievement_types"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    custom_emoji_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
