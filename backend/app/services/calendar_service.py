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


class CalendarService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        sunday_rotation: SundayTournamentRotation = sunday_tournament_rotation,
    ) -> None:
        self.session_factory = session_factory
        self.sunday_rotation = sunday_rotation

    async def create_manual_tournament_prompt(
        self,
        tournament_date: date,
        tournament_type_id: int,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            if await TournamentRepository(session).exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
            tournament_type = await self._tournament_type_detail(
                session,
                tournament_type_id,
            )
            if tournament_type is None:
                raise CalendarPromptInvalidPayloadError
            payload = self._tournament_prompt_payload(
                tournament_date=tournament_date,
                tournament_type_id=tournament_type.id,
            )
            prompt = await AdminPromptRepository(session).get_or_create_pending(
                key=f"tournament:{tournament_date.isoformat()}",
                kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                payload=payload,
            )
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
            result = await session.execute(
                select(TournamentType)
                .where(TournamentType.status == TournamentTypeStatus.ACTIVE)
                .order_by(TournamentType.id)
            )
            return [
                TournamentTypeOptionView(id=tournament_type.id, name=tournament_type.name)
                for tournament_type in result.scalars()
            ]

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

    async def update_tournament_prompt_type(
        self,
        prompt_id: int,
        tournament_index: int,
        tournament_type_id: int,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            payload = json.loads(prompt.payload)
            tournament = self._tournament_payload_item(payload, tournament_index)
            tournament_type = await self._tournament_type_detail(session, tournament_type_id)
            if tournament_type is None:
                raise CalendarPromptInvalidPayloadError
            tournament["tournament_type_id"] = tournament_type.id
            prompt.payload = json.dumps(payload, ensure_ascii=False)
            await self._commit_tournament_prompt(session)
            await session.refresh(prompt)
            return await self._tournament_prompt_view(session, prompt)

    async def update_tournament_prompt_date(
        self,
        prompt_id: int,
        tournament_date: date,
    ) -> TournamentPromptView:
        async with self.session_factory() as session:
            if await TournamentRepository(session).exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
            prompt = await self._get_pending_tournament_prompt(session, prompt_id)
            repository = AdminPromptRepository(session)
            key = f"tournament:{tournament_date.isoformat()}"
            existing_prompt = await repository.get_by_key(key)
            if existing_prompt is not None and existing_prompt.id != prompt.id:
                raise CalendarTournamentDateAlreadyExistsError
            payload = json.loads(prompt.payload)
            tournament = self._tournament_payload_item(payload, 0)
            tournament["date"] = tournament_date.isoformat()
            prompt.key = key
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

    @staticmethod
    def _tournament_payload_item(
        payload: dict[str, object],
        tournament_index: int,
    ) -> dict[str, object]:
        tournaments = payload["tournaments"]
        if not isinstance(tournaments, list):
            raise CalendarPromptInvalidPayloadError
        try:
            item = tournaments[tournament_index]
        except IndexError as error:
            raise CalendarPromptInvalidPayloadError from error
        if not isinstance(item, dict):
            raise CalendarPromptInvalidPayloadError
        return item

    @staticmethod
    def _tournament_prompt_payload(
        *,
        tournament_date: date,
        tournament_type_id: int,
    ) -> str:
        return json.dumps(
            {
                "tournaments": [
                    {
                        "date": tournament_date.isoformat(),
                        "tournament_type_id": tournament_type_id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    async def _tournament_type_detail(
        self,
        session: AsyncSession,
        tournament_type_id: int,
    ) -> TournamentTypeDetailView | None:
        type_result = await session.execute(
            select(TournamentType).where(
                TournamentType.id == tournament_type_id,
                TournamentType.status == TournamentTypeStatus.ACTIVE,
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
            rebuys=[
                TournamentRebuyView(fee=rebuy.fee, stack=rebuy.stack)
                for rebuy in rebuys
            ],
            knockout_mode=rule.knockout_mode.value if rule is not None else "none",
        )

    async def _tournament_prompt_view(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> TournamentPromptView:
        payload = json.loads(prompt.payload)
        tournaments = payload.get("tournaments")
        if not isinstance(tournaments, list):
            raise CalendarPromptInvalidPayloadError

        items: list[TournamentPromptItemView] = []
        for item in tournaments:
            if not isinstance(item, dict):
                raise CalendarPromptInvalidPayloadError
            tournament_type = await self._tournament_type_detail(
                session,
                int(item["tournament_type_id"]),
            )
            if tournament_type is None:
                raise CalendarPromptInvalidPayloadError
            items.append(
                TournamentPromptItemView(
                    date=date.fromisoformat(str(item["date"])),
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
        active_season = await season_repository.get_active()
        if active_season is None:
            raise CalendarPromptInvalidPayloadError
        tournament_dates = [date.fromisoformat(item["date"]) for item in payload["tournaments"]]
        for tournament_date in tournament_dates:
            if await tournament_repository.exists_for_date(tournament_date):
                raise CalendarTournamentDateAlreadyExistsError
        for item in payload["tournaments"]:
            tournament_date = date.fromisoformat(item["date"])
            tournament_type_id = int(item["tournament_type_id"])
            session.add(
                Tournament(
                    season_id=active_season.id,
                    tournament_type_id=tournament_type_id,
                    date=tournament_date,
                    status=TournamentStatus.ACTIVE,
                )
            )

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
