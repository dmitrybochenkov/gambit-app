from dataclasses import dataclass


@dataclass(frozen=True)
class AchievementTypeView:
    kind: str
    title: str
    emoji: str
    custom_emoji_id: str | None = None
