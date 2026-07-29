from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    TournamentParticipant,
    TournamentRegistration,
    TournamentResult,
    TournamentResultDraft,
    User,
)
from app.db.models.enums import RegistrationStatus, TournamentParticipantSource, UserStatus


class TournamentParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        tournament_id: int,
        user_id: int,
    ) -> TournamentParticipant | None:
        result = await self.session.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_user_ids(self, tournament_id: int) -> list[int]:
        result = await self.session.execute(
            select(TournamentParticipant.user_id).where(
                TournamentParticipant.tournament_id == tournament_id
            )
        )
        return list(result.scalars())

    async def add_if_missing(
        self,
        *,
        tournament_id: int,
        user_id: int,
        source: TournamentParticipantSource,
        checked_in_by_user_id: int,
    ) -> TournamentParticipant:
        participant = await self.get(tournament_id, user_id)
        if participant is not None:
            return participant
        participant = TournamentParticipant(
            tournament_id=tournament_id,
            user_id=user_id,
            source=source,
            checked_in_by_user_id=checked_in_by_user_id,
        )
        self.session.add(participant)
        await self.session.flush()
        return participant

    async def delete(self, participant: TournamentParticipant) -> None:
        await self.session.delete(participant)

    async def registered_user_ids(self, tournament_id: int) -> set[int]:
        result = await self.session.execute(
            select(TournamentRegistration.player_id).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
            )
        )
        return set(result.scalars())

    async def has_result_data(self, tournament_id: int, user_id: int) -> bool:
        draft_result = await self.session.execute(
            select(TournamentResultDraft.id).where(
                TournamentResultDraft.tournament_id == tournament_id,
                TournamentResultDraft.player_id == user_id,
                (
                    (TournamentResultDraft.place.is_not(None))
                    | (TournamentResultDraft.knockouts_count > 0)
                    | (TournamentResultDraft.big_knockouts_count > 0)
                ),
            )
        )
        if draft_result.scalar_one_or_none() is not None:
            return True
        result = await self.session.execute(
            select(TournamentResult.id).where(
                TournamentResult.tournament_id == tournament_id,
                TournamentResult.player_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def delete_empty_draft(self, tournament_id: int, user_id: int) -> None:
        await self.session.execute(
            delete(TournamentResultDraft).where(
                TournamentResultDraft.tournament_id == tournament_id,
                TournamentResultDraft.player_id == user_id,
                TournamentResultDraft.place.is_(None),
                TournamentResultDraft.knockouts_count == 0,
                TournamentResultDraft.big_knockouts_count == 0,
            )
        )

    async def list_registered_check_in_rows(self, tournament_id: int) -> list[object]:
        result = await self.session.execute(
            select(
                User.id.label("user_id"),
                User.display_name,
                TournamentParticipant.source,
                TournamentResultDraft.place,
                TournamentResultDraft.knockouts_count,
                TournamentResultDraft.big_knockouts_count,
            )
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .outerjoin(
                TournamentParticipant,
                (TournamentParticipant.tournament_id == tournament_id)
                & (TournamentParticipant.user_id == User.id),
            )
            .outerjoin(
                TournamentResultDraft,
                (TournamentResultDraft.tournament_id == tournament_id)
                & (TournamentResultDraft.player_id == User.id),
            )
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
            )
            .order_by(User.display_name, User.id)
        )
        return list(result)

    async def walk_in_count(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(func.count(TournamentParticipant.id)).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.source.in_(
                    [
                        TournamentParticipantSource.DATABASE_WALK_IN,
                        TournamentParticipantSource.ADMIN_CREATED,
                    ]
                ),
            )
        )
        return int(result.scalar_one())

    async def participant_count(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(func.count(TournamentParticipant.id)).where(
                TournamentParticipant.tournament_id == tournament_id
            )
        )
        return int(result.scalar_one())

    async def search_registered(self, tournament_id: int) -> list[User]:
        result = await self.session.execute(
            select(User)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.display_name, User.id)
        )
        return list(result.scalars())
