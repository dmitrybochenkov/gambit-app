from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tournament_photo import TournamentPhoto


@dataclass(frozen=True)
class TournamentPhotoRecord:
    id: int
    tournament_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    uploaded_by_user_id: int | None
    position: int
    created_at: datetime


class TournamentPhotoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_tournament(self, tournament_id: int) -> list[TournamentPhoto]:
        result = await self.session.execute(
            select(TournamentPhoto)
            .where(TournamentPhoto.tournament_id == tournament_id)
            .order_by(TournamentPhoto.position, TournamentPhoto.id)
        )
        return list(result.scalars())

    async def count_for_tournament(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(func.count(TournamentPhoto.id)).where(
                TournamentPhoto.tournament_id == tournament_id
            )
        )
        return int(result.scalar_one())

    async def exists_unique_file(
        self,
        *,
        tournament_id: int,
        telegram_file_unique_id: str,
    ) -> bool:
        result = await self.session.execute(
            select(TournamentPhoto.id).where(
                TournamentPhoto.tournament_id == tournament_id,
                TournamentPhoto.telegram_file_unique_id == telegram_file_unique_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def next_position(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(TournamentPhoto.position), -1)).where(
                TournamentPhoto.tournament_id == tournament_id
            )
        )
        return int(result.scalar_one()) + 1

    async def add(
        self,
        *,
        tournament_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        uploaded_by_user_id: int | None,
        position: int,
    ) -> TournamentPhoto:
        photo = TournamentPhoto(
            tournament_id=tournament_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            uploaded_by_user_id=uploaded_by_user_id,
            position=position,
        )
        self.session.add(photo)
        await self.session.flush()
        return photo

    async def delete_all_for_tournament(self, tournament_id: int) -> int:
        result = await self.session.execute(
            delete(TournamentPhoto).where(TournamentPhoto.tournament_id == tournament_id)
        )
        return int(result.rowcount or 0)
