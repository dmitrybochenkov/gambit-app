import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament
from app.db.models.enums import (
    KnockoutMode,
    TournamentPublicationDestination,
    TournamentPublicationType,
    TournamentStatus,
)
from app.db.repositories.tournament_combination_repository import TournamentCombinationRepository
from app.db.repositories.tournament_photo_repository import TournamentPhotoRepository
from app.db.repositories.tournament_publication_repository import TournamentPublicationRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.results import (
    SchedulePublicationView,
    TournamentCombinationView,
    TournamentPhotoView,
    TournamentPublicationDestinationView,
    TournamentPublicationKnockoutView,
    TournamentPublicationPlaceView,
    TournamentPublicationResultView,
    TournamentPublicationSummaryView,
    TournamentResultPublicationView,
    TournamentResultsView,
)
from app.services.dto.tournaments import TournamentScheduleDetailsView
from app.services.result_service import ResultService, ResultTournamentNotFoundError
from app.services.tournament_service import build_tournament_schedule_details, tournament_view


class TournamentPublicationNoDestinationsError(ValueError):
    pass


class TournamentPublicationAlreadyPublishedError(ValueError):
    pass


class TournamentPublicationUnavailableError(ValueError):
    pass


class TournamentPublicationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
        club_chat_id: int | None = settings.telegram_club_chat_id,
        club_channel_id: int | None = settings.telegram_club_channel_id,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour
        self.club_chat_id = club_chat_id
        self.club_channel_id = club_channel_id

    async def get_result_publication_preview(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultPublicationView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if tournament is None:
                raise ResultTournamentNotFoundError
            if tournament.status != TournamentStatus.CLOSED or tournament.tournament_fund is None:
                raise TournamentPublicationUnavailableError
            destinations = self._destinations()
            if not destinations:
                raise TournamentPublicationNoDestinationsError
            view = await self._result_publication_view(session, tournament, destinations)
            if all(destination.already_published for destination in view.destinations):
                raise TournamentPublicationAlreadyPublishedError
            return view

    async def get_result_publication_content_preview(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultPublicationView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if tournament is None:
                raise ResultTournamentNotFoundError
            if tournament.status != TournamentStatus.CLOSED or tournament.tournament_fund is None:
                raise TournamentPublicationUnavailableError
            return await self._result_publication_view(session, tournament, self._destinations())

    async def get_pre_close_result_publication_preview(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        tournament_fund: int,
    ) -> TournamentResultPublicationView:
        calculated_results = await ResultService(
            self.session_factory,
            clock=self.clock,
            tournament_day_start_hour=self.tournament_day_start_hour,
        ).preview_tournament_close(
            superadmin_telegram_id=superadmin_telegram_id,
            tournament_id=tournament_id,
            tournament_fund=tournament_fund,
        )

        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if tournament is None:
                raise ResultTournamentNotFoundError

            return await self._result_publication_view(
                session,
                tournament,
                self._destinations(),
                calculated_results=calculated_results,
                tournament_fund=tournament_fund,
            )

    async def get_schedule_publication_preview(
        self,
        superadmin_telegram_id: int,
    ) -> SchedulePublicationView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            destinations = self._destinations()
            if not destinations:
                raise TournamentPublicationNoDestinationsError
            tournaments = await TournamentRepository(session).list_upcoming_active(
                resolve_tournament_day(self.clock, self.tournament_day_start_hour),
            )
            items = [
                await build_tournament_schedule_details(session, tournament)
                for tournament in tournaments[:5]
            ]
            content_hash = self._content_hash(
                {
                    "type": "schedule",
                    "tournaments": [self._schedule_tournament_payload(item) for item in items],
                }
            )
            destinations = await self._publication_destinations(
                session,
                publication_type=TournamentPublicationType.SCHEDULE,
                content_hash=content_hash,
                destinations=destinations,
            )
            if all(destination.already_published for destination in destinations):
                raise TournamentPublicationAlreadyPublishedError
            return SchedulePublicationView(
                tournaments=items,
                destinations=destinations,
                content_hash=content_hash,
            )

    async def record_publication_success(
        self,
        superadmin_telegram_id: int,
        *,
        tournament_id: int | None,
        publication_type: TournamentPublicationType,
        destination_type: TournamentPublicationDestination,
        destination_chat_id: int,
        content_hash: str,
        telegram_message_id: int | None,
    ) -> None:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, superadmin_telegram_id)
            try:
                await TournamentPublicationRepository(session).add(
                    tournament_id=tournament_id,
                    publication_type=publication_type,
                    destination_type=destination_type,
                    destination_chat_id=destination_chat_id,
                    content_hash=content_hash,
                    telegram_message_id=telegram_message_id,
                    published_by_user_id=actor.id,
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()

    def delivery_summary(
        self,
        *,
        sent: list[str],
        failed: list[str],
        already_published: list[str],
    ) -> TournamentPublicationSummaryView:
        destination_order = [
            TournamentPublicationDestination.GROUP.value,
            TournamentPublicationDestination.CHANNEL.value,
        ]
        results = []
        for destination in destination_order:
            if destination in sent:
                results.append(TournamentPublicationResultView(destination, sent=True))
            elif destination in failed:
                results.append(
                    TournamentPublicationResultView(destination, sent=False, failed=True)
                )
            elif destination in already_published:
                results.append(
                    TournamentPublicationResultView(
                        destination,
                        sent=False,
                        already_published=True,
                    )
                )
        return TournamentPublicationSummaryView(results=results)

    async def _result_publication_view(
        self,
        session: AsyncSession,
        tournament: Tournament,
        destinations: list[tuple[TournamentPublicationDestination, int]],
        *,
        calculated_results: TournamentResultsView | None = None,
        tournament_fund: int | None = None,
    ) -> TournamentResultPublicationView:
        result_rows = await TournamentResultRepository(session).list_with_users(tournament.id)
        combinations = await TournamentCombinationRepository(session).list_with_users(tournament.id)
        photos = await TournamentPhotoRepository(session).list_for_tournament(tournament.id)
        calculated_players = (
            {player.player_id: player for player in calculated_results.players}
            if calculated_results is not None
            else {}
        )
        effective_fund = (
            tournament_fund
            if tournament_fund is not None
            else int(tournament.tournament_fund or 0)
        )
        places = [
            TournamentPublicationPlaceView(
                place=row.result.place,
                display_name=row.user.display_name,
                total_points=(
                    calculated_players[row.user.id].total_points
                    if calculated_results is not None
                    else row.result.total_points
                ),
            )
            for row in result_rows
            if row.result.place is not None
        ]
        places.sort(key=lambda item: item.place)
        top_knockouters: list[TournamentPublicationKnockoutView] = []
        knockout_mode = await self._knockout_mode(session, tournament)
        if knockout_mode in {KnockoutMode.SMALL, KnockoutMode.SMALL_BIG}:
            knockout_rows = [
                row
                for row in result_rows
                if row.result.knockouts_count + row.result.big_knockouts_count > 0
            ]
            knockout_rows.sort(
                key=lambda row: (
                    -(row.result.knockouts_count + row.result.big_knockouts_count),
                    -row.result.big_knockouts_count,
                    row.user.display_name_normalized,
                    row.user.id,
                )
            )
            top_knockouters = [
                TournamentPublicationKnockoutView(
                    display_name=row.user.display_name,
                    knockouts_count=row.result.knockouts_count,
                    big_knockouts_count=row.result.big_knockouts_count,
                )
                for row in knockout_rows[:3]
            ]
        combination_views = [
            TournamentCombinationView(
                id=row.combination.id,
                tournament_id=row.combination.tournament_id,
                player_id=row.user.id,
                display_name=row.user.display_name,
                combination_type=row.combination.combination_type,
                rank=row.combination.rank,
            )
            for row in combinations
        ]
        photo_views = [
            TournamentPhotoView(
                id=photo.id,
                tournament_id=photo.tournament_id,
                telegram_file_id=photo.telegram_file_id,
                telegram_file_unique_id=photo.telegram_file_unique_id,
                position=photo.position,
            )
            for photo in photos
        ]
        content_hash = self._content_hash(
            {
                "type": "results",
                "tournament_id": tournament.id,
                "fund": effective_fund,
                "places": [
                    {
                        "place": place.place,
                        "name": place.display_name,
                        "points": str(place.total_points),
                    }
                    for place in places
                ],
                "knockouts": [
                    {
                        "name": row.display_name,
                        "ko": row.knockouts_count,
                        "bko": row.big_knockouts_count,
                    }
                    for row in top_knockouters
                ],
                "combinations": [
                    {
                        "id": row.id,
                        "player_id": row.player_id,
                        "type": row.combination_type,
                    }
                    for row in combination_views
                ],
                "photos": [photo.telegram_file_unique_id for photo in photo_views],
            }
        )
        destination_views = await self._publication_destinations(
            session,
            publication_type=TournamentPublicationType.RESULTS,
            content_hash=content_hash,
            destinations=destinations,
        )
        return TournamentResultPublicationView(
            tournament=tournament_view(tournament),
            tournament_fund=effective_fund,
            places=places,
            top_knockouters=top_knockouters,
            combinations=combination_views,
            photos=photo_views,
            destinations=destination_views,
            content_hash=content_hash,
        )

    async def _publication_destinations(
        self,
        session: AsyncSession,
        *,
        publication_type: TournamentPublicationType,
        content_hash: str,
        destinations: list[tuple[TournamentPublicationDestination, int]],
    ) -> list[TournamentPublicationDestinationView]:
        repository = TournamentPublicationRepository(session)
        return [
            TournamentPublicationDestinationView(
                destination_type=destination.value,
                chat_id=chat_id,
                already_published=await repository.exists(
                    publication_type=publication_type,
                    destination_type=destination,
                    destination_chat_id=chat_id,
                    content_hash=content_hash,
                ),
            )
            for destination, chat_id in destinations
        ]

    def _schedule_tournament_payload(
        self,
        tournament: TournamentScheduleDetailsView,
    ) -> dict[str, object]:
        economy = tournament.economy
        return {
            "id": tournament.id,
            "date": tournament.date.isoformat(),
            "name": tournament.tournament_type_name,
            "description": tournament.description,
            "economy": (
                {
                    "entry_fee": economy.entry_fee,
                    "entry_stack": economy.entry_stack,
                    "addon_fee": economy.addon_fee,
                    "addon_stack": economy.addon_stack,
                    "rebuys": [
                        {"fee": rebuy.fee, "stack": rebuy.stack} for rebuy in economy.rebuys
                    ],
                }
                if economy is not None
                else None
            ),
        }

    async def _knockout_mode(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> KnockoutMode:
        from app.db.repositories.tournament_type_repository import TournamentTypeRepository

        rule = await TournamentTypeRepository(session).get_rule_capabilities(
            tournament.tournament_type_id
        )
        if rule is None:
            return KnockoutMode.NONE
        return rule.knockout_mode

    def _destinations(self) -> list[tuple[TournamentPublicationDestination, int]]:
        destinations = []
        if self.club_chat_id is not None:
            destinations.append((TournamentPublicationDestination.GROUP, self.club_chat_id))
        if self.club_channel_id is not None:
            destinations.append((TournamentPublicationDestination.CHANNEL, self.club_channel_id))
        return destinations

    @staticmethod
    def _content_hash(payload: object) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


tournament_publication_service = TournamentPublicationService(SessionFactory)
