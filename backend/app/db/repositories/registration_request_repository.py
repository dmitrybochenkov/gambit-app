from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegistrationRequest
from app.db.models.enums import RegistrationRequestStatus


class RegistrationRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, request_id: int) -> RegistrationRequest | None:
        return await self.session.get(RegistrationRequest, request_id)

    async def get_pending_by_telegram_id(
        self,
        telegram_id: int,
    ) -> RegistrationRequest | None:
        result = await self.session.execute(
            select(RegistrationRequest).where(
                RegistrationRequest.telegram_id == telegram_id,
                RegistrationRequest.status == RegistrationRequestStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def list_pending(self, limit: int | None = None) -> list[RegistrationRequest]:
        query = (
            select(RegistrationRequest)
            .where(RegistrationRequest.status == RegistrationRequestStatus.PENDING)
            .order_by(RegistrationRequest.created_at, RegistrationRequest.id)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars())

    def add(self, request: RegistrationRequest) -> None:
        self.session.add(request)
