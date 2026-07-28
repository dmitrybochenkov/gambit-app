from __future__ import annotations

import json
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AdminPrompt,
    Tournament,
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentType,
    TournamentTypeRule,
)
from app.db.models.enums import (
    AdminPromptStatus,
    TournamentStatus,
    TournamentTypeStatus,
)
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory
from app.services.dto import (
    AdminPromptView,
    TournamentPromptDayEditView,
    TournamentPromptItemView,
    TournamentPromptView,
    TournamentRebuyView,
    TournamentTypeDetailView,
    TournamentTypeOptionView,
)
from app.services.sunday_tournament_rotation import (
    SundayTournamentRotation,
    SundayTournamentRotationDateError,
    sunday_tournament_rotation,
)


class AdminPromptKind(StrEnum):
    TOURNAMENTS_PROPOSAL = "tournaments_proposal"


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


class CalendarWeeklyPromptConflictError(ValueError):
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
    ) -> None:
        self.session_factory = session_factory
        self.sunday_rotation = sunday_rotation

    async def create_weekly_tournament_prompt(
        self,
        today: date | None = None,
    ) -> TournamentPromptView:
        target_dates = next_complete_game_week(today or date.today())
        async with self.session_factory() as session:
            tournament_repository = TournamentRepository(session)
            for tournament_date in target_dates:
                if await tournament_repository.exists_for_date(tournament_date):
                    raise CalendarTournamentDateAlreadyExistsError

            repository = AdminPromptRepository(session)
            key = weekly_tournaments_prompt_key(target_dates)
            existing_prompt = await repository.get_by_key(key)
            if existing_prompt is not None:
                if existing_prompt.status == AdminPromptStatus.PENDING:
                    return await self._tournament_prompt_view(session, existing_prompt)
                raise CalendarWeeklyPromptConflictError

            tournament_type_ids = await self._default_weekly_tournament_type_ids(
                session,
                target_dates,
            )
            payload = self._weekly_tournament_prompt_payload(
                target_dates=target_dates,
                tournament_type_ids=tournament_type_ids,
            )
            prompt = AdminPrompt(
                key=key,
                kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                payload=payload,
                status=AdminPromptStatus.PENDING,
            )
            session.add(prompt)
            await self._commit_tournament_prompt(session)
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    async def get_prompt(self, prompt_id: int) -> AdminPromptView:
        async with self.session_factory() as session:
            prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
            if prompt is None:
                raise CalendarPromptNotFoundError
            if prompt.status != AdminPromptStatus.PENDING:
                raise CalendarPromptAlreadyResolvedError
            return admin_prompt_view(prompt)

    async def get_tournament_prompt(self, prompt_id: int) -> TournamentPromptView:
        async with self.session_factory() as session:
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            return await self._tournament_prompt_view(session, prompt)

    async def list_tournament_type_options(self) -> list[TournamentTypeOptionView]:
        async with self.session_factory() as session:
            return await self._list_tournament_type_options(session)

    async def get_recommended_sunday_tournament_type(
        self,
        target_date: date,
    ) -> TournamentTypeOptionView:
        try:
            tournament_type_code = self.sunday_rotation.code_for(target_date)
        except SundayTournamentRotationDateError as error:
            raise CalendarSundayTournamentDateError from error

        async with self.session_factory() as session:
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
        prompt_id: int,
        tournament_date: date,
    ) -> TournamentPromptDayEditView:
        async with self.session_factory() as session:
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
        prompt_id: int,
        admin_telegram_id: int,
        action: CalendarPromptAction,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            repository = AdminPromptRepository(session)
            prompt = await repository.get_by_id(prompt_id)
            if prompt is None:
                raise CalendarPromptNotFoundError
            if prompt.status != AdminPromptStatus.PENDING:
                raise CalendarPromptAlreadyResolvedError

            if action == CalendarPromptAction.CONFIRM:
                await self._apply_prompt(session, prompt, admin_telegram_id)
                prompt.status = AdminPromptStatus.CONFIRMED
            elif action == CalendarPromptAction.CANCEL:
                prompt.status = AdminPromptStatus.CANCELLED
            else:
                prompt.status = AdminPromptStatus.NEEDS_CHANGES

            prompt.resolved_at = datetime.now(UTC)
            prompt.resolved_by_admin_id = admin_telegram_id
            await self._commit_tournament_prompt(session)
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    async def update_weekly_prompt_day_type(
        self,
        prompt_id: int,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
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
            raise

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
        if not isinstance(tournaments, list) or len(tournaments) != len(WEEKLY_PLAYING_WEEKDAYS):
            raise CalendarPromptInvalidPayloadError

        items: list[dict[str, object]] = []
        for item in tournaments:
            if not isinstance(item, dict):
                raise CalendarPromptInvalidPayloadError
            if set(item) != {"date", "tournament_type_id"}:
                raise CalendarPromptInvalidPayloadError
            items.append(item)

        dates = [_payload_date(item) for item in items]
        wednesday = dates[0]
        expected_dates = tuple(
            wednesday.fromordinal(wednesday.toordinal() + weekday - WEDNESDAY_WEEKDAY)
            for weekday in WEEKLY_PLAYING_WEEKDAYS
        )
        if wednesday.weekday() != WEDNESDAY_WEEKDAY or tuple(dates) != expected_dates:
            raise CalendarPromptInvalidPayloadError
        return items

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
                sunday_type_code = self.sunday_rotation.code_for(target_date)
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

    async def _list_tournament_type_options(
        self,
        session: AsyncSession,
    ) -> list[TournamentTypeOptionView]:
        result = await session.execute(
            select(TournamentType)
            .where(
                TournamentType.status == TournamentTypeStatus.ACTIVE,
                TournamentType.code != LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
            )
            .order_by(TournamentType.id)
        )
        return [
            TournamentTypeOptionView(id=tournament_type.id, name=tournament_type.name)
            for tournament_type in result.scalars()
        ]

    async def _tournament_type_detail(
        self,
        session: AsyncSession,
        tournament_type_id: int,
    ) -> TournamentTypeDetailView | None:
        type_result = await session.execute(
            select(TournamentType).where(
                TournamentType.id == tournament_type_id,
                TournamentType.status == TournamentTypeStatus.ACTIVE,
                TournamentType.code != LEGACY_UNKNOWN_TOURNAMENT_TYPE_CODE,
            )
        )
        tournament_type = type_result.scalar_one_or_none()
        if tournament_type is None:
            return None

        economy_result = await session.execute(
            select(TournamentEconomyConfig).where(
                TournamentEconomyConfig.tournament_type_id == tournament_type_id
            )
        )
        economy = economy_result.scalar_one_or_none()
        if economy is None:
            return None

        rebuys_result = await session.execute(
            select(TournamentRebuyConfig)
            .where(TournamentRebuyConfig.tournament_type_id == tournament_type_id)
            .order_by(TournamentRebuyConfig.rebuy_order)
        )
        rebuys = list(rebuys_result.scalars())
        rule_result = await session.execute(
            select(TournamentTypeRule).where(
                TournamentTypeRule.tournament_type_id == tournament_type_id
            )
        )
        rule = rule_result.scalar_one_or_none()
        return TournamentTypeDetailView(
            id=tournament_type.id,
            name=tournament_type.name,
            description=tournament_type.description,
            entry_fee=economy.entry_fee,
            entry_stack=economy.entry_stack,
            addon_fee=economy.addon_fee,
            addon_stack=economy.addon_stack,
            rebuys=[TournamentRebuyView(fee=rebuy.fee, stack=rebuy.stack) for rebuy in rebuys],
            knockout_mode=rule.knockout_mode.value if rule is not None else "none",
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
        admin_telegram_id: int,
    ) -> None:
        del admin_telegram_id
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
            session.add(
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id,
                    date=tournament_date,
                    status=TournamentStatus.ACTIVE,
                )
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


def _payload_date(item: dict[str, object]) -> date:
    try:
        return date.fromisoformat(str(item["date"]))
    except (KeyError, ValueError) as error:
        raise CalendarPromptInvalidPayloadError from error
