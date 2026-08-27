from __future__ import annotations

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
            for tournament_type in await TournamentTypeRepository(session).list_active_real_types()
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
