from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentRegistration, TournamentResult, User
from app.db.models.enums import TournamentStatus, UserStatus


class TournamentRegistrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        tournament_id: int,
        player_id: int,
    ) -> TournamentRegistration | None:
        result = await self.session.execute(
            select(TournamentRegistration).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def exists(
        self,
        tournament_id: int,
        player_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(TournamentRegistration.id).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.player_id == player_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_registered_user_ids(self, tournament_id: int) -> set[int]:
        result = await self.session.execute(
            select(TournamentRegistration.player_id).where(
                TournamentRegistration.tournament_id == tournament_id
            )
        )
        return set(result.scalars())

    async def list_active_registered_users(self, tournament_id: int) -> list[User]:
        result = await self.session.execute(
            select(User)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())

    async def list_active_unchecked_registered_users(
        self,
        tournament_id: int,
        checked_in_user_ids: set[int],
    ) -> list[User]:
        statement = (
            select(User)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.display_name, User.id)
        )
        if checked_in_user_ids:
            statement = statement.where(User.id.not_in(checked_in_user_ids))
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def add(
        self,
        tournament_id: int,
        player_id: int,
    ) -> TournamentRegistration:
        registration = TournamentRegistration(
            tournament_id=tournament_id,
            player_id=player_id,
        )
        self.session.add(registration)
        await self.session.flush()
        return registration

    async def delete(self, registration: TournamentRegistration) -> None:
        await self.session.delete(registration)

    async def list_registered_upcoming(
        self,
        player_id: int,
        from_date: date,
    ) -> list[Tournament]:
        result = await self.session.execute(
            select(Tournament)
            .options(selectinload(Tournament.tournament_type))
            .join(
                TournamentRegistration,
                TournamentRegistration.tournament_id == Tournament.id,
            )
            .where(
                TournamentRegistration.player_id == player_id,
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.date >= from_date,
                ~select(TournamentResult.id)
                .where(
                    TournamentResult.tournament_id == Tournament.id,
                    TournamentResult.player_id == player_id,
                )
                .exists(),
            )
            .order_by(Tournament.date, Tournament.tournament_type_id)
        )
        return list(result.scalars())
