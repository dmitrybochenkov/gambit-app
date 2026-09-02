from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament, WeeklyTournamentTemplate
from app.db.models.enums import TournamentStatus
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.session import SessionFactory
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.schedules import (
    TournamentPlanDayEditView,
    TournamentPlanItemView,
    TournamentRebuyView,
    TournamentTypeDetailView,
    TournamentTypeOptionView,
    WeeklyTournamentFactItemView,
    WeeklyTournamentFactView,
    WeeklyTournamentPlanView,
)
from app.services.dto.tournaments import (
    SuperadminOpenTournamentListItemView,
    SuperadminOpenTournamentPageView,
    SuperadminTournamentHubView,
    TournamentCalendarApprovalPreviewView,
    TournamentCalendarAutofillPreviewView,
    TournamentCalendarCreatePreviewView,
    TournamentCalendarDayView,
    TournamentCalendarDeletePreviewView,
    TournamentCalendarMonthView,
    TournamentCalendarTypeChangePreviewView,
    TournamentCalendarTypeOptionView,
    TournamentCalendarWeekDetailView,
    TournamentCalendarWeekView,
    TournamentCancellationNotificationView,
    TournamentView,
)
from app.services.pagination import pagination_service
from app.services.sunday_tournament_rotation import (
    SundayTournamentRotation,
    sunday_tournament_rotation,
)
from app.services.tournament_service import tournament_view


class CalendarPlanStaleError(ValueError):
    pass


class CalendarTournamentDateAlreadyExistsError(ValueError):
    pass


class CalendarDefaultTournamentTypeNotFoundError(ValueError):
    pass


class CalendarWeeklyPlanEmptyError(ValueError):
    pass


class CalendarWeeklyPlanIntegrityError(ValueError):
    pass


class CalendarTournamentDateNotInPlanError(ValueError):
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


class WeeklyPlanningStatus(StrEnum):
    BLOCKED_BY_ACTIVE_WEEK = "blocked_by_active_week"
    READY = "ready"


