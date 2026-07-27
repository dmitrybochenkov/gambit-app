from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season
from app.db.models.enums import SeasonStatus


class SeasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, season_id: int) -> Season | None:
        return await self.session.get(Season, season_id)

    async def get_active(self) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(Season.status == SeasonStatus.ACTIVE)
            .order_by(Season.starts_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Season]:
        result = await self.session.execute(select(Season).order_by(Season.starts_at.desc()))
        return list(result.scalars())

    async def get_by_name(self, name: str) -> Season | None:
        result = await self.session.execute(select(Season).where(Season.name == name))
        return result.scalar_one_or_none()

    def add(self, season: Season) -> None:
        self.session.add(season)
