from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season


class SeasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, season_id: int) -> Season | None:
        return await self.session.get(Season, season_id)

    async def get_for_date(self, target_date: date) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(
                Season.starts_at <= target_date,
                or_(Season.ends_at.is_(None), Season.ends_at >= target_date),
            )
            .order_by(Season.starts_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_scheduled_after(self, target_date: date) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(Season.starts_at > target_date)
            .order_by(Season.starts_at, Season.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_completed_before(self, target_date: date) -> list[Season]:
        result = await self.session.execute(
            select(Season)
            .where(Season.ends_at.is_not(None), Season.ends_at < target_date)
            .order_by(Season.starts_at)
        )
        return list(result.scalars())

    async def list_future_after(self, target_date: date) -> list[Season]:
        result = await self.session.execute(
            select(Season)
            .where(Season.starts_at > target_date)
            .order_by(Season.starts_at, Season.id)
        )
        return list(result.scalars())

    async def get_previous_before(self, target_date: date) -> Season | None:
        result = await self.session.execute(
            select(Season)
            .where(Season.starts_at < target_date)
            .order_by(Season.starts_at.desc(), Season.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_open_ended(self) -> Season | None:
        result = await self.session.execute(
            select(Season).where(Season.ends_at.is_(None)).order_by(Season.starts_at).limit(1)
        )
        return result.scalar_one_or_none()

    async def find_overlapping(
        self,
        *,
        starts_at: date,
        ends_at: date | None,
        exclude_id: int | None = None,
    ) -> list[Season]:
        statement = select(Season).where(
            or_(Season.ends_at.is_(None), Season.ends_at >= starts_at),
        )
        if ends_at is not None:
            statement = statement.where(Season.starts_at <= ends_at)
        if exclude_id is not None:
            statement = statement.where(Season.id != exclude_id)
        result = await self.session.execute(statement.order_by(Season.starts_at, Season.id))
        return list(result.scalars())

    async def list_all(self) -> list[Season]:
        result = await self.session.execute(select(Season).order_by(Season.starts_at.desc()))
        return list(result.scalars())

    async def list_all_ordered(self) -> list[Season]:
        result = await self.session.execute(select(Season).order_by(Season.starts_at, Season.id))
        return list(result.scalars())

    async def get_by_name(self, name: str) -> Season | None:
        result = await self.session.execute(select(Season).where(Season.name == name))
        return result.scalar_one_or_none()

    def add(self, season: Season) -> None:
        self.session.add(season)

    async def delete(self, season: Season) -> None:
        await self.session.delete(season)
