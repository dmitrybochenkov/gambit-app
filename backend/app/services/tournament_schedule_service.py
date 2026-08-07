from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AdminPrompt
from app.db.models.enums import AdminPromptKind, AdminPromptStatus, KnockoutMode
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.schedules import (
    TournamentRebuyView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
)
from app.services.tournament_proposal_service import (
    CalendarPromptAlreadyResolvedError,
    CalendarPromptNotFoundError,
    CalendarPromptUnsupportedError,
    CalendarWeeklyPromptIntegrityError,
    WeeklyTournamentPromptPayload,
)


class TournamentScheduleService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

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

    async def _created_weekly_schedule_view(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
    ) -> WeeklyScheduleView:
        prompt_items = WeeklyTournamentPromptPayload.from_json(prompt.payload).tournaments
        expected_keys = [(item.date, item.tournament_type_id) for item in prompt_items]
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


tournament_schedule_service = TournamentScheduleService(SessionFactory)