class LatestWeekState(StrEnum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


WEDNESDAY_WEEKDAY = 2
SUNDAY_WEEKDAY = 6
WEEKLY_PLAYING_WEEKDAYS = (2, 3, 4, 5, 6)
LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE = "legacy_unknown"
SUPERADMIN_OPEN_TOURNAMENT_PAGE_SIZE = 6
REAL_TOURNAMENT_TYPE_CODES = (
    "bounty_v2",
    "classic_v2",
    "freezeout_v2",
    "deep_stack",
    "white_party",
    "mystery_bounty",
    "boss_bounty",
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

    @classmethod
    def from_fsm(cls, raw_items: object) -> WeeklyTournamentPlan:
        if not isinstance(raw_items, list):
            raise CalendarPlanStaleError
        items: list[WeeklyTournamentPlanItem] = []
        try:
            for item in raw_items:
                if not isinstance(item, dict):
                    raise CalendarPlanStaleError
                items.append(
                    WeeklyTournamentPlanItem(
                        date=date.fromisoformat(str(item["date"])),
                        tournament_type_id=int(item["tournament_type_id"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise CalendarPlanStaleError from error
        plan = cls(tournaments=tuple(items))
        plan.validate()
        return plan

    def to_fsm(self) -> list[dict[str, object]]:
        return [
            {
                "date": item.date.isoformat(),
                "tournament_type_id": item.tournament_type_id,
            }
            for item in self.tournaments
        ]

    def item_by_date(self, tournament_date: date) -> WeeklyTournamentPlanItem:
        for item in self.tournaments:
            if item.date == tournament_date:
                return item
        raise CalendarTournamentDateNotInPlanError

    def with_tournament_type(
        self,
        tournament_date: date,
        tournament_type_id: int,
    ) -> WeeklyTournamentPlan:
        self.item_by_date(tournament_date)
        return WeeklyTournamentPlan(
            tournaments=tuple(
                WeeklyTournamentPlanItem(
                    date=item.date,
                    tournament_type_id=(
                        tournament_type_id
                        if item.date == tournament_date
                        else item.tournament_type_id
                    ),
                )
                for item in self.tournaments
            )
        )

    def without_date(self, tournament_date: date) -> WeeklyTournamentPlan:
        self.item_by_date(tournament_date)
        if len(self.tournaments) == 1:
            raise CalendarWeeklyPlanEmptyError
        updated = WeeklyTournamentPlan(
            tournaments=tuple(item for item in self.tournaments if item.date != tournament_date)
        )
        updated.validate()
        return updated

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(item.date for item in self.tournaments)

    @property
    def tournament_type_ids(self) -> tuple[int, ...]:
        return tuple(item.tournament_type_id for item in self.tournaments)

    def validate(self) -> None:
        if not self.tournaments:
            raise CalendarWeeklyPlanIntegrityError
        dates = [item.date for item in self.tournaments]
        if len(set(dates)) != len(dates):
            raise CalendarWeeklyPlanIntegrityError
        wednesday = wednesday_for_week(dates[0])
        valid_dates = set(week_dates_for(wednesday))
        has_date_outside_week = any(tournament_date not in valid_dates for tournament_date in dates)
        if dates != sorted(dates) or has_date_outside_week:
            raise CalendarWeeklyPlanIntegrityError


@dataclass(frozen=True)
class WeeklyPlanningCheckView:
    status: WeeklyPlanningStatus
    plan: WeeklyTournamentPlanView | None = None
    schedule: WeeklyTournamentFactView | None = None


class TournamentPlanningService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        sunday_rotation: SundayTournamentRotation = sunday_tournament_rotation,
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.sunday_rotation = sunday_rotation
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def get_superadmin_tournament_hub(
        self,
        actor_telegram_id: int,
    ) -> SuperadminTournamentHubView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            open_count = await TournamentRepository(session).count_active_on_or_before(
                resolve_tournament_day(self.clock, self.tournament_day_start_hour)
            )
            return SuperadminTournamentHubView(open_tournaments_count=open_count)

    async def list_open_tournaments_for_superadmin(
        self,
        actor_telegram_id: int,
        *,
        page: int,
        page_size: int = SUPERADMIN_OPEN_TOURNAMENT_PAGE_SIZE,
    ) -> SuperadminOpenTournamentPageView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            tournaments = await TournamentRepository(session).list_active_on_or_before(
                resolve_tournament_day(self.clock, self.tournament_day_start_hour)
            )
            items = [
                SuperadminOpenTournamentListItemView(tournament=tournament_view(tournament))
                for tournament in tournaments
            ]
            return pagination_service.paginate(items, page=page, page_size=page_size)

    async def build_next_week_plan(
        self,
        actor_telegram_id: int,
        today: date | None = None,
    ) -> WeeklyTournamentPlanView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            plan = await self._build_next_week_plan(session, business_date)
            return await self.plan_view(session, plan)

    async def inspect_next_week(
        self,
        actor_telegram_id: int,
        today: date | None = None,
    ) -> WeeklyPlanningCheckView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._inspect_next_week_from_db(session, business_date)

    async def inspect_after_tournament_close(
        self,
        actor_telegram_id: int,
        closed_tournament_date: date,
    ) -> WeeklyPlanningCheckView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._inspect_next_week_from_db(
                session,
                self.clock.today(),
            )

    async def list_tournament_type_options(
        self,
        actor_telegram_id: int,
    ) -> list[TournamentTypeOptionView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._list_tournament_type_options(session)

    async def get_calendar_month(
        self,
        actor_telegram_id: int,
        *,
        year: int | None = None,
        month: int | None = None,
    ) -> TournamentCalendarMonthView:
        today = self.clock.today()
        target_year = year or today.year
        target_month = month or today.month
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._calendar_month_view(session, target_year, target_month)

    async def get_calendar_week(
        self,
        actor_telegram_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarWeekDetailView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._calendar_week_view(session, year, month, row_number)

    async def list_calendar_tournament_type_options(
        self,
        actor_telegram_id: int,
    ) -> list[TournamentCalendarTypeOptionView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._calendar_type_options(session)

    async def get_calendar_create_preview(
        self,
        actor_telegram_id: int,
        *,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentCalendarCreatePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            if await TournamentRepository(session).exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
            tournament_type = await self._calendar_type_option(session, tournament_type_id)
            return TournamentCalendarCreatePreviewView(
                tournament_date=tournament_date,
                tournament_type=tournament_type,
            )

    async def create_calendar_tournament(
        self,
        actor_telegram_id: int,
        *,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
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
        actor_telegram_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarAutofillPreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            week = await self._calendar_week_view(session, year, month, row_number)
            if not week.is_empty:
                raise CalendarWeekNotEmptyError
            target_dates = tuple(
                day.date for day in week.days if day.date.weekday() in WEEKLY_PLAYING_WEEKDAYS
            )
            if len(target_dates) != len(WEEKLY_PLAYING_WEEKDAYS):
                raise CalendarWeeklyPlanIntegrityError
            plan = await self._build_plan_for_dates(session, target_dates)
            return await self._autofill_preview(session, plan)

    async def create_calendar_autofill_week(
        self,
        actor_telegram_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarAutofillPreviewView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
                week = await self._calendar_week_view(session, year, month, row_number)
                if not week.is_empty:
                    raise CalendarWeekNotEmptyError
                target_dates = tuple(
                    day.date for day in week.days if day.date.weekday() in WEEKLY_PLAYING_WEEKDAYS
                )
                if len(target_dates) != len(WEEKLY_PLAYING_WEEKDAYS):
                    raise CalendarWeeklyPlanIntegrityError
                plan = await self._build_plan_for_dates(session, target_dates)
                preview = await self._autofill_preview(session, plan)
                season_repository = SeasonRepository(session)
                tournament_repository = TournamentRepository(session)
                for item in plan.tournaments:
                    season = await season_repository.get_for_date(item.date)
                    if season is None:
                        raise CalendarWeeklyPlanIntegrityError
                    await tournament_repository.add(
                        Tournament(
                            season_id=season.id,
                            tournament_type_id=item.tournament_type_id,
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
        actor_telegram_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarApprovalPreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
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
        actor_telegram_id: int,
        *,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarApprovalPreviewView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
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
        actor_telegram_id: int,
        *,
        tournament_id: int,
        new_tournament_type_id: int,
    ) -> TournamentCalendarTypeChangePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            tournament = await self._require_future_calendar_tournament(session, tournament_id)
            tournament_type = await self._calendar_type_option(session, new_tournament_type_id)
            return TournamentCalendarTypeChangePreviewView(
                tournament=tournament_view(tournament),
                new_type=tournament_type,
            )

    async def change_calendar_tournament_type(
        self,
        actor_telegram_id: int,
        *,
        tournament_id: int,
        new_tournament_type_id: int,
    ) -> TournamentView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
                tournament = await self._require_future_calendar_tournament(session, tournament_id)
                await self._calendar_type_option(session, new_tournament_type_id)
                tournament.tournament_type_id = new_tournament_type_id
                await session.commit()
                return tournament_view(tournament)
            except Exception:
                await session.rollback()
                raise

    async def get_calendar_delete_preview(
        self,
        actor_telegram_id: int,
        *,
        tournament_id: int,
    ) -> TournamentCalendarDeletePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
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
        actor_telegram_id: int,
        *,
        tournament_id: int,
    ) -> tuple[TournamentView, tuple[TournamentCancellationNotificationView, ...]]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
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

    async def get_day_edit_options(
        self,
        actor_telegram_id: int,
        plan: WeeklyTournamentPlan,
        tournament_date: date,
    ) -> TournamentPlanDayEditView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            plan.item_by_date(tournament_date)
            return TournamentPlanDayEditView(
                tournament_date=tournament_date,
                tournament_types=await self._list_tournament_type_options(session),
            )

    async def get_plan_view(
        self,
        actor_telegram_id: int,
        plan: WeeklyTournamentPlan,
    ) -> WeeklyTournamentPlanView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self.plan_view(session, plan)

    async def update_plan_day_type(
        self,
        actor_telegram_id: int,
        plan: WeeklyTournamentPlan,
        tournament_date: date,
        tournament_type_id: int,
    ) -> WeeklyTournamentPlanView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            if await self._tournament_type_detail(session, tournament_type_id) is None:
                raise CalendarTournamentTypeNotFoundError
            updated_plan = plan.with_tournament_type(tournament_date, tournament_type_id)
            return await self.plan_view(session, updated_plan)

    async def remove_plan_day(
        self,
        actor_telegram_id: int,
        plan: WeeklyTournamentPlan,
        tournament_date: date,
    ) -> WeeklyTournamentPlanView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            updated_plan = plan.without_date(tournament_date)
            return await self.plan_view(session, updated_plan)

    async def create_weekly_schedule(
        self,
        actor_telegram_id: int,
        plan: WeeklyTournamentPlan,
    ) -> WeeklyTournamentPlanView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, actor_telegram_id)
                planning = await self._inspect_next_week_from_db(session, self.clock.today())
                if (
                    planning.status != WeeklyPlanningStatus.READY
                    or planning.plan is None
                    or not set(plan.dates).issubset(
                        {item.date for item in planning.plan.tournaments}
                    )
                ):
                    raise CalendarTournamentDateAlreadyExistsError
                await self._validate_plan_for_apply(session, plan)
                season_repository = SeasonRepository(session)
                tournament_repository = TournamentRepository(session)
                for item in plan.tournaments:
                    season = await season_repository.get_for_date(item.date)
                    if season is None:
                        raise CalendarWeeklyPlanIntegrityError
                    await tournament_repository.add(
                        Tournament(
                            season_id=season.id,
                            tournament_type_id=item.tournament_type_id,
                            date=item.date,
                            status=TournamentStatus.ACTIVE,
                            registration_open=False,
                        )
                    )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise CalendarTournamentDateAlreadyExistsError from exc
            except Exception:
                await session.rollback()
                raise
            return await self.plan_view(session, plan)

    async def _build_next_week_plan(
        self,
        session: AsyncSession,
        today: date,
    ) -> WeeklyTournamentPlan:
        target_dates = await self._next_available_target_dates(session, today)
        return await self._build_plan_for_dates(session, target_dates)

    async def _calendar_month_view(
        self,
        session: AsyncSession,
        year: int,
        month: int,
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
                        )
                        for day in week
                    ),
                )
                for index, week in enumerate(weeks, start=1)
            ),
        )

    async def _calendar_week_view(
        self,
        session: AsyncSession,
        year: int,
        month: int,
        row_number: int,
    ) -> TournamentCalendarWeekDetailView:
        month_view = await self._calendar_month_view(session, year, month)
        try:
            week = month_view.weeks[row_number - 1]
        except IndexError as exc:
            raise CalendarWeeklyPlanIntegrityError from exc
        days = tuple(day for day in week.days if day.in_month)
        if not days:
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
    ) -> TournamentCalendarDayView:
        return TournamentCalendarDayView(
            date=day,
            in_month=in_month,
            tournament=tournament_view(tournament) if tournament is not None else None,
            registrations_count=registrations_count,
            editable_future=(
                in_month
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

    async def _autofill_preview(
        self,
        session: AsyncSession,
        plan: WeeklyTournamentPlan,
    ) -> TournamentCalendarAutofillPreviewView:
        items = []
        for item in plan.tournaments:
            items.append(
                TournamentCalendarCreatePreviewView(
                    tournament_date=item.date,
                    tournament_type=await self._calendar_type_option(
                        session,
                        item.tournament_type_id,
                    ),
                )
            )
        return TournamentCalendarAutofillPreviewView(
            week_start=plan.dates[0],
            week_end=plan.dates[-1],
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

    async def _next_available_target_dates(
        self,
        session: AsyncSession,
        today: date,
    ) -> tuple[date, ...]:
        latest_tournament = await TournamentRepository(session).get_latest_tournament()
        if latest_tournament is None:
            return next_complete_game_week(today)
        latest_week_dates = week_dates_for(latest_tournament.date)
        latest_week_tournaments = await TournamentRepository(session).list_by_dates(
            latest_week_dates
        )
        if latest_week_state(latest_week_tournaments) == LatestWeekState.IN_PROGRESS:
            raise CalendarTournamentDateAlreadyExistsError
        return next_complete_game_week(latest_week_dates[-1])

    async def _inspect_next_week_from_db(
        self,
        session: AsyncSession,
        today: date,
    ) -> WeeklyPlanningCheckView:
        latest_tournament = await TournamentRepository(session).get_latest_tournament()
        if latest_tournament is None:
            return await self._inspect_target_dates(session, next_complete_game_week(today))

        latest_week_dates = week_dates_for(latest_tournament.date)
        latest_week_tournaments = await TournamentRepository(session).list_by_dates(
            latest_week_dates
        )
        if latest_week_state(latest_week_tournaments) == LatestWeekState.IN_PROGRESS:
            return WeeklyPlanningCheckView(
                status=WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK,
                schedule=self._fact_view(latest_week_dates, latest_week_tournaments),
            )

        target_dates = next_complete_game_week(latest_week_dates[-1])
        return await self._inspect_target_dates(session, target_dates)

    async def _inspect_target_dates(
        self,
        session: AsyncSession,
        target_dates: tuple[date, ...],
    ) -> WeeklyPlanningCheckView:
        existing_tournaments = await TournamentRepository(session).list_by_dates(target_dates)
        if existing_tournaments:
            return WeeklyPlanningCheckView(
                status=WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK,
                schedule=self._fact_view(target_dates, existing_tournaments),
            )
        plan = await self._build_plan_for_dates(session, target_dates)
        return WeeklyPlanningCheckView(
            status=WeeklyPlanningStatus.READY,
            plan=await self.plan_view(session, plan),
        )

    async def _build_plan_for_dates(
        self,
        session: AsyncSession,
        target_dates: tuple[date, ...],
    ) -> WeeklyTournamentPlan:
        tournament_repository = TournamentRepository(session)
        for tournament_date in target_dates:
            if await tournament_repository.exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
        tournament_type_ids = await self._default_weekly_tournament_type_ids(session, target_dates)
        return WeeklyTournamentPlan.create(
            target_dates=target_dates,
            tournament_type_ids=tournament_type_ids,
        )

    async def _validate_plan_for_apply(
        self,
        session: AsyncSession,
        plan: WeeklyTournamentPlan,
    ) -> None:
        plan.validate()
        tournament_repository = TournamentRepository(session)
        for item in plan.tournaments:
            if await tournament_repository.exists_for_date(item.date):
                raise CalendarTournamentDateAlreadyExistsError
            if await SeasonRepository(session).get_for_date(item.date) is None:
                raise CalendarWeeklyPlanIntegrityError
            if await self._tournament_type_detail(session, item.tournament_type_id) is None:
                raise CalendarTournamentTypeNotFoundError

    async def _default_weekly_tournament_type_ids(
        self,
        session: AsyncSession,
        target_dates: tuple[date, ...],
    ) -> tuple[int, ...]:
        repository = TournamentRepository(session)
        templates = await repository.list_active_weekly_templates()
        templates_by_weekday = {
            weekday: [template for template in templates if template.weekday == weekday]
            for weekday in WEEKLY_PLAYING_WEEKDAYS
        }
        if any(not weekday_templates for weekday_templates in templates_by_weekday.values()):
            raise CalendarDefaultTournamentTypeNotFoundError

        tournament_type_ids: list[int] = []
        for target_date in target_dates:
            if target_date.weekday() == SUNDAY_WEEKDAY:
                sunday_rotation_codes = sunday_rotation_codes_for_templates(
                    templates_by_weekday[SUNDAY_WEEKDAY]
                )
                sunday_type_code = await self._default_sunday_tournament_type_code(
                    repository,
                    target_date,
                    sunday_rotation_codes,
                )
                sunday_template = next(
                    (
                        template
                        for template in templates_by_weekday[SUNDAY_WEEKDAY]
                        if template.tournament_type.code == sunday_type_code
                    ),
                    None,
                )
                if sunday_template is None:
                    raise CalendarDefaultTournamentTypeNotFoundError
                tournament_type_ids.append(sunday_template.tournament_type_id)
                continue

            weekday_templates = templates_by_weekday[target_date.weekday()]
            if len(weekday_templates) != 1:
                raise CalendarDefaultTournamentTypeNotFoundError
            template = weekday_templates[0]
            if template.tournament_type.code == LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE:
                raise CalendarDefaultTournamentTypeNotFoundError
            tournament_type_ids.append(template.tournament_type_id)

        return tuple(tournament_type_ids)

    async def _default_sunday_tournament_type_code(
        self,
        repository: TournamentRepository,
        target_date: date,
        rotation_codes: tuple[str, ...],
    ) -> str:
        latest_sunday = await repository.get_latest_sunday_rotation_tournament_before(
            target_date,
            rotation_codes,
        )
        if latest_sunday is not None and latest_sunday.tournament_type is not None:
            return self.sunday_rotation.next_code_after(
                latest_sunday.tournament_type.code,
                rotation_codes,
            )
        return self.sunday_rotation.fallback_code_for(target_date, rotation_codes)

    async def plan_view(
        self,
        session: AsyncSession,
        plan: WeeklyTournamentPlan,
    ) -> WeeklyTournamentPlanView:
        items: list[TournamentPlanItemView] = []
        for item in plan.tournaments:
            tournament_type = await self._tournament_type_detail(
                session,
                item.tournament_type_id,
            )
            if tournament_type is None:
                raise CalendarTournamentTypeNotFoundError
            items.append(
                TournamentPlanItemView(
                    date=item.date,
                    tournament_type=tournament_type,
                )
            )
        return WeeklyTournamentPlanView(
            week_start=plan.dates[0],
            week_end=plan.dates[-1],
            tournaments=items,
        )

    def _fact_view(
        self,
        target_dates: tuple[date, ...],
        tournaments: list[Tournament],
    ) -> WeeklyTournamentFactView:
        return WeeklyTournamentFactView(
            week_start=target_dates[0],
            week_end=target_dates[-1],
            tournaments=[
                WeeklyTournamentFactItemView(
                    date=tournament.date,
                    tournament_type_name=(
                        tournament.tournament_type.name
                        if tournament.tournament_type is not None
                        else None
                    ),
                )
                for tournament in sorted(tournaments, key=lambda item: item.date)
            ],
        )

    async def _list_tournament_type_options(
        self,
        session: AsyncSession,
    ) -> list[TournamentTypeOptionView]:
        return [
            TournamentTypeOptionView(id=tournament_type.id, name=tournament_type.name)
            for tournament_type in await TournamentTypeRepository(
                session
            ).list_creatable_real_types()
        ]

    async def _tournament_type_detail(
        self,
        session: AsyncSession,
        tournament_type_id: int,
    ) -> TournamentTypeDetailView | None:
        config = await TournamentTypeRepository(session).get_active_real_config(
            tournament_type_id,
            legacy_unknown_code=LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
        )
        if config is None:
            return None
        return TournamentTypeDetailView(
            id=config.tournament_type.id,
            name=config.tournament_type.name,
            description=config.tournament_type.description,
            entry_fee=config.economy.entry_fee,
            entry_stack=config.economy.entry_stack,
            addon_fee=config.economy.addon_fee,
            addon_stack=config.economy.addon_stack,
            rebuys=[
                TournamentRebuyView(fee=rebuy.fee, stack=rebuy.stack) for rebuy in config.rebuys
            ],
            knockout_mode=(config.rule.knockout_mode.value if config.rule is not None else "none"),
        )


def next_complete_game_week(today: date) -> tuple[date, ...]:
    days_until_wednesday = (WEDNESDAY_WEEKDAY - today.weekday()) % 7
    if days_until_wednesday == 0:
        days_until_wednesday = 7
    wednesday = today.fromordinal(today.toordinal() + days_until_wednesday)
    return tuple(
        wednesday.fromordinal(wednesday.toordinal() + weekday - WEDNESDAY_WEEKDAY)
        for weekday in WEEKLY_PLAYING_WEEKDAYS
    )


def wednesday_for_week(tournament_date: date) -> date:
    if tournament_date.weekday() not in WEEKLY_PLAYING_WEEKDAYS:
        raise CalendarWeeklyPlanIntegrityError
    return tournament_date.fromordinal(
        tournament_date.toordinal() - (tournament_date.weekday() - WEDNESDAY_WEEKDAY)
    )


def week_dates_for(tournament_date: date) -> tuple[date, ...]:
    wednesday = wednesday_for_week(tournament_date)
    return tuple(
        wednesday.fromordinal(wednesday.toordinal() + weekday - WEDNESDAY_WEEKDAY)
        for weekday in WEEKLY_PLAYING_WEEKDAYS
    )


def latest_week_state(tournaments: list[Tournament]) -> LatestWeekState:
    if any(tournament.status == TournamentStatus.ACTIVE for tournament in tournaments):
        return LatestWeekState.IN_PROGRESS
    return LatestWeekState.FINISHED


def sunday_rotation_codes_for_templates(
    templates: list[WeeklyTournamentTemplate],
) -> tuple[str, ...]:
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
