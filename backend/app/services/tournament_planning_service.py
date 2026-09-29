from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament, TournamentType, WeeklyTournamentTemplate
from app.db.models.enums import TournamentStatus
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_type_repository import (
    TournamentTypeConfigRecord,
    TournamentTypeRepository,
)
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.schedules import TournamentRebuyView
from app.services.dto.tournaments import (
    SuperadminOpenTournamentListItemView,
    SuperadminOpenTournamentPageView,
    SuperadminTournamentHubView,
    TournamentCalendarApprovalPreviewView,
    TournamentCalendarAutofillPreviewView,
    TournamentCalendarCreatePreviewView,
    TournamentCalendarDayView,
    TournamentCalendarDeletePreviewView,
    TournamentCalendarDraftCommand,
    TournamentCalendarDraftItem,
    TournamentCalendarFormatDetailView,
    TournamentCalendarMonthTypeView,
    TournamentCalendarMonthView,
    TournamentCalendarTypeChangePreviewView,
    TournamentCalendarTypeOptionView,
    TournamentCalendarWeekDetailView,
    TournamentCalendarWeekView,
    TournamentCancellationNotificationView,
    TournamentEconomyView,
    TournamentFormatAvailabilityResultView,
    TournamentFormatView,
    TournamentRulesView,
    TournamentView,
    WeeklyTemplateDayView,
    WeeklyTemplateTypeView,
    WeeklyTemplateView,
)
from app.services.pagination import pagination_service
from app.services.tournament_service import tournament_view
from app.services.weekday_tournament_rotation import (
    WeekdayTournamentRotation,
    weekday_tournament_rotation,
)


class CalendarTournamentDateAlreadyExistsError(ValueError):
    pass


class CalendarDefaultTournamentTypeNotFoundError(ValueError):
    pass


class CalendarWeeklyPlanIntegrityError(ValueError):
    pass


class CalendarAutofillDraftInvalidError(ValueError):
    pass


class CalendarTournamentTypeNotFoundError(ValueError):
    pass


class CalendarTournamentNotFoundError(ValueError):
    pass


class CalendarTournamentNotEditableError(ValueError):
    pass


class CalendarWeekNotEmptyError(ValueError):
    pass


class CalendarNoUnapprovedTournamentsError(ValueError):
    pass


class WeeklyTemplateInvalidError(ValueError):
    pass


class WeeklyTemplateTournamentTypeNotAllowedError(ValueError):
    pass


LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE = "legacy_unknown"
SUPERADMIN_OPEN_TOURNAMENT_PAGE_SIZE = 6
REAL_TOURNAMENT_TYPE_CODES = (
    "bounty_v3",
    "classic_v3",
    "freezeout_v2",
    "deep_stack_v2",
    "white_party",
    "mystery_bounty",
    "boss_bounty",
    "main_ko",
    "slow_blinds",
    "satellite",
    "black_party",
    "month_main",
    "satellite_v2",
    "mystery_quest",
)


@dataclass(frozen=True)
class WeeklyTournamentPlanItem:
    date: date
    tournament_type_id: int


@dataclass(frozen=True)
class WeeklyTournamentPlan:
    tournaments: tuple[WeeklyTournamentPlanItem, ...]

    @classmethod
    def create(
        cls,
        *,
        target_dates: tuple[date, ...],
        tournament_type_ids: tuple[int, ...],
    ) -> WeeklyTournamentPlan:
        if len(target_dates) != len(tournament_type_ids):
            raise CalendarWeeklyPlanIntegrityError
        plan = cls(
            tournaments=tuple(
                WeeklyTournamentPlanItem(
                    date=tournament_date,
                    tournament_type_id=tournament_type_id,
                )
                for tournament_date, tournament_type_id in zip(
                    target_dates,
                    tournament_type_ids,
                    strict=True,
                )
            )
        )
        plan.validate()
        return plan

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(item.date for item in self.tournaments)

    def validate(self) -> None:
        if not self.tournaments:
            raise CalendarWeeklyPlanIntegrityError
        dates = [item.date for item in self.tournaments]
        if len(set(dates)) != len(dates):
            raise CalendarWeeklyPlanIntegrityError
        monday = dates[0].fromordinal(dates[0].toordinal() - dates[0].weekday())
        valid_dates = {monday.fromordinal(monday.toordinal() + offset) for offset in range(7)}
        has_date_outside_week = any(tournament_date not in valid_dates for tournament_date in dates)
        if dates != sorted(dates) or has_date_outside_week:
            raise CalendarWeeklyPlanIntegrityError


