from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HallOfFameAchievement, HallOfFamePhoto, Season, User
from app.db.models.enums import (
    HallOfFameAchievementKind,
    UserGender,
    UserRole,
    UserStatus,
)

_ACHIEVEMENT_KIND_ORDER = {
    HallOfFameAchievementKind.RATING_WINNER: 0,
    HallOfFameAchievementKind.KO_RATING_WINNER: 1,
    HallOfFameAchievementKind.GRAND_SEASON: 2,
    HallOfFameAchievementKind.GRAND_MONTH: 3,
    HallOfFameAchievementKind.GRAND_KNOCKOUT: 4,
}


@dataclass(frozen=True)
class HallOfFameSeasonRow:
    season_id: int
    season_name: str
    starts_at: date
    ends_at: date | None
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None
    photos: tuple["HallOfFamePhotoRow", ...] = ()
    achievements: tuple["HallOfFameAchievementRow", ...] = ()


@dataclass(frozen=True)
class HallOfFamePhotoRow:
    id: int
    season_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    position: int


@dataclass(frozen=True)
class HallOfFameAchievementRow:
    id: int
    season_id: int
    player_id: int
    display_name: str
    telegram_id: int | None
    status: UserStatus
    role: UserRole
    gender: UserGender | None
    kind: HallOfFameAchievementKind
    awarded_at: date


@dataclass(frozen=True)
class PlayerHallOfFameHonourRow:
    achievement_id: int
    season_id: int
    season_name: str
    starts_at: date
    kind: str
    awarded_at: date


class HallOfFameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_achievement(
        self, *, season_id: int, player_id: int, kind: HallOfFameAchievementKind, awarded_at: date
    ) -> HallOfFameAchievement:
        achievement = HallOfFameAchievement(
            season_id=season_id, player_id=player_id, kind=kind, awarded_at=awarded_at
        )
        self.session.add(achievement)
        await self.session.flush()
        return achievement

    async def get_singleton_achievement(
        self, *, season_id: int, kind: HallOfFameAchievementKind
    ) -> HallOfFameAchievement | None:
        result = await self.session.execute(
            select(HallOfFameAchievement).where(
                HallOfFameAchievement.season_id == season_id,
                HallOfFameAchievement.kind == kind,
            )
        )
        return result.scalar_one_or_none()

    async def add_photo(
        self,
        *,
        season_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        uploaded_by_user_id: int,
    ) -> HallOfFamePhoto:
        photos = (await self.list_photos_for_seasons((season_id,))).get(season_id, ())
        photo = HallOfFamePhoto(
            season_id=season_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            uploaded_by_user_id=uploaded_by_user_id,
            position=max((item.position for item in photos), default=-1) + 1,
        )
        self.session.add(photo)
        await self.session.flush()
        return photo

    async def delete_all_photos(self, season_id: int) -> None:
        await self.session.execute(
            delete(HallOfFamePhoto).where(HallOfFamePhoto.season_id == season_id)
        )

    async def list_photos_for_seasons(
        self, season_ids: tuple[int, ...]
    ) -> dict[int, tuple[HallOfFamePhotoRow, ...]]:
        if not season_ids:
            return {}
        result = await self.session.execute(
            select(HallOfFamePhoto)
            .where(HallOfFamePhoto.season_id.in_(season_ids))
            .order_by(HallOfFamePhoto.season_id, HallOfFamePhoto.position, HallOfFamePhoto.id)
        )
        grouped: dict[int, list[HallOfFamePhotoRow]] = {}
        for photo in result.scalars():
            grouped.setdefault(photo.season_id, []).append(
                HallOfFamePhotoRow(
                    id=photo.id,
                    season_id=photo.season_id,
                    telegram_file_id=photo.telegram_file_id,
                    telegram_file_unique_id=photo.telegram_file_unique_id,
                    position=photo.position,
                )
            )
        return {season_id: tuple(items) for season_id, items in grouped.items()}

    async def list_achievements_for_seasons(
        self, season_ids: tuple[int, ...]
    ) -> dict[int, tuple[HallOfFameAchievementRow, ...]]:
        if not season_ids:
            return {}
        result = await self.session.execute(
            select(
                HallOfFameAchievement,
                User.display_name,
                User.telegram_id,
                User.status,
                User.role,
                User.gender,
            )
            .join(User, User.id == HallOfFameAchievement.player_id)
            .where(HallOfFameAchievement.season_id.in_(season_ids))
            .order_by(HallOfFameAchievement.season_id, HallOfFameAchievement.id)
        )
        grouped: dict[int, list[HallOfFameAchievementRow]] = {}
        for achievement, display_name, telegram_id, status, role, gender in result:
            grouped.setdefault(achievement.season_id, []).append(
                HallOfFameAchievementRow(
                    id=achievement.id,
                    season_id=achievement.season_id,
                    player_id=achievement.player_id,
                    display_name=display_name,
                    telegram_id=telegram_id,
                    status=status,
                    role=role,
                    gender=gender,
                    kind=achievement.kind,
                    awarded_at=achievement.awarded_at,
                )
            )
        return {
            season_id: tuple(
                sorted(
                    items,
                    key=lambda item: (
                        _ACHIEVEMENT_KIND_ORDER[item.kind],
                        -item.awarded_at.toordinal()
                        if item.kind
                        in {
                            HallOfFameAchievementKind.GRAND_MONTH,
                            HallOfFameAchievementKind.GRAND_KNOCKOUT,
                        }
                        else item.awarded_at.toordinal(),
                        -item.id,
                    ),
                )
            )
            for season_id, items in grouped.items()
        }

    async def list_public_entries(self, today: date) -> list[HallOfFameSeasonRow]:
        result = await self.session.execute(
            select(
                Season.id.label("season_id"),
                Season.name.label("season_name"),
                Season.starts_at,
                Season.ends_at,
            )
            .where(Season.starts_at <= today)
            .order_by(Season.starts_at.desc(), Season.id.desc())
        )
        raw_rows = list(result)
        season_ids = tuple(row.season_id for row in raw_rows)
        achievements = await self.list_achievements_for_seasons(season_ids)
        photos = await self.list_photos_for_seasons(season_ids)
        rows = []
        for row in raw_rows:
            season_achievements = achievements.get(row.season_id, ())
            season_photos = photos.get(row.season_id, ())
            if not season_photos and not season_achievements:
                continue
            champion = next(
                (
                    item
                    for item in season_achievements
                    if item.kind == HallOfFameAchievementKind.RATING_WINNER
                ),
                None,
            )
            knockout = next(
                (
                    item
                    for item in season_achievements
                    if item.kind == HallOfFameAchievementKind.KO_RATING_WINNER
                ),
                None,
            )
            rows.append(
                HallOfFameSeasonRow(
                    season_id=row.season_id,
                    season_name=row.season_name,
                    starts_at=row.starts_at,
                    ends_at=row.ends_at,
                    champion_player_id=champion.player_id if champion is not None else None,
                    champion_display_name=champion.display_name if champion is not None else None,
                    knockout_leader_player_id=knockout.player_id if knockout is not None else None,
                    knockout_leader_display_name=(
                        knockout.display_name if knockout is not None else None
                    ),
                    photos=season_photos,
                    achievements=season_achievements,
                )
            )
        return rows

    async def list_player_honours(self, player_id: int) -> list[PlayerHallOfFameHonourRow]:
        result = await self.session.execute(
            select(HallOfFameAchievement, Season.name, Season.starts_at)
            .join(Season, Season.id == HallOfFameAchievement.season_id)
            .where(HallOfFameAchievement.player_id == player_id)
            .order_by(Season.starts_at, HallOfFameAchievement.id)
        )
        rows = [
            PlayerHallOfFameHonourRow(
                achievement_id=achievement.id,
                season_id=achievement.season_id,
                season_name=season_name,
                starts_at=starts_at,
                kind=achievement.kind.value,
                awarded_at=achievement.awarded_at,
            )
            for achievement, season_name, starts_at in result
        ]
        return sorted(
            rows,
            key=lambda row: (
                row.starts_at,
                _ACHIEVEMENT_KIND_ORDER[HallOfFameAchievementKind(row.kind)],
                -row.awarded_at.toordinal()
                if row.kind in {"grand_month", "grand_knockout"}
                else row.awarded_at.toordinal(),
                -row.achievement_id,
            ),
        )
