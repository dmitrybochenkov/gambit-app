from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScoringConfig


class ScoringConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, scoring_config_id: int) -> ScoringConfig | None:
        return await self.session.get(ScoringConfig, scoring_config_id)

    async def list_all(self) -> list[ScoringConfig]:
        result = await self.session.execute(select(ScoringConfig).order_by(ScoringConfig.id))
        return list(result.scalars())