class TournamentPlanningService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        weekday_rotation: WeekdayTournamentRotation = weekday_tournament_rotation,
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.weekday_rotation = weekday_rotation
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def get_superadmin_tournament_hub(
        self,
        actor_user_id: int,
    ) -> SuperadminTournamentHubView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            open_count = await TournamentRepository(session).count_active_on_or_before(
                resolve_tournament_day(self.clock, self.tournament_day_start_hour)
            )
            return SuperadminTournamentHubView(open_tournaments_count=open_count)

    async def list_open_tournaments_for_superadmin(
        self,
        actor_user_id: int,
        *,
        page: int,
        page_size: int = SUPERADMIN_OPEN_TOURNAMENT_PAGE_SIZE,
    ) -> SuperadminOpenTournamentPageView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            tournaments = await TournamentRepository(session).list_active_on_or_before(
                resolve_tournament_day(self.clock, self.tournament_day_start_hour)
            )
            items = [
                SuperadminOpenTournamentListItemView(tournament=tournament_view(tournament))
                for tournament in tournaments
            ]
            return pagination_service.paginate(items, page=page, page_size=page_size)

    async def get_calendar_month(
        self,
        actor_user_id: int,
        *,
        year: int | None = None,
        month: int | None = None,
    ) -> TournamentCalendarMonthView:
        today = self.clock.today()
        target_year = year or today.year
        target_month = month or today.month
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            return await self._calendar_month_view(session, target_year, target_month)

    async def get_calendar_week(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarWeekDetailView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            return await self._calendar_week_view(session, year, month, row_number)

    async def list_calendar_tournament_type_options(
        self,
        actor_user_id: int,
    ) -> list[TournamentCalendarTypeOptionView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            return await self._calendar_type_options(session)

    async def get_weekly_template(self, actor_user_id: int) -> WeeklyTemplateView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            return await self._weekly_template_view(session)

    async def list_weekly_template_add_options(
        self,
        actor_user_id: int,
        *,
        selected_tournament_type_ids: tuple[int, ...],
    ) -> list[TournamentCalendarTypeOptionView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            selected = set(selected_tournament_type_ids)
            return [
                option
                for option in await self._calendar_type_options(session)
                if option.id not in selected
            ]

    async def replace_weekly_template(
        self,
        actor_user_id: int,
        *,
        tournament_type_ids_by_weekday: dict[int, tuple[int, ...]],
    ) -> WeeklyTemplateView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                normalized = {
                    weekday: tuple(type_ids)
                    for weekday, type_ids in tournament_type_ids_by_weekday.items()
                }
                if any(weekday not in range(7) for weekday in normalized):
                    raise WeeklyTemplateInvalidError
                if not any(normalized.values()):
                    raise WeeklyTemplateInvalidError
                if any(len(type_ids) != len(set(type_ids)) for type_ids in normalized.values()):
                    raise WeeklyTemplateInvalidError

                repository = TournamentRepository(session)
                current = await repository.list_active_weekly_templates()
                current_ids_by_weekday = {
                    weekday: {row.tournament_type_id for row in current if row.weekday == weekday}
                    for weekday in range(7)
                }
                type_repository = TournamentTypeRepository(session)
                creatable_ids = {item.id for item in await self._calendar_type_options(session)}
                for weekday, type_ids in normalized.items():
                    for tournament_type_id in type_ids:
                        tournament_type = await type_repository.get_by_id(tournament_type_id)
                        if tournament_type is None:
                            raise WeeklyTemplateInvalidError
                        if (
                            tournament_type_id not in creatable_ids
                            and tournament_type_id not in current_ids_by_weekday[weekday]
                        ):
                            raise WeeklyTemplateTournamentTypeNotAllowedError

                rows = [
                    WeeklyTournamentTemplate(
                        weekday=weekday,
                        tournament_type_id=tournament_type_id,
                        rotation_order=index,
                        is_active=True,
                    )
                    for weekday in range(7)
                    for index, tournament_type_id in enumerate(normalized.get(weekday, ()), start=1)
                ]
                await repository.replace_active_weekly_templates(rows)
                await session.flush()
                view = await self._weekly_template_view(session)
                await session.commit()
                return view
            except Exception:
                await session.rollback()
                raise

    async def list_tournament_formats(self, actor_user_id: int) -> list[TournamentFormatView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            rows = await TournamentTypeRepository(session).list_active_real_types()
            return [self._tournament_format_view(row) for row in rows]

    async def get_tournament_format(
        self,
        actor_user_id: int,
        tournament_type_id: int,
    ) -> TournamentFormatAvailabilityResultView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            tournament_type = await TournamentTypeRepository(session).get_by_id(tournament_type_id)
            if (
                tournament_type is None
                or tournament_type.code == LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE
            ):
                raise CalendarTournamentTypeNotFoundError
            templates = await TournamentRepository(session).list_active_weekly_templates()
            return TournamentFormatAvailabilityResultView(
                tournament_format=self._tournament_format_view(tournament_type),
                affected_weekdays=tuple(
                    sorted(
                        {
                            row.weekday
                            for row in templates
                            if row.tournament_type_id == tournament_type_id
                        }
                    )
                ),
            )

    async def set_tournament_format_creatable(
        self,
        actor_user_id: int,
        *,
        tournament_type_id: int,
        is_creatable: bool,
    ) -> TournamentFormatAvailabilityResultView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                type_repository = TournamentTypeRepository(session)
                tournament_type = await type_repository.get_by_id(tournament_type_id)
                if (
                    tournament_type is None
                    or tournament_type.code == LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE
                ):
                    raise CalendarTournamentTypeNotFoundError
                repository = TournamentRepository(session)
                templates = await repository.list_active_weekly_templates()
                affected_weekdays = tuple(
                    sorted(
                        {
                            row.weekday
                            for row in templates
                            if row.tournament_type_id == tournament_type_id
                        }
                    )
                )
                tournament_type.is_creatable = is_creatable
                if not is_creatable and affected_weekdays:
                    remaining_by_weekday = {
                        weekday: [
                            row
                            for row in templates
                            if row.weekday == weekday
                            and row.tournament_type_id != tournament_type_id
                        ]
                        for weekday in range(7)
                    }
                    replacement = [
                        WeeklyTournamentTemplate(
                            weekday=weekday,
                            tournament_type_id=row.tournament_type_id,
                            rotation_order=index,
                            is_active=True,
                        )
                        for weekday in range(7)
                        for index, row in enumerate(
                            remaining_by_weekday[weekday],
                            start=1,
                        )
                    ]
                    await repository.replace_active_weekly_templates(replacement)
                await session.flush()
                await session.commit()
                return TournamentFormatAvailabilityResultView(
                    tournament_format=self._tournament_format_view(tournament_type),
                    affected_weekdays=affected_weekdays,
                )
            except Exception:
                await session.rollback()
                raise

    async def get_calendar_format_detail(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        tournament_type_id: int,
    ) -> TournamentCalendarFormatDetailView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            month_view = await self._calendar_month_view(session, year, month)
            if tournament_type_id not in {
                tournament_type.id for tournament_type in month_view.tournament_types
            }:
                raise CalendarTournamentTypeNotFoundError
            config = await TournamentTypeRepository(session).get_config(tournament_type_id)
            if config is None:
                raise CalendarTournamentTypeNotFoundError
            return _calendar_format_detail_view(config)

    async def get_calendar_create_preview(
        self,
        actor_user_id: int,
        *,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentCalendarCreatePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            if await TournamentRepository(session).exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
            tournament_type = await self._calendar_type_option(session, tournament_type_id)
            return TournamentCalendarCreatePreviewView(
                tournament_date=tournament_date,
                tournament_type=tournament_type,
            )

    async def create_calendar_tournament(
        self,
        actor_user_id: int,
        *,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                if await TournamentRepository(session).exists_for_date(tournament_date):
                    raise CalendarTournamentDateAlreadyExistsError
                tournament_type = await self._calendar_type_option(session, tournament_type_id)
                season = await SeasonRepository(session).get_for_date(tournament_date)
                if season is None:
                    raise CalendarWeeklyPlanIntegrityError
                tournament = await TournamentRepository(session).add(
                    Tournament(
                        season_id=season.id,
                        tournament_type_id=tournament_type_id,
                        scoring_config_id=season.scoring_config_id,
                        date=tournament_date,
                        status=TournamentStatus.ACTIVE,
                        registration_open=False,
                    )
                )
                view = TournamentView(
                    id=tournament.id,
                    date=tournament.date,
                    tournament_type_id=tournament.tournament_type_id,
                    tournament_type_name=tournament_type.name,
                    tournament_type_code=tournament_type.code,
                    tournament_type_calendar_code=tournament_type.calendar_code,
                    registration_open=tournament.registration_open,
                )
                await session.commit()
                return view
            except IntegrityError as exc:
                await session.rollback()
                raise CalendarTournamentDateAlreadyExistsError from exc
            except Exception:
                await session.rollback()
                raise

    async def get_calendar_autofill_preview(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarAutofillPreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            week = await self._calendar_week_view(session, year, month, row_number)
            if not week.is_empty:
                raise CalendarWeekNotEmptyError
            target_dates = tuple(day.date for day in week.days)
            plan = await self._build_plan_for_dates(session, target_dates)
            return await self._autofill_preview(
                session,
                plan,
                week_start=target_dates[0],
                week_end=target_dates[-1],
            )

    async def create_calendar_autofill_week(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarAutofillPreviewView:
        preview = await self.get_calendar_autofill_preview(
            actor_user_id,
            year=year,
            month=month,
            row_number=row_number,
        )
        return await self._create_calendar_autofill_draft(
            actor_user_id,
            TournamentCalendarDraftCommand(
                year=year,
                month=month,
                row_number=row_number,
                tournaments=tuple(
                    TournamentCalendarDraftItem(
                        tournament_date=item.tournament_date,
                        tournament_type_id=item.tournament_type.id,
                    )
                    for item in preview.tournaments
                ),
            ),
            allow_existing_template_types=True,
        )

    async def create_calendar_autofill_draft(
        self,
        actor_user_id: int,
        command: TournamentCalendarDraftCommand,
    ) -> TournamentCalendarAutofillPreviewView:
        return await self._create_calendar_autofill_draft(
            actor_user_id,
            command,
            allow_existing_template_types=False,
        )

    async def _create_calendar_autofill_draft(
        self,
        actor_user_id: int,
        command: TournamentCalendarDraftCommand,
        *,
        allow_existing_template_types: bool,
    ) -> TournamentCalendarAutofillPreviewView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                week = await self._calendar_week_view(
                    session,
                    command.year,
                    command.month,
                    command.row_number,
                )
                if not week.is_empty:
                    raise CalendarWeekNotEmptyError

                authoritative_dates = tuple(day.date for day in week.days)
                requested_items = tuple(
                    sorted(command.tournaments, key=lambda item: item.tournament_date)
                )
                requested_dates = tuple(item.tournament_date for item in requested_items)
                if not requested_dates or len(requested_dates) != len(set(requested_dates)):
                    raise CalendarAutofillDraftInvalidError
                if any(item.tournament_type_id <= 0 for item in requested_items):
                    raise CalendarAutofillDraftInvalidError
                if any(item_date not in authoritative_dates for item_date in requested_dates):
                    raise CalendarAutofillDraftInvalidError

                repository = TournamentRepository(session)
                for tournament_date in authoritative_dates:
                    if await repository.exists_for_date(tournament_date):
                        raise CalendarTournamentDateAlreadyExistsError

                creatable_ids = {option.id for option in await self._calendar_type_options(session)}
                if not allow_existing_template_types and any(
                    item.tournament_type_id not in creatable_ids for item in requested_items
                ):
                    raise CalendarTournamentTypeNotFoundError

                plan = WeeklyTournamentPlan.create(
                    target_dates=requested_dates,
                    tournament_type_ids=tuple(item.tournament_type_id for item in requested_items),
                )
                preview = await self._autofill_preview(
                    session,
                    plan,
                    week_start=authoritative_dates[0],
                    week_end=authoritative_dates[-1],
                )
                season_repository = SeasonRepository(session)
                for item in plan.tournaments:
                    season = await season_repository.get_for_date(item.date)
                    if season is None:
                        raise CalendarWeeklyPlanIntegrityError
                    await repository.add(
                        Tournament(
                            season_id=season.id,
                            tournament_type_id=item.tournament_type_id,
                            scoring_config_id=season.scoring_config_id,
                            date=item.date,
                            status=TournamentStatus.ACTIVE,
                            registration_open=False,
                        )
                    )
                await session.commit()
                return preview
            except IntegrityError as exc:
                await session.rollback()
                raise CalendarTournamentDateAlreadyExistsError from exc
            except Exception:
                await session.rollback()
                raise

    async def get_week_approval_preview(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarApprovalPreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            week = await self._calendar_week_view(session, year, month, row_number)
            tournaments = tuple(
                day.tournament
                for day in week.days
                if day.tournament is not None and not day.tournament.registration_open
            )
            if not tournaments:
                raise CalendarNoUnapprovedTournamentsError
            return TournamentCalendarApprovalPreviewView(
                week_start=week.week_start,
                week_end=week.week_end,
                tournaments=tournaments,
            )

    async def approve_calendar_week(
        self,
        actor_user_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarApprovalPreviewView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                week = await self._calendar_week_view(session, year, month, row_number)
                tournament_ids = [
                    day.tournament.id
                    for day in week.days
                    if day.tournament is not None and not day.tournament.registration_open
                ]
                if not tournament_ids:
                    raise CalendarNoUnapprovedTournamentsError
                repository = TournamentRepository(session)
                approved: list[TournamentView] = []
                for tournament_id in tournament_ids:
                    tournament = await repository.get_by_id(tournament_id)
                    if tournament is None or tournament.status != TournamentStatus.ACTIVE:
                        raise CalendarTournamentNotFoundError
                    tournament.registration_open = True
                    approved.append(tournament_view(tournament))
                await session.commit()
                return TournamentCalendarApprovalPreviewView(
                    week_start=week.week_start,
                    week_end=week.week_end,
                    tournaments=tuple(approved),
                )
            except Exception:
                await session.rollback()
                raise

    async def get_type_change_preview(
        self,
        actor_user_id: int,
        *,
        tournament_id: int,
        new_tournament_type_id: int,
    ) -> TournamentCalendarTypeChangePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            tournament = await self._require_future_calendar_tournament(session, tournament_id)
            tournament_type = await self._calendar_type_option(session, new_tournament_type_id)
            return TournamentCalendarTypeChangePreviewView(
                tournament=tournament_view(tournament),
                new_type=tournament_type,
            )

    async def change_calendar_tournament_type(
        self,
        actor_user_id: int,
        *,
        tournament_id: int,
        new_tournament_type_id: int,
    ) -> TournamentView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                tournament = await self._require_future_calendar_tournament(session, tournament_id)
                if await self._has_tournament_fact_data(session, tournament.id):
                    raise CalendarTournamentNotEditableError
                tournament_type = await self._calendar_type_option(
                    session,
                    new_tournament_type_id,
                )
                tournament.tournament_type_id = new_tournament_type_id
                await session.commit()
                return TournamentView(
                    id=tournament.id,
                    date=tournament.date,
                    tournament_type_id=tournament.tournament_type_id,
                    tournament_type_name=tournament_type.name,
                    tournament_type_code=tournament_type.code,
                    tournament_type_calendar_code=tournament_type.calendar_code,
                    registration_open=tournament.registration_open,
                )
            except Exception:
                await session.rollback()
                raise

    async def get_calendar_delete_preview(
        self,
        actor_user_id: int,
        *,
        tournament_id: int,
    ) -> TournamentCalendarDeletePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_user_id)
            tournament = await self._require_future_calendar_tournament(session, tournament_id)
            counts = await TournamentRegistrationRepository(session).count_by_tournament_ids(
                (tournament.id,)
            )
            return TournamentCalendarDeletePreviewView(
                tournament=tournament_view(tournament),
                registrations_count=counts.get(tournament.id, 0),
            )

    async def delete_calendar_tournament(
        self,
        actor_user_id: int,
        *,
        tournament_id: int,
    ) -> tuple[TournamentView, tuple[TournamentCancellationNotificationView, ...]]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_user_id)
                tournament = await self._require_future_calendar_tournament(session, tournament_id)
                if await self._has_tournament_fact_data(session, tournament.id):
                    raise CalendarTournamentNotEditableError
                view = tournament_view(tournament)
                registered_users = await TournamentRegistrationRepository(
                    session
                ).list_active_registered_users(tournament.id)
                notifications = tuple(
                    TournamentCancellationNotificationView(
                        telegram_id=user.telegram_id,
                        tournament=view,
                    )
                    for user in registered_users
                    if user.telegram_id is not None and user.telegram_id > 0
                )
                registration_repository = TournamentRegistrationRepository(session)
                await registration_repository.delete_by_tournament(tournament.id)
                await TournamentRepository(session).delete(tournament)
                await session.commit()
                return view, notifications
            except Exception:
                await session.rollback()
                raise

    async def _calendar_month_view(
        self,
        session: AsyncSession,
        year: int,
        month: int,
        *,
        enable_adjacent_actions: bool = False,
    ) -> TournamentCalendarMonthView:
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        month_start = min(day for week in weeks for day in week)
        month_end = max(day for week in weeks for day in week)
        tournaments = await TournamentRepository(session).list_between_dates(
            month_start,
            month_end,
        )
        counts = await TournamentRegistrationRepository(session).count_by_tournament_ids(
            tuple(tournament.id for tournament in tournaments)
        )
        tournaments_by_date = {tournament.date: tournament for tournament in tournaments}
        business_date = resolve_tournament_day(self.clock, self.tournament_day_start_hour)
        return TournamentCalendarMonthView(
            year=year,
            month=month,
            weeks=tuple(
                TournamentCalendarWeekView(
                    row_number=index,
                    days=tuple(
                        self._calendar_day_view(
                            day,
                            in_month=day.month == month,
                            tournament=tournaments_by_date.get(day),
                            registrations_count=counts.get(
                                tournaments_by_date[day].id,
                                0,
                            )
                            if day in tournaments_by_date
                            else 0,
                            business_date=business_date,
                            enable_adjacent_actions=enable_adjacent_actions,
                        )
                        for day in week
                    ),
                )
                for index, week in enumerate(weeks, start=1)
            ),
            tournament_types=_calendar_month_tournament_types(
                [
                    tournament
                    for tournament in tournaments
                    if tournament.date.year == year and tournament.date.month == month
                ]
            ),
        )

    async def _calendar_week_view(
        self,
        session: AsyncSession,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarWeekDetailView:
        if row_number <= 0:
            raise CalendarWeeklyPlanIntegrityError
        month_view = await self._calendar_month_view(
            session,
            year,
            month,
            enable_adjacent_actions=True,
        )
        try:
            week = month_view.weeks[row_number - 1]
        except IndexError as exc:
            raise CalendarWeeklyPlanIntegrityError from exc
        days = week.days
        if len(days) != 7:
            raise CalendarWeeklyPlanIntegrityError
        return TournamentCalendarWeekDetailView(
            year=year,
            month=month,
            row_number=row_number,
            week_start=days[0].date,
            week_end=days[-1].date,
            days=days,
            has_tournaments=any(day.tournament is not None for day in days),
            has_unapproved_tournaments=any(
                day.tournament is not None and not day.tournament.registration_open for day in days
            ),
            is_empty=all(day.tournament is None for day in days),
        )

    def _calendar_day_view(
        self,
        day: date,
        *,
        in_month: bool,
        tournament: Tournament | None,
        registrations_count: int,
        business_date: date,
        enable_adjacent_actions: bool,
    ) -> TournamentCalendarDayView:
        return TournamentCalendarDayView(
            date=day,
            in_month=in_month,
            tournament=tournament_view(tournament) if tournament is not None else None,
            registrations_count=registrations_count,
            editable_future=(
                (in_month or enable_adjacent_actions)
                and tournament is not None
                and tournament.status == TournamentStatus.ACTIVE
                and tournament.date > business_date
            ),
        )

    async def _calendar_type_options(
        self,
        session: AsyncSession,
    ) -> list[TournamentCalendarTypeOptionView]:
        return [
            TournamentCalendarTypeOptionView(
                id=tournament_type.id,
                code=tournament_type.code,
                name=tournament_type.name,
                calendar_code=tournament_type.calendar_code,
            )
            for tournament_type in await TournamentTypeRepository(
                session
            ).list_creatable_real_types()
            if tournament_type.code in REAL_TOURNAMENT_TYPE_CODES
        ]

    async def _calendar_type_option(
        self,
        session: AsyncSession,
        tournament_type_id: int,
    ) -> TournamentCalendarTypeOptionView:
        options = await self._calendar_type_options(session)
        for option in options:
            if option.id == tournament_type_id:
                return option
        raise CalendarTournamentTypeNotFoundError

    async def _calendar_real_type_option(
        self,
        session: AsyncSession,
        tournament_type_id: int,
    ) -> TournamentCalendarTypeOptionView:
        config = await TournamentTypeRepository(session).get_real_config(
            tournament_type_id,
            legacy_unknown_code=LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
        )
        if config is None:
            raise CalendarTournamentTypeNotFoundError
        return TournamentCalendarTypeOptionView(
            id=config.tournament_type.id,
            code=config.tournament_type.code,
            name=config.tournament_type.name,
            calendar_code=config.tournament_type.calendar_code,
        )

    async def _autofill_preview(
        self,
        session: AsyncSession,
        plan: WeeklyTournamentPlan,
        *,
        week_start: date | None = None,
        week_end: date | None = None,
    ) -> TournamentCalendarAutofillPreviewView:
        items = []
        for item in plan.tournaments:
            tournament_type = await self._calendar_real_type_option(
                session,
                item.tournament_type_id,
            )
            items.append(
                TournamentCalendarCreatePreviewView(
                    tournament_date=item.date,
                    tournament_type=tournament_type,
                )
            )
        return TournamentCalendarAutofillPreviewView(
            week_start=week_start or plan.dates[0],
            week_end=week_end or plan.dates[-1],
            tournaments=tuple(items),
        )

    async def _require_future_calendar_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise CalendarTournamentNotFoundError
        business_date = resolve_tournament_day(self.clock, self.tournament_day_start_hour)
        if tournament.status != TournamentStatus.ACTIVE or tournament.date <= business_date:
            raise CalendarTournamentNotEditableError
        return tournament

    async def _has_tournament_fact_data(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> bool:
        # Future calendar deletion is only allowed before play starts. Registrations are
        # deleted explicitly; factual game rows are protected by this direct relation check.
        return await TournamentRepository(session).has_fact_data(tournament_id)

    async def _build_plan_for_dates(
        self,
        session: AsyncSession,
        target_dates: tuple[date, ...],
    ) -> WeeklyTournamentPlan:
        tournament_repository = TournamentRepository(session)
        for tournament_date in target_dates:
            if await tournament_repository.exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
        planned_dates, tournament_type_ids = await self._default_weekly_tournament_type_ids(
            session, target_dates
        )
        return WeeklyTournamentPlan.create(
            target_dates=planned_dates,
            tournament_type_ids=tournament_type_ids,
        )

    async def _default_weekly_tournament_type_ids(
        self,
        session: AsyncSession,
        target_dates: tuple[date, ...],
    ) -> tuple[tuple[date, ...], tuple[int, ...]]:
        repository = TournamentRepository(session)
        templates = await repository.list_active_weekly_templates()
        templates_by_weekday = {
            weekday: [template for template in templates if template.weekday == weekday]
            for weekday in range(7)
        }
        if not templates:
            raise CalendarDefaultTournamentTypeNotFoundError

        planned_dates: list[date] = []
        tournament_type_ids: list[int] = []
        for target_date in target_dates:
            weekday_templates = templates_by_weekday[target_date.weekday()]
            if not weekday_templates:
                continue
            rotation_codes = rotation_codes_for_templates(weekday_templates)
            selected_code = (
                rotation_codes[0]
                if len(rotation_codes) == 1
                else await self._default_rotation_tournament_type_code(
                    repository,
                    target_date,
                    rotation_codes,
                )
            )
            template = next(
                (item for item in weekday_templates if item.tournament_type.code == selected_code),
                None,
            )
            if template is None:
                raise CalendarDefaultTournamentTypeNotFoundError
            planned_dates.append(target_date)
            tournament_type_ids.append(template.tournament_type_id)

        if not planned_dates:
            raise CalendarDefaultTournamentTypeNotFoundError
        return tuple(planned_dates), tuple(tournament_type_ids)

    async def _default_rotation_tournament_type_code(
        self,
        repository: TournamentRepository,
        target_date: date,
        rotation_codes: tuple[str, ...],
    ) -> str:
        latest = await repository.get_latest_rotation_tournament_before(
            target_date,
            rotation_codes,
        )
        if latest is not None and latest.tournament_type is not None:
            return self.weekday_rotation.next_code_after(
                latest.tournament_type.code,
                rotation_codes,
            )
        return self.weekday_rotation.fallback_code_for(target_date, rotation_codes)

    async def _weekly_template_view(self, session: AsyncSession) -> WeeklyTemplateView:
        rows = await TournamentRepository(session).list_active_weekly_templates()
        return WeeklyTemplateView(
            days=tuple(
                WeeklyTemplateDayView(
                    weekday=weekday,
                    tournament_types=tuple(
                        WeeklyTemplateTypeView(
                            id=row.tournament_type.id,
                            code=row.tournament_type.code,
                            name=row.tournament_type.name,
                            calendar_code=row.tournament_type.calendar_code,
                            is_creatable=row.tournament_type.is_creatable,
                        )
                        for row in rows
                        if row.weekday == weekday
                    ),
                )
                for weekday in range(7)
            )
        )

    @staticmethod
    def _tournament_format_view(tournament_type: TournamentType) -> TournamentFormatView:
        return TournamentFormatView(
            id=tournament_type.id,
            code=tournament_type.code,
            name=tournament_type.name,
            calendar_code=tournament_type.calendar_code,
            is_creatable=tournament_type.is_creatable,
        )


def _calendar_format_detail_view(
    config: TournamentTypeConfigRecord,
) -> TournamentCalendarFormatDetailView:
    return TournamentCalendarFormatDetailView(
        id=config.tournament_type.id,
        name=config.tournament_type.name,
        description=config.tournament_type.description,
        economy=(
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
        ),
        rules=(
            TournamentRulesView(
                points_multiplier=config.rule.points_multiplier,
                prize_place_multiplier=config.rule.prize_place_multiplier,
                prize_place_multiplier_places=config.rule.prize_place_multiplier_places,
                knockout_mode=config.rule.knockout_mode.value,
                supports_bonus_points=config.rule.supports_bonus_points,
            )
            if config.rule is not None
            else None
        ),
    )


def _calendar_month_tournament_types(
    tournaments: list[Tournament],
) -> tuple[TournamentCalendarMonthTypeView, ...]:
    seen_type_ids: set[int] = set()
    items: list[TournamentCalendarMonthTypeView] = []
    for tournament in sorted(tournaments, key=lambda item: (item.date, item.id)):
        tournament_type = tournament.tournament_type
        if tournament_type.id in seen_type_ids:
            continue
        seen_type_ids.add(tournament_type.id)
        items.append(
            TournamentCalendarMonthTypeView(
                id=tournament_type.id,
                name=tournament_type.name,
                short_name=tournament_type.short_name,
                calendar_code=tournament_type.calendar_code,
            )
        )
    return tuple(items)


def rotation_codes_for_templates(
    templates: list[WeeklyTournamentTemplate],
) -> tuple[str, ...]:
    if len(templates) == 1:
        code = templates[0].tournament_type.code
        if code == LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE:
            raise CalendarDefaultTournamentTypeNotFoundError
        return (code,)
    rotation_templates = sorted(
        templates,
        key=lambda template: template.rotation_order or 0,
    )
    if any(template.rotation_order is None for template in rotation_templates):
        raise CalendarDefaultTournamentTypeNotFoundError
    codes = tuple(template.tournament_type.code for template in rotation_templates)
    if not codes or LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE in codes:
        raise CalendarDefaultTournamentTypeNotFoundError
    return codes


tournament_planning_service = TournamentPlanningService(SessionFactory)
