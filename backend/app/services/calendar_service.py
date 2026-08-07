from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import AdminPrompt, Tournament
from app.db.models.enums import (
    AdminPromptKind,
    AdminPromptStatus,
    KnockoutMode,
    TournamentStatus,
)
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto import (
    AdminPromptView,
    TournamentPromptDayEditView,
    TournamentPromptItemView,
    TournamentPromptView,
    TournamentRebuyView,
    TournamentTypeDetailView,
    TournamentTypeOptionView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
)
from app.services.sunday_tournament_rotation import (
    SundayTournamentRotation,
    SundayTournamentRotationDateError,
    sunday_tournament_rotation,
)

logger = logging.getLogger(__name__)


class CalendarPromptAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    EDIT = "edit"


class CalendarPromptNotFoundError(ValueError):
    pass


class CalendarPromptAlreadyResolvedError(ValueError):
    pass


class CalendarPromptUnsupportedError(ValueError):
    pass


class CalendarPromptInvalidPayloadError(ValueError):
    pass


class CalendarTournamentDateAlreadyExistsError(ValueError):
    pass


class CalendarSundayTournamentDateError(ValueError):
    pass


class CalendarSundayTournamentTypeNotFoundError(ValueError):
    pass


class CalendarDefaultTournamentTypeNotFoundError(ValueError):
    pass


class CalendarWeeklyPromptIntegrityError(ValueError):
    pass


class CalendarWeeklyPromptEmptyError(ValueError):
    pass


class CalendarWeeklyPendingConflictError(ValueError):
    pass


class CalendarTournamentDateNotInPromptError(ValueError):
    pass


WEDNESDAY_WEEKDAY = 2
SUNDAY_WEEKDAY = 6
WEEKLY_PLAYING_WEEKDAYS = (2, 3, 4, 5, 6)
LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE = "legacy_unknown"


