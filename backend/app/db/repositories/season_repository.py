from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season
from app.db.models.enums import SeasonStatus


class SeasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(Season.status == SeasonStatus.ACTIVE)
            .order_by(Season.starts_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Season | None:
        result = await self.session.execute(select(Season).where(Season.name == name))
        return result.scalar_one_or_none()

    async def get_for_date(self, target_date: date) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(
                Season.starts_at <= target_date,
                Season.ends_at >= target_date,
            )
            .order_by(Season.status, Season.starts_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
