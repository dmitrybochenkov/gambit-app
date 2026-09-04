from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament
from app.db.models.enums import TournamentCombinationType
from app.db.repositories.tournament_combination_repository import TournamentCombinationRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.results import (
    TournamentCombinationPlayerView,
    TournamentCombinationsView,
    TournamentCombinationView,
)
from app.services.result_errors import (
    ResultCombinationAlreadyExistsError,
    ResultCombinationNotFoundError,
    ResultInvalidCombinationRankError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    TournamentResultsEditingUnavailableError,
)
from app.services.tournament_service import tournament_view

FOUR_OF_A_KIND_RANKS = {
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "J",
    "Q",
    "K",
    "A",
}


class TournamentCombinationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def list_for_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCombinationsView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            return await self.list_for_tournament_in_session(session, tournament)

    async def add_combination(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        combination_type: TournamentCombinationType,
        rank: str | None = None,
    ) -> TournamentCombinationsView:
        self._validate_rank(combination_type, rank)
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            result = await TournamentResultRepository(session).get_by_tournament_and_player(
                tournament.id,
                player_id,
            )
            if result is None:
                raise ResultUserNotFoundError
            try:
                await TournamentCombinationRepository(session).add(
                    tournament_id=tournament.id,
                    player_id=player_id,
                    combination_type=combination_type,
                    rank=rank,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ResultCombinationAlreadyExistsError from exc
            return await self.list_for_tournament_in_session(session, tournament)

    async def delete_combination(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        combination_id: int,
    ) -> TournamentCombinationsView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            deleted = await TournamentCombinationRepository(session).delete_by_id(
                tournament_id=tournament_id,
                combination_id=combination_id,
            )
            if not deleted:
                raise ResultCombinationNotFoundError
            await session.commit()
            return await self.list_for_tournament_in_session(session, tournament)

    async def list_for_tournament_in_session(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> TournamentCombinationsView:
        repository = TournamentCombinationRepository(session)
        combinations = await repository.list_with_users(tournament.id)
        players = await repository.list_player_candidates(tournament.id)
        return TournamentCombinationsView(
            tournament=tournament_view(tournament),
            combinations=[
                TournamentCombinationView(
                    id=row.combination.id,
                    tournament_id=row.combination.tournament_id,
                    player_id=row.user.id,
                    display_name=row.user.display_name,
                    combination_type=row.combination.combination_type,
                    rank=row.combination.rank,
                )
                for row in combinations
            ],
            players=[
                TournamentCombinationPlayerView(
                    player_id=player.id,
                    display_name=player.display_name,
                )
                for player in players
            ],
        )

    async def delete_for_player_in_session(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        player_id: int,
    ) -> int:
        return await TournamentCombinationRepository(session).delete_for_player(
            tournament_id=tournament_id,
            player_id=player_id,
        )

    async def count_for_player_in_session(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        player_id: int,
    ) -> int:
        combinations = await TournamentCombinationRepository(session).list_for_player(
            tournament_id=tournament_id,
            player_id=player_id,
        )
        return len(combinations)

    @staticmethod
    def _validate_rank(
        combination_type: TournamentCombinationType,
        rank: str | None,
    ) -> None:
        if combination_type == TournamentCombinationType.FOUR_OF_A_KIND:
            if rank not in FOUR_OF_A_KIND_RANKS:
                raise ResultInvalidCombinationRankError
        elif rank is not None:
            raise ResultInvalidCombinationRankError

    async def _require_editable_tournament_for_actor(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        actor_role: object,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise ResultTournamentNotFoundError
        if not can_edit_open_tournament_for_actor(
            actor_role=actor_role,
            tournament_status=tournament.status,
            tournament_date=tournament.date,
            business_date=self._tournament_day(),
            admin_current_day_only=False,
        ):
            raise TournamentResultsEditingUnavailableError
        return tournament

    def _tournament_day(self) -> date:
        return resolve_tournament_day(self.clock, self.tournament_day_start_hour)


tournament_combination_service = TournamentCombinationService(SessionFactory)
