from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import TournamentStatus
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import ActiveUserRequiredError, access_policy
from app.services.dto.schedules import TournamentRebuyView
from app.services.dto.tournaments import (
    PlayerTournamentView,
    TournamentEconomyView,
    TournamentRulesView,
    TournamentScheduleDetailsView,
    TournamentView,
)


class TournamentRegistrationNotAllowedError(ValueError):
    pass


class TournamentScheduleNotAllowedError(ValueError):
    pass


class TournamentUnavailableError(ValueError):
    pass


class TournamentCancellationUnavailableError(ValueError):
    pass


class TournamentRegistrationAlreadyCheckedInError(ValueError):
    pass


class TournamentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def get_upcoming_schedule(
        self,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRepository(session).list_active_between_dates(
                start_date=week_start,
                end_date=week_end,
                registration_open_only=True,
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_schedule_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentScheduleNotAllowedError from exc
            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRepository(session).list_active_between_dates(
                start_date=week_start,
                end_date=week_end,
                registration_open_only=True,
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_schedule_tournament_details_for_player(
        self,
        telegram_id: int,
        tournament_id: int,
        from_date: date | None = None,
    ) -> TournamentScheduleDetailsView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentScheduleNotAllowedError from exc

            week_start, week_end = self._current_week_range(from_date)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if (
                tournament is None
                or tournament.status != TournamentStatus.ACTIVE
                or tournament.date < week_start
                or tournament.date > week_end
                or not tournament.registration_open
            ):
                raise TournamentUnavailableError

            return await build_tournament_schedule_details(session, tournament)

    async def get_registration_options_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc
            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRepository(session).list_active_between_dates(
                start_date=week_start,
                end_date=week_end,
                registration_open_only=True,
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_player_upcoming_registrations(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc
            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRegistrationRepository(
                session
            ).list_registered_between_dates(
                player_id=player.id,
                start_date=week_start,
                end_date=week_end,
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_current_week_tournaments_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[PlayerTournamentView]:
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentScheduleNotAllowedError from exc

            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRepository(session).list_active_between_dates(
                start_date=week_start,
                end_date=week_end,
                registration_open_only=True,
            )
            return await self._player_tournament_views(session, player.id, tournaments)

    async def get_current_week_tournament_for_player(
        self,
        telegram_id: int,
        tournament_id: int,
        from_date: date | None = None,
    ) -> PlayerTournamentView:
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentScheduleNotAllowedError from exc

            week_start, week_end = self._current_week_range(from_date)
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if (
                tournament is None
                or tournament.status != TournamentStatus.ACTIVE
                or tournament.date < week_start
                or tournament.date > week_end
                or not tournament.registration_open
            ):
                raise TournamentUnavailableError

            views = await self._player_tournament_views(session, player.id, [tournament])
            return views[0]

    async def get_current_week_registrations_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[PlayerTournamentView]:
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc
            week_start, week_end = self._current_week_range(from_date)
            tournaments = await TournamentRegistrationRepository(
                session
            ).list_registered_between_dates(
                player_id=player.id,
                start_date=week_start,
                end_date=week_end,
            )
            return await self._player_tournament_views(session, player.id, tournaments)

    async def register_player_for_tournaments(
        self,
        telegram_id: int,
        tournament_ids: list[int],
        from_date: date | None = None,
    ) -> list[TournamentView]:
        unique_tournament_ids = list(dict.fromkeys(tournament_ids))
        if not unique_tournament_ids:
            return []

        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc

            week_start, week_end = self._current_week_range(from_date)
            tournament_repository = TournamentRepository(session)
            registration_repository = TournamentRegistrationRepository(session)
            selected: list[tuple[Tournament, TournamentRegistration | None]] = []

            for tournament_id in unique_tournament_ids:
                tournament = await tournament_repository.get_by_id(tournament_id)
                if (
                    tournament is None
                    or tournament.status != TournamentStatus.ACTIVE
                    or tournament.date < week_start
                    or tournament.date > week_end
                    or not tournament.registration_open
                ):
                    raise TournamentUnavailableError

                registration = await registration_repository.get(
                    tournament.id,
                    player.id,
                )
                selected.append((tournament, registration))

            for tournament, registration in selected:
                if registration is None:
                    await registration_repository.add(
                        tournament_id=tournament.id,
                        player_id=player.id,
                    )

            await session.commit()
            return [tournament_view(tournament) for tournament, _ in selected]

    async def cancel_player_tournament_registrations(
        self,
        telegram_id: int,
        tournament_ids: list[int],
        from_date: date | None = None,
    ) -> list[TournamentView]:
        unique_tournament_ids = list(dict.fromkeys(tournament_ids))
        if not unique_tournament_ids:
            return []

        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc

            week_start, week_end = self._current_week_range(from_date)
            tournament_repository = TournamentRepository(session)
            registration_repository = TournamentRegistrationRepository(session)
            tournaments_by_id: dict[int, Tournament] = {}
            for tournament_id in unique_tournament_ids:
                tournament = await tournament_repository.get_by_id(tournament_id)
                if (
                    tournament is None
                    or tournament.status != TournamentStatus.ACTIVE
                    or tournament.date < week_start
                    or tournament.date > week_end
                ):
                    raise TournamentCancellationUnavailableError
                tournaments_by_id[tournament.id] = tournament

                registration = await registration_repository.get(tournament.id, player.id)
                if registration is None:
                    continue
                checked_in = await TournamentResultRepository(
                    session
                ).exists_for_tournament_and_player(
                    tournament.id,
                    player.id,
                )
                if checked_in:
                    raise TournamentRegistrationAlreadyCheckedInError
                await registration_repository.delete(registration)

            await session.commit()
            return [
                tournament_view(tournaments_by_id[tournament_id])
                for tournament_id in unique_tournament_ids
            ]

    def _current_week_range(self, from_date: date | None = None) -> tuple[date, date]:
        business_date = (
            from_date
            if from_date is not None
            else resolve_tournament_day(self.clock, self.tournament_day_start_hour)
        )
        week_start = business_date - timedelta(days=business_date.weekday())
        return week_start, week_start + timedelta(days=6)

    async def _player_tournament_views(
        self,
        session: AsyncSession,
        player_id: int,
        tournaments: list[Tournament],
    ) -> list[PlayerTournamentView]:
        registration_repository = TournamentRegistrationRepository(session)
        result_repository = TournamentResultRepository(session)
        views: list[PlayerTournamentView] = []
        for tournament in tournaments:
            registration = await registration_repository.get(tournament.id, player_id)
            checked_in = await result_repository.exists_for_tournament_and_player(
                tournament.id,
                player_id,
            )
            details = await build_tournament_schedule_details(session, tournament)
            is_registered = registration is not None
            views.append(
                PlayerTournamentView(
                    id=tournament.id,
                    date=tournament.date,
                    tournament_type_code=details.tournament_type_code,
                    tournament_type_name=details.tournament_type_name,
                    description=details.description,
                    registration_open=tournament.registration_open,
                    is_registered=is_registered,
                    can_register=tournament.registration_open and not is_registered,
                    can_cancel_registration=is_registered and not checked_in,
                    my_registration_status=(
                        "checked_in" if checked_in else "registered" if is_registered else "none"
                    ),
                    economy=details.economy,
                    rules=details.rules,
                )
            )
        return views


tournament_service = TournamentService(SessionFactory)


def tournament_view(tournament: Tournament) -> TournamentView:
    return TournamentView(
        id=tournament.id,
        date=tournament.date,
        tournament_type_id=tournament.tournament_type_id,
        tournament_type_name=tournament.tournament_type.name,
        tournament_type_code=tournament.tournament_type.code,
        registration_open=tournament.registration_open,
    )


async def build_tournament_schedule_details(
    session: AsyncSession,
    tournament: Tournament,
) -> TournamentScheduleDetailsView:
    config = await TournamentTypeRepository(session).get_config(tournament.tournament_type_id)
    if config is None:
        raise TournamentUnavailableError
    economy = (
        TournamentEconomyView(
            entry_fee=config.economy.entry_fee,
            entry_stack=config.economy.entry_stack,
            addon_fee=config.economy.addon_fee,
            addon_stack=config.economy.addon_stack,
            rebuys=[
                TournamentRebuyView(fee=rebuy.fee, stack=rebuy.stack) for rebuy in config.rebuys
            ],
        )
        if config.economy is not None
        else None
    )
    rules = (
        TournamentRulesView(
            points_multiplier=config.rule.points_multiplier,
            prize_place_multiplier=config.rule.prize_place_multiplier,
            prize_place_multiplier_places=config.rule.prize_place_multiplier_places,
            knockout_mode=config.rule.knockout_mode.value,
            supports_bonus_points=config.rule.supports_bonus_points,
        )
        if config.rule is not None
        else None
    )
    return TournamentScheduleDetailsView(
        id=tournament.id,
        date=tournament.date,
        tournament_type_name=config.tournament_type.name,
        tournament_type_code=config.tournament_type.code,
        description=config.tournament_type.description,
        economy=economy,
        rules=rules,
    )
