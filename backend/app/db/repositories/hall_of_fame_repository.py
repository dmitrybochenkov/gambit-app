from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Season, SeasonHallOfFame, User


@dataclass(frozen=True)
class HallOfFameSeasonRow:
    season_id: int
    season_name: str
    starts_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None
    champion_photo_file_id: str | None
    knockout_photo_file_id: str | None


@dataclass(frozen=True)
class PlayerHallOfFameHonourRow:
    season_id: int
    season_name: str
    starts_at: date
    kind: str


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

    async def list_completed_entries(self, today: date) -> list[HallOfFameSeasonRow]:
        champion = aliased(User)
        knockout = aliased(User)
        result = await self.session.execute(
            select(
                Season.id.label("season_id"),
                Season.name.label("season_name"),
                Season.starts_at,
                SeasonHallOfFame.champion_player_id,
                champion.display_name.label("champion_display_name"),
                SeasonHallOfFame.knockout_player_id.label("knockout_leader_player_id"),
                knockout.display_name.label("knockout_leader_display_name"),
                SeasonHallOfFame.champion_photo_file_id,
                SeasonHallOfFame.knockout_photo_file_id,
            )
            .join(SeasonHallOfFame, SeasonHallOfFame.season_id == Season.id)
            .outerjoin(champion, champion.id == SeasonHallOfFame.champion_player_id)
            .outerjoin(knockout, knockout.id == SeasonHallOfFame.knockout_player_id)
            .where(Season.ends_at.is_not(None), Season.ends_at < today)
            .order_by(Season.starts_at.desc(), Season.id.desc())
        )
        return [
            HallOfFameSeasonRow(
                season_id=row.season_id,
                season_name=row.season_name,
                starts_at=row.starts_at,
                champion_player_id=row.champion_player_id,
                champion_display_name=row.champion_display_name,
                knockout_leader_player_id=row.knockout_leader_player_id,
                knockout_leader_display_name=row.knockout_leader_display_name,
                champion_photo_file_id=row.champion_photo_file_id,
                knockout_photo_file_id=row.knockout_photo_file_id,
            )
            for row in result
        ]

    async def list_player_honours(self, player_id: int) -> list[PlayerHallOfFameHonourRow]:
        result = await self.session.execute(
            select(
                Season.id.label("season_id"),
                Season.name.label("season_name"),
                Season.starts_at,
                SeasonHallOfFame.champion_player_id,
                SeasonHallOfFame.knockout_player_id,
            )
            .join(SeasonHallOfFame, SeasonHallOfFame.season_id == Season.id)
            .where(
                (SeasonHallOfFame.champion_player_id == player_id)
                | (SeasonHallOfFame.knockout_player_id == player_id)
            )
            .order_by(Season.starts_at, Season.id)
        )
        honours: list[PlayerHallOfFameHonourRow] = []
        for row in result:
            if row.champion_player_id == player_id:
                honours.append(
                    PlayerHallOfFameHonourRow(
                        season_id=row.season_id,
                        season_name=row.season_name,
                        starts_at=row.starts_at,
                        kind="champion",
                    )
                )
            if row.knockout_player_id == player_id:
                honours.append(
                    PlayerHallOfFameHonourRow(
                        season_id=row.season_id,
                        season_name=row.season_name,
                        starts_at=row.starts_at,
                        kind="knockout",
                    )
                )
        return honours
