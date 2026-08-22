from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TournamentPublication
from app.db.models.enums import TournamentPublicationDestination, TournamentPublicationType


class TournamentPublicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_identity(
        self,
        *,
        publication_type: TournamentPublicationType,
        content_hash: str,
    ) -> list[TournamentPublication]:
        result = await self.session.execute(
            select(TournamentPublication).where(
                TournamentPublication.publication_type == publication_type,
                TournamentPublication.content_hash == content_hash,
            )
        )
        return list(result.scalars())

    async def exists(
        self,
        *,
        publication_type: TournamentPublicationType,
        destination_type: TournamentPublicationDestination,
        destination_chat_id: int,
        content_hash: str,
    ) -> bool:
        result = await self.session.execute(
            select(TournamentPublication.id).where(
                TournamentPublication.publication_type == publication_type,
                TournamentPublication.destination_type == destination_type,
                TournamentPublication.destination_chat_id == destination_chat_id,
                TournamentPublication.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add(
        self,
        *,
        tournament_id: int | None,
        publication_type: TournamentPublicationType,
        destination_type: TournamentPublicationDestination,
        destination_chat_id: int,
        content_hash: str,
        telegram_message_id: int | None,
        published_by_user_id: int | None,
    ) -> TournamentPublication:
        publication = TournamentPublication(
            tournament_id=tournament_id,
            publication_type=publication_type,
            destination_type=destination_type,
            destination_chat_id=destination_chat_id,
            content_hash=content_hash,
            telegram_message_id=telegram_message_id,
            published_by_user_id=published_by_user_id,
        )
        self.session.add(publication)
        await self.session.flush()
        return publication
