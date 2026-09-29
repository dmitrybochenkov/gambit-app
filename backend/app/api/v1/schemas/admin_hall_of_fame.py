from datetime import date

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import HallOfFameAchievementKind
from app.services.dto.achievements import AchievementTypeView
from app.services.dto.hall_of_fame import (
    HallOfFameAchievementManagementView,
    HallOfFameCandidateView,
    HallOfFameEntryView,
    HallOfFameSeasonListItemView,
)

from .media import PhotoDescriptorResponse


class HallOfFameManagementSeasonResponse(BaseModel):
    id: int
    name: str
    starts_at: date
    ends_at: date | None

    @classmethod
    def from_view(
        cls,
        view: HallOfFameSeasonListItemView,
    ) -> "HallOfFameManagementSeasonResponse":
        return cls(
            id=view.season_id,
            name=view.season_name,
            starts_at=view.starts_at,
            ends_at=view.ends_at,
        )


class HallOfFameManagementSeasonListResponse(BaseModel):
    items: list[HallOfFameManagementSeasonResponse]


class HallOfFameManagementPlayerResponse(BaseModel):
    id: int
    display_name: str


class HallOfFameManagementPlayerListResponse(BaseModel):
    items: list[HallOfFameManagementPlayerResponse]

    @classmethod
    def from_views(
        cls,
        views: list[HallOfFameCandidateView],
    ) -> "HallOfFameManagementPlayerListResponse":
        return cls(
            items=[
                HallOfFameManagementPlayerResponse(
                    id=view.user.id,
                    display_name=view.user.display_name,
                )
                for view in views
            ]
        )


class HallOfFameAchievementTypeResponse(BaseModel):
    kind: str
    title: str
    emoji: str
    custom_emoji_id: str | None

    @classmethod
    def from_view(cls, view: AchievementTypeView) -> "HallOfFameAchievementTypeResponse":
        return cls(
            kind=view.kind,
            title=view.title,
            emoji=view.emoji,
            custom_emoji_id=view.custom_emoji_id,
        )


class HallOfFameAchievementTypeListResponse(BaseModel):
    items: list[HallOfFameAchievementTypeResponse]


class HallOfFameManagementAchievementResponse(BaseModel):
    id: int
    season_id: int
    player: HallOfFameManagementPlayerResponse
    kind: HallOfFameAchievementKind
    awarded_at: date
    title: str
    emoji: str
    custom_emoji_id: str | None

    @classmethod
    def from_view(
        cls,
        season_id: int,
        view: HallOfFameAchievementManagementView,
    ) -> "HallOfFameManagementAchievementResponse":
        return cls(
            id=view.id,
            season_id=season_id,
            player=HallOfFameManagementPlayerResponse(
                id=view.player.id,
                display_name=view.player.display_name,
            ),
            kind=view.kind,
            awarded_at=view.awarded_at,
            title=view.title,
            emoji=view.emoji,
            custom_emoji_id=view.custom_emoji_id,
        )


class HallOfFameManagementEntryResponse(BaseModel):
    season: HallOfFameManagementSeasonResponse
    achievements: list[HallOfFameManagementAchievementResponse]
    achievement_types: list[HallOfFameAchievementTypeResponse]
    photos: list[PhotoDescriptorResponse]

    @classmethod
    def from_view(cls, view: HallOfFameEntryView) -> "HallOfFameManagementEntryResponse":
        return cls(
            season=HallOfFameManagementSeasonResponse(
                id=view.season_id,
                name=view.season_name,
                starts_at=view.starts_at,
                ends_at=view.ends_at,
            ),
            achievements=[
                HallOfFameManagementAchievementResponse.from_view(view.season_id, item)
                for item in view.achievements
            ],
            achievement_types=[
                HallOfFameAchievementTypeResponse.from_view(item) for item in view.achievement_types
            ],
            photos=[
                PhotoDescriptorResponse.hall_of_fame_photo(
                    photo_id=photo.id,
                    position=photo.position,
                )
                for photo in view.photos
            ],
        )


class HallOfFameAchievementCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_id: int
    player_id: int
    kind: HallOfFameAchievementKind
    awarded_at: date
