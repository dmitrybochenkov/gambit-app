from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AdminPrompt, Season, Tournament
from app.db.models.enums import AdminPromptStatus, SeasonStatus, TournamentStatus
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory

SEASON_NOTICE_DAYS = 7
DEFAULT_TOURNAMENT_CAPACITY = 30
DEFAULT_WEEKLY_TOURNAMENTS = {
    2: 1,
    3: 2,
    4: 3,
}


class AdminPromptKind(StrEnum):
    SEASON_PROPOSAL = "season_proposal"
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


@dataclass(frozen=True)
class ProposedTournament:
    date: date
    type: int
    capacity: int = DEFAULT_TOURNAMENT_CAPACITY


class CalendarService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def collect_due_prompts(
        self,
        today: date | None = None,
    ) -> list[AdminPrompt]:
        today = today or date.today()
        prompts: list[AdminPrompt] = []
        async with self.session_factory() as session:
            season_prompt = await self._get_or_create_season_prompt(session, today)
            if (
                season_prompt is not None
                and season_prompt.status == AdminPromptStatus.PENDING
                and season_prompt.notified_at is None
            ):
                prompts.append(season_prompt)

            tournament_prompt = await self._get_or_create_tournaments_prompt(
                session,
                today,
            )
            if (
                tournament_prompt is not None
                and tournament_prompt.status == AdminPromptStatus.PENDING
                and tournament_prompt.notified_at is None
            ):
                prompts.append(tournament_prompt)

            await session.commit()
            for prompt in prompts:
                await session.refresh(prompt)
            return prompts

    async def mark_prompt_notified(self, prompt_id: int) -> None:
        async with self.session_factory() as session:
            prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
            if prompt is None:
                return
            prompt.notified_at = datetime.now(UTC)
            await session.commit()

    async def resolve_prompt(
        self,
        prompt_id: int,
        admin_telegram_id: int,
        action: CalendarPromptAction,
    ) -> AdminPrompt:
        async with self.session_factory() as session:
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
                prompt.status = AdminPromptStatus.NEEDS_CHANGES

            prompt.resolved_at = datetime.now(UTC)
            prompt.resolved_by_admin_id = admin_telegram_id
            await session.commit()
            await session.refresh(prompt)
            return prompt

    async def _get_or_create_season_prompt(
        self,
        session: AsyncSession,
        today: date,
    ) -> AdminPrompt | None:
        active_season = await SeasonRepository(session).get_active()
        if active_season is None:
            return None
        if today < active_season.ends_at - timedelta(days=SEASON_NOTICE_DAYS):
            return None

        next_start = active_season.ends_at + timedelta(days=1)
        next_season = seasonal_season_for(next_start)
        existing_next = await SeasonRepository(session).get_by_name(next_season["name"])
        if existing_next is not None:
            return None

        payload = json.dumps(
            {
                "current_season_id": active_season.id,
                "name": next_season["name"],
                "starts_at": next_season["starts_at"].isoformat(),
                "ends_at": next_season["ends_at"].isoformat(),
            },
            ensure_ascii=False,
        )
        return await AdminPromptRepository(session).get_or_create_pending(
            key=f"season:{next_season['name']}",
            kind=AdminPromptKind.SEASON_PROPOSAL,
            payload=payload,
        )

    async def _get_or_create_tournaments_prompt(
        self,
        session: AsyncSession,
        today: date,
    ) -> AdminPrompt | None:
        if today.weekday() != 6:
            return None

        proposed_tournaments = await self._missing_tournaments_for_next_two_weeks(
            session,
            today,
        )
        if not proposed_tournaments:
            return None

        first_date = proposed_tournaments[0].date
        last_date = proposed_tournaments[-1].date
        payload = json.dumps(
            {
                "tournaments": [
                    {
                        "date": tournament.date.isoformat(),
                        "type": tournament.type,
                        "capacity": tournament.capacity,
                    }
                    for tournament in proposed_tournaments
                ]
            },
            ensure_ascii=False,
        )
        return await AdminPromptRepository(session).get_or_create_pending(
            key=f"tournaments:{first_date.isoformat()}:{last_date.isoformat()}",
            kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
            payload=payload,
        )

    async def _missing_tournaments_for_next_two_weeks(
        self,
        session: AsyncSession,
        today: date,
    ) -> list[ProposedTournament]:
        first_monday = today + timedelta(days=1)
        last_day = first_monday + timedelta(days=13)
        repository = TournamentRepository(session)
        proposed: list[ProposedTournament] = []

        current_day = first_monday
        while current_day <= last_day:
            tournament_type = DEFAULT_WEEKLY_TOURNAMENTS.get(current_day.weekday())
            if tournament_type is not None and not await repository.exists_for_date_and_type(
                current_day,
                tournament_type,
            ):
                proposed.append(
                    ProposedTournament(
                        date=current_day,
                        type=tournament_type,
                    )
                )
            current_day += timedelta(days=1)
        return proposed

    async def _apply_prompt(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> None:
        if prompt.kind == AdminPromptKind.SEASON_PROPOSAL:
            await self._apply_season_prompt(session, prompt)
            return
        if prompt.kind == AdminPromptKind.TOURNAMENTS_PROPOSAL:
            await self._apply_tournaments_prompt(session, prompt)
            return
        raise CalendarPromptUnsupportedError(prompt.kind)

    async def _apply_season_prompt(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> None:
        payload = json.loads(prompt.payload)
        season_repository = SeasonRepository(session)
        existing = await season_repository.get_by_name(payload["name"])
        if existing is not None:
            return

        active_season = await season_repository.get_active()
        scoring_config_id = active_season.scoring_config_id if active_season else 1
        session.add(
            Season(
                name=payload["name"],
                scoring_config_id=scoring_config_id,
                starts_at=date.fromisoformat(payload["starts_at"]),
                ends_at=date.fromisoformat(payload["ends_at"]),
                status=SeasonStatus.UPCOMING,
            )
        )

    async def _apply_tournaments_prompt(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> None:
        payload = json.loads(prompt.payload)
        season_repository = SeasonRepository(session)
        tournament_repository = TournamentRepository(session)
        for item in payload["tournaments"]:
            tournament_date = date.fromisoformat(item["date"])
            tournament_type = int(item["type"])
            if await tournament_repository.exists_for_date_and_type(
                tournament_date,
                tournament_type,
            ):
                continue

            season = await season_repository.get_for_date(tournament_date)
            if season is None:
                continue

            session.add(
                Tournament(
                    season_id=season.id,
                    type=tournament_type,
                    date=tournament_date,
                    capacity=int(item["capacity"]),
                    status=TournamentStatus.ACTIVE,
                )
            )


def seasonal_season_for(target_date: date) -> dict[str, date | str]:
    year = target_date.year
    if target_date.month in {12, 1, 2}:
        winter_year = year if target_date.month == 12 else year - 1
        return {
            "name": f"Зима {winter_year}-{winter_year + 1}",
            "starts_at": date(winter_year, 12, 1),
            "ends_at": date(winter_year + 1, 2, 29 if is_leap_year(winter_year + 1) else 28),
        }
    if target_date.month in {3, 4, 5}:
        return {
            "name": f"Весна {year}",
            "starts_at": date(year, 3, 1),
            "ends_at": date(year, 5, 31),
        }
    if target_date.month in {6, 7, 8}:
        return {
            "name": f"Лето {year}",
            "starts_at": date(year, 6, 1),
            "ends_at": date(year, 8, 31),
        }
    return {
        "name": f"Осень {year}",
        "starts_at": date(year, 9, 1),
        "ends_at": date(year, 11, 30),
    }


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


calendar_service = CalendarService(SessionFactory)