class CalendarService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        sunday_rotation: SundayTournamentRotation = sunday_tournament_rotation,
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.sunday_rotation = sunday_rotation
        self.clock = clock

    async def create_weekly_tournament_prompt(
        self,
        actor_telegram_id: int,
        today: date | None = None,
    ) -> TournamentPromptView:
        target_dates = next_complete_game_week(today or self.clock.today())
        scope_key = weekly_tournaments_prompt_key(target_dates)
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            tournament_repository = TournamentRepository(session)

            repository = AdminPromptRepository(session)
            pending_prompt = await repository.get_pending_by_scope(
                AdminPromptKind.TOURNAMENTS_PROPOSAL,
                scope_key,
            )
            if pending_prompt is not None:
                return await self._tournament_prompt_view(session, pending_prompt)

            tournament_dates_exist = [
                await tournament_repository.exists_for_date(tournament_date)
                for tournament_date in target_dates
            ]
            confirmed_prompt = await repository.get_latest_confirmed_by_scope(
                AdminPromptKind.TOURNAMENTS_PROPOSAL,
                scope_key,
            )
            if confirmed_prompt is not None:
                try:
                    materialized = await self._confirmed_weekly_prompt_is_materialized(
                        confirmed_prompt,
                        tournament_repository,
                    )
                except (CalendarPromptInvalidPayloadError, CalendarWeeklyPromptEmptyError):
                    materialized = False
                if materialized:
                    raise CalendarTournamentDateAlreadyExistsError
                logger.error(
                    "Confirmed weekly tournament prompt has missing tournaments",
                    extra={
                        "prompt_id": confirmed_prompt.id,
                        "scope_key": scope_key,
                    },
                )
                raise CalendarWeeklyPromptIntegrityError

            if any(tournament_dates_exist):
                raise CalendarTournamentDateAlreadyExistsError

            tournament_type_ids = await self._default_weekly_tournament_type_ids(
                session,
                target_dates,
            )
            payload = self._weekly_tournament_prompt_payload(
                target_dates=target_dates,
                tournament_type_ids=tournament_type_ids,
            )
            prompt = await repository.create_prompt(
                key=await self._next_weekly_prompt_key(repository, scope_key),
                kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                payload=payload,
                scope_key=scope_key,
            )
            try:
                await self._commit_tournament_prompt(session)
            except CalendarWeeklyPendingConflictError:
                recovered_prompt = await self._recover_pending_weekly_prompt(scope_key)
                if recovered_prompt is not None:
                    return recovered_prompt
                raise
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    async def get_prompt(self, actor_telegram_id: int, prompt_id: int) -> AdminPromptView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
            if prompt is None:
                raise CalendarPromptNotFoundError
            if prompt.status != AdminPromptStatus.PENDING:
                raise CalendarPromptAlreadyResolvedError
            return admin_prompt_view(prompt)

    async def get_tournament_prompt(
        self,
        actor_telegram_id: int,
        prompt_id: int,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            return await self._tournament_prompt_view(session, prompt)

    async def list_tournament_type_options(
        self,
        actor_telegram_id: int,
    ) -> list[TournamentTypeOptionView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            return await self._list_tournament_type_options(session)

    async def get_recommended_sunday_tournament_type(
        self,
        actor_telegram_id: int,
        target_date: date,
    ) -> TournamentTypeOptionView:
        try:
            if target_date.weekday() != SUNDAY_WEEKDAY:
                raise SundayTournamentRotationDateError
        except SundayTournamentRotationDateError as error:
            raise CalendarSundayTournamentDateError from error

        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            tournament_type_code = await self._default_sunday_tournament_type_code(
                TournamentRepository(session),
                target_date,
            )
            tournament_type = await TournamentRepository(
                session
            ).get_active_tournament_type_by_code(tournament_type_code)
            if tournament_type is None:
                raise CalendarSundayTournamentTypeNotFoundError(tournament_type_code)
            return TournamentTypeOptionView(
                id=tournament_type.id,
                name=tournament_type.name,
            )

    async def get_weekly_prompt_day_edit_options(
        self,
        actor_telegram_id: int,
        prompt_id: int,
        tournament_date: date,
    ) -> TournamentPromptDayEditView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            payload = json.loads(prompt.payload)
            self._weekly_prompt_payload_items(payload)
            self._tournament_payload_item_by_date(payload, tournament_date)
            return TournamentPromptDayEditView(
                prompt_id=prompt.id,
                tournament_date=tournament_date,
                tournament_types=await self._list_tournament_type_options(session),
            )

    async def resolve_prompt(
        self,
        actor_telegram_id: int,
        prompt_id: int,
        action: CalendarPromptAction,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            actor = await access_policy.require_superadmin(session, actor_telegram_id)
            repository = AdminPromptRepository(session)
            prompt = await repository.get_by_id(prompt_id)
            if prompt is None:
                raise CalendarPromptNotFoundError
            if prompt.status != AdminPromptStatus.PENDING:
                raise CalendarPromptAlreadyResolvedError

            if action == CalendarPromptAction.CONFIRM:
                await self._apply_prompt(session, prompt)
                prompt.status = AdminPromptStatus.CONFIRMED
            elif action == CalendarPromptAction.CANCEL:
                prompt.status = AdminPromptStatus.CANCELLED
            else:
                raise CalendarPromptUnsupportedError(action)

            prompt.resolved_at = self.clock.now()
            prompt.resolved_by_user_id = actor.id
            await self._commit_tournament_prompt(session)
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    async def get_created_weekly_schedule(
        self,
        actor_telegram_id: int,
        prompt_id: int,
    ) -> WeeklyScheduleView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
            if prompt is None:
                raise CalendarPromptNotFoundError
            if prompt.kind != AdminPromptKind.TOURNAMENTS_PROPOSAL:
                raise CalendarPromptUnsupportedError(prompt.kind)
            if prompt.status != AdminPromptStatus.CONFIRMED:
                raise CalendarPromptAlreadyResolvedError
            return await self._created_weekly_schedule_view(session, prompt)

    async def update_weekly_prompt_day_type(
        self,
        actor_telegram_id: int,
        prompt_id: int,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, actor_telegram_id)
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            payload = json.loads(prompt.payload)
            tournament = self._tournament_payload_item_by_date(payload, tournament_date)
            tournament_type = await self._tournament_type_detail(session, tournament_type_id)
            if tournament_type is None:
                raise CalendarPromptInvalidPayloadError
            tournament["tournament_type_id"] = tournament_type.id
            prompt.payload = json.dumps(payload, ensure_ascii=False)
            await self._commit_tournament_prompt(session)
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    @staticmethod
    async def _commit_tournament_prompt(session: AsyncSession) -> None:
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            if _is_tournament_date_integrity_error(error):
                raise CalendarTournamentDateAlreadyExistsError from error
            if _is_pending_prompt_scope_integrity_error(error):
                raise CalendarWeeklyPendingConflictError from error
            raise

    @staticmethod
    async def _next_weekly_prompt_key(
        repository: AdminPromptRepository,
        scope_key: str,
    ) -> str:
        prompts = await repository.list_by_scope(AdminPromptKind.TOURNAMENTS_PROPOSAL, scope_key)
        suffixes = [_weekly_prompt_attempt_suffix(prompt.key, scope_key) for prompt in prompts]
        return f"{scope_key}:{max(suffixes, default=0) + 1}"

    async def _recover_pending_weekly_prompt(
        self,
        scope_key: str,
    ) -> TournamentPromptView | None:
        async with self.session_factory() as session:
            pending_prompt = await AdminPromptRepository(session).get_pending_by_scope(
                AdminPromptKind.TOURNAMENTS_PROPOSAL,
                scope_key,
            )
            if pending_prompt is None:
                return None
            return await self._tournament_prompt_view(session, pending_prompt)

    async def _get_pending_tournament_prompt(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> AdminPrompt:
        repository = AdminPromptRepository(session)
        prompt = await repository.get_by_id(prompt_id)
        if prompt is None:
            raise CalendarPromptNotFoundError
        if prompt.status != AdminPromptStatus.PENDING:
            raise CalendarPromptAlreadyResolvedError
        if prompt.kind != AdminPromptKind.TOURNAMENTS_PROPOSAL:
            raise CalendarPromptUnsupportedError(prompt.kind)
        return prompt

    @classmethod
    def _tournament_payload_item_by_date(
        cls,
        payload: dict[str, object],
        tournament_date: date,
    ) -> dict[str, object]:
        for item in cls._weekly_prompt_payload_items(payload):
            if _payload_date(item) == tournament_date:
                return item
        raise CalendarTournamentDateNotInPromptError

    @staticmethod
    def _weekly_prompt_payload_items(
        payload: dict[str, object],
    ) -> list[dict[str, object]]:
        tournaments = payload.get("tournaments")
        if not isinstance(tournaments, list):
            raise CalendarPromptInvalidPayloadError
        if not tournaments:
            raise CalendarWeeklyPromptEmptyError
        if len(tournaments) != len(WEEKLY_PLAYING_WEEKDAYS):
            raise CalendarPromptInvalidPayloadError

        items: list[dict[str, object]] = []
        for item in tournaments:
            if not isinstance(item, dict):
                raise CalendarPromptInvalidPayloadError
            if set(item) != {"date", "tournament_type_id"}:
                raise CalendarPromptInvalidPayloadError
            items.append(item)

        dates = [_payload_date(item) for item in items]
        if len(set(dates)) != len(dates):
            raise CalendarPromptInvalidPayloadError
        wednesday = _wednesday_for_week(dates[0])
        expected_dates = tuple(
            wednesday.fromordinal(wednesday.toordinal() + weekday - WEDNESDAY_WEEKDAY)
            for weekday in WEEKLY_PLAYING_WEEKDAYS
        )
        expected_date_set = set(expected_dates)
        if set(dates) != expected_date_set:
            raise CalendarPromptInvalidPayloadError
        if dates != sorted(dates):
            raise CalendarPromptInvalidPayloadError
        return sorted(items, key=_payload_date)

    @staticmethod
    def _weekly_tournament_prompt_payload(
        *,
        target_dates: tuple[date, ...],
        tournament_type_ids: tuple[int, ...],
    ) -> str:
        return json.dumps(
            {
                "tournaments": [
                    {
                        "date": tournament_date.isoformat(),
                        "tournament_type_id": tournament_type_id,
                    }
                    for tournament_date, tournament_type_id in zip(
                        target_dates,
                        tournament_type_ids,
                        strict=True,
                    )
                ]
            },
            ensure_ascii=False,
        )

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
                sunday_type_code = await self._default_sunday_tournament_type_code(
                    repository,
                    target_date,
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
    ) -> str:
        latest_sunday = await repository.get_latest_sunday_rotation_tournament_before(
            target_date,
            self.sunday_rotation.rotation_codes,
        )
        if latest_sunday is not None and latest_sunday.tournament_type is not None:
            return self.sunday_rotation.next_code_after(latest_sunday.tournament_type.code)
        return self.sunday_rotation.fallback_code_for(target_date)

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

    async def _tournament_prompt_view(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> TournamentPromptView:
        payload = json.loads(prompt.payload)
        items: list[TournamentPromptItemView] = []
        for item in self._weekly_prompt_payload_items(payload):
            tournament_type = await self._tournament_type_detail(
                session,
                int(item["tournament_type_id"]),
            )
            if tournament_type is None:
                raise CalendarPromptInvalidPayloadError
            items.append(
                TournamentPromptItemView(
                    date=_payload_date(item),
                    tournament_type=tournament_type,
                )
            )
        return TournamentPromptView(
            id=prompt.id,
            kind=prompt.kind,
            status=prompt.status.value,
            tournaments=items,
        )

    async def _apply_prompt(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> None:
        if prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL:
            await self._apply_tournaments_prompt(session, prompt)
            return
        raise CalendarPromptUnsupportedError(prompt.kind)

    async def _apply_tournaments_prompt(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> None:
        payload = json.loads(prompt.payload)
        season_repository = SeasonRepository(session)
        tournament_repository = TournamentRepository(session)
        prompt_items = self._weekly_prompt_payload_items(payload)
        tournament_dates = [_payload_date(item) for item in prompt_items]
        for tournament_date in tournament_dates:
            if await tournament_repository.exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
        for item in prompt_items:
            tournament_date = _payload_date(item)
            season = await season_repository.get_for_date(tournament_date)
            if season is None:
                raise CalendarPromptInvalidPayloadError
            tournament_type_id = int(item["tournament_type_id"])
            if await self._tournament_type_detail(session, tournament_type_id) is None:
                raise CalendarPromptInvalidPayloadError
            await tournament_repository.add(
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id,
                    date=tournament_date,
                    status=TournamentStatus.ACTIVE,
                )
            )

    async def _created_weekly_schedule_view(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> WeeklyScheduleView:
        payload = json.loads(prompt.payload)
        prompt_items = self._weekly_prompt_payload_items(payload)
        expected_keys = [
            (_payload_date(item), int(item["tournament_type_id"])) for item in prompt_items
        ]
        tournament_rows = await TournamentRepository(session).list_weekly_schedule_records(
            dates=tuple(key[0] for key in expected_keys),
            tournament_type_ids=tuple(key[1] for key in expected_keys),
        )
        tournaments_by_key = {(row.date, row.tournament_type_id): row for row in tournament_rows}
        if set(tournaments_by_key) != set(expected_keys):
            raise CalendarWeeklyPromptIntegrityError

        rebuys_by_type_id = await self._rebuys_by_type_id(
            session,
            tuple({type_id for _, type_id in expected_keys}),
        )
        return WeeklyScheduleView(
            tournaments=[
                WeeklyScheduleTournamentView(
                    id=row.id,
                    date=row.date,
                    tournament_type_code=row.tournament_type_code,
                    tournament_type_name=row.tournament_type_name,
                    description=row.description,
                    entry_fee=row.entry_fee,
                    entry_stack=row.entry_stack,
                    addon_fee=row.addon_fee,
                    addon_stack=row.addon_stack,
                    rebuys=rebuys_by_type_id.get(row.tournament_type_id, []),
                    knockout_mode=(
                        row.knockout_mode.value
                        if row.knockout_mode is not None
                        else KnockoutMode.NONE.value
                    ),
                    points_multiplier=row.points_multiplier or Decimal("1.00"),
                    prize_place_multiplier=row.prize_place_multiplier or Decimal("1.00"),
                    prize_place_multiplier_places=row.prize_place_multiplier_places,
                )
                for row in (tournaments_by_key[key] for key in expected_keys)
            ]
        )

    async def _rebuys_by_type_id(
        self,
        session: AsyncSession,
        tournament_type_ids: tuple[int, ...],
    ) -> dict[int, list[TournamentRebuyView]]:
        rebuys = await TournamentTypeRepository(session).list_rebuys_by_type_ids(
            tournament_type_ids
        )
        rebuys_by_type_id: dict[int, list[TournamentRebuyView]] = {}
        for tournament_type_id, rows in rebuys.items():
            rebuys_by_type_id[tournament_type_id] = [
                TournamentRebuyView(fee=rebuy.fee, stack=rebuy.stack) for rebuy in rows
            ]
        return rebuys_by_type_id

    async def _confirmed_weekly_prompt_is_materialized(
        self,
        prompt: AdminPrompt,
        tournament_repository: TournamentRepository,
    ) -> bool:
        payload = json.loads(prompt.payload)
        prompt_items = self._weekly_prompt_payload_items(payload)
        for item in prompt_items:
            if not await tournament_repository.exists_for_date_and_type_id(
                _payload_date(item),
                int(item["tournament_type_id"]),
            ):
                return False
        return True


def next_complete_game_week(today: date) -> tuple[date, ...]:
    days_until_wednesday = (WEDNESDAY_WEEKDAY - today.weekday()) % 7
    if days_until_wednesday == 0:
        days_until_wednesday = 7
    wednesday = today.fromordinal(today.toordinal() + days_until_wednesday)
    return tuple(
        wednesday.fromordinal(wednesday.toordinal() + weekday - WEDNESDAY_WEEKDAY)
        for weekday in WEEKLY_PLAYING_WEEKDAYS
    )


def weekly_tournaments_prompt_key(target_dates: tuple[date, ...]) -> str:
    return f"tournaments:{target_dates[0].isoformat()}:{target_dates[-1].isoformat()}"


calendar_service = CalendarService(SessionFactory)


def admin_prompt_view(prompt: AdminPrompt) -> AdminPromptView:
    return AdminPromptView(
        id=prompt.id,
        kind=prompt.kind,
        payload=prompt.payload,
        status=prompt.status.value,
    )


def _is_tournament_date_integrity_error(error: IntegrityError) -> bool:
    message = str(error.orig)
    return "tournaments.date" in message or "uq_tournaments_date" in message


def _is_pending_prompt_scope_integrity_error(error: IntegrityError) -> bool:
    message = str(error.orig)
    return (
        "uq_admin_prompts_pending_scope" in message
        or "admin_prompts.kind, admin_prompts.scope_key" in message
        or "admin_prompts.key" in message
        or "uq_admin_prompts_key" in message
    )


def _payload_date(item: dict[str, object]) -> date:
    try:
        return date.fromisoformat(str(item["date"]))
    except (KeyError, ValueError) as error:
        raise CalendarPromptInvalidPayloadError from error


def _wednesday_for_week(tournament_date: date) -> date:
    if tournament_date.weekday() not in WEEKLY_PLAYING_WEEKDAYS:
        raise CalendarPromptInvalidPayloadError
    return tournament_date.fromordinal(
        tournament_date.toordinal() - (tournament_date.weekday() - WEDNESDAY_WEEKDAY)
    )


def _weekly_prompt_attempt_suffix(prompt_key: str, scope_key: str) -> int:
    if prompt_key == scope_key:
        return 1
    prefix = f"{scope_key}:"
    if not prompt_key.startswith(prefix):
        return 0
    try:
        return int(prompt_key.removeprefix(prefix))
    except ValueError:
        return 0
