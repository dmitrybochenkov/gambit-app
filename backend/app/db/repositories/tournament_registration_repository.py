from datetime import date
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentRegistration, TournamentResult, TournamentType, User
from app.db.models.enums import TournamentStatus, UserStatus


class TournamentRegistrationCountRow(NamedTuple):
    tournament_id: int
    tournament_date: date
    tournament_type_name: str
    registrations_count: int


class TournamentRegistrationPlayerRow(NamedTuple):
    player_id: int
    display_name: str


class TournamentRegistrationsDetailRow(NamedTuple):
    tournament_id: int
    tournament_date: date
    tournament_type_name: str
    players: list[TournamentRegistrationPlayerRow]


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

    async def list_registered_player_ids(self, tournament_id: int) -> set[int]:
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

    async def count_by_tournament_ids(self, tournament_ids: tuple[int, ...]) -> dict[int, int]:
        if not tournament_ids:
            return {}
        result = await self.session.execute(
            select(TournamentRegistration.tournament_id, func.count(TournamentRegistration.id))
            .where(TournamentRegistration.tournament_id.in_(tournament_ids))
            .group_by(TournamentRegistration.tournament_id)
        )
        return {int(tournament_id): int(count) for tournament_id, count in result.all()}

    async def delete_by_tournament(self, tournament_id: int) -> None:
        registrations = await self.session.execute(
            select(TournamentRegistration).where(
                TournamentRegistration.tournament_id == tournament_id
            )
        )
        for registration in registrations.scalars():
            await self.delete(registration)

    async def list_active_unchecked_registered_users(
        self,
        tournament_id: int,
        checked_in_player_ids: set[int],
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
        if checked_in_player_ids:
            statement = statement.where(User.id.not_in(checked_in_player_ids))
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

    async def delete_by_tournament_and_player(
        self,
        tournament_id: int,
        player_id: int,
    ) -> bool:
        registration = await self.get(tournament_id, player_id)
        if registration is None:
            return False
        await self.delete(registration)
        return True

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
                Tournament.registration_open.is_(True),
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

    async def list_active_tournament_registration_counts(
        self,
        from_date: date,
    ) -> list[TournamentRegistrationCountRow]:
        result = await self.session.execute(
            select(
                Tournament.id,
                Tournament.date,
                TournamentType.name,
                func.count(TournamentRegistration.id),
            )
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .join(TournamentRegistration, TournamentRegistration.tournament_id == Tournament.id)
            .where(
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.registration_open.is_(True),
                Tournament.date >= from_date,
            )
            .group_by(Tournament.id, Tournament.date, TournamentType.name)
            .order_by(Tournament.date, Tournament.id)
        )
        return [
            TournamentRegistrationCountRow(
                tournament_id=int(row[0]),
                tournament_date=row[1],
                tournament_type_name=str(row[2]),
                registrations_count=int(row[3]),
            )
            for row in result.all()
        ]

    async def get_active_tournament_registration_detail(
        self,
        tournament_id: int,
        from_date: date,
    ) -> TournamentRegistrationsDetailRow | None:
        tournament_result = await self.session.execute(
            select(Tournament.id, Tournament.date, TournamentType.name)
            .join(TournamentType, TournamentType.id == Tournament.tournament_type_id)
            .where(
                Tournament.id == tournament_id,
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.registration_open.is_(True),
                Tournament.date >= from_date,
            )
        )
        tournament = tournament_result.one_or_none()
        if tournament is None:
            return None

        players_result = await self.session.execute(
            select(User.id, User.display_name)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(TournamentRegistration.tournament_id == tournament_id)
            .order_by(User.display_name_normalized, User.display_name, User.id)
        )
        return TournamentRegistrationsDetailRow(
            tournament_id=int(tournament[0]),
            tournament_date=tournament[1],
            tournament_type_name=str(tournament[2]),
            players=[
                TournamentRegistrationPlayerRow(
                    player_id=int(row[0]),
                    display_name=str(row[1]),
                )
                for row in players_result.all()
            ],
        )
