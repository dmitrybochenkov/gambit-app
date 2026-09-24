from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HallOfFameAchievement, Season, SeasonHallOfFame, User
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
    ends_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None
    champion_photo_file_id: str | None
    knockout_photo_file_id: str | None
    achievements: tuple["HallOfFameAchievementRow", ...] = ()


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

    async def get_by_season_id(self, season_id: int) -> SeasonHallOfFame | None:
        result = await self.session.execute(
            select(SeasonHallOfFame).where(SeasonHallOfFame.season_id == season_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        *,
        season_id: int,
        updated_by_user_id: int,
    ) -> SeasonHallOfFame:
        entry = await self.get_by_season_id(season_id)
        if entry is not None:
            return entry
        entry = SeasonHallOfFame(
            season_id=season_id,
            updated_by_user_id=updated_by_user_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_achievement(self, achievement_id: int) -> HallOfFameAchievement | None:
        return await self.session.get(HallOfFameAchievement, achievement_id)

    async def add_achievement(
        self, *, season_id: int, player_id: int, kind: HallOfFameAchievementKind, awarded_at: date
    ) -> HallOfFameAchievement:
        achievement = HallOfFameAchievement(
            season_id=season_id, player_id=player_id, kind=kind, awarded_at=awarded_at
        )
        self.session.add(achievement)
        await self.session.flush()
        return achievement

    async def delete_achievement(self, achievement: HallOfFameAchievement) -> None:
        await self.session.delete(achievement)

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

    async def list_completed_entries(self, today: date) -> list[HallOfFameSeasonRow]:
        result = await self.session.execute(
            select(
                Season.id.label("season_id"),
                Season.name.label("season_name"),
                Season.starts_at,
                Season.ends_at,
                SeasonHallOfFame.season_id.label("hall_of_fame_season_id"),
                SeasonHallOfFame.champion_photo_file_id,
                SeasonHallOfFame.knockout_photo_file_id,
            )
            .outerjoin(SeasonHallOfFame, SeasonHallOfFame.season_id == Season.id)
            .where(Season.ends_at.is_not(None), Season.ends_at < today)
            .order_by(Season.starts_at.desc(), Season.id.desc())
        )
        raw_rows = list(result)
        achievements = await self.list_achievements_for_seasons(
            tuple(row.season_id for row in raw_rows)
        )
        rows = []
        for row in raw_rows:
            season_achievements = achievements.get(row.season_id, ())
            if row.hall_of_fame_season_id is None and not season_achievements:
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
                    champion_photo_file_id=row.champion_photo_file_id,
                    knockout_photo_file_id=row.knockout_photo_file_id,
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
