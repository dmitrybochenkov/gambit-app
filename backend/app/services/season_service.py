import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import AdminPrompt, ScoringConfig, Season
from app.db.models.enums import AdminPromptKind, AdminPromptStatus
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.admin_prompt_service import admin_prompt_service
from app.services.dto.seasons import (
    ScoringConfigView,
    SeasonLifecycleStateView,
    SeasonProposalView,
    SeasonTimelineView,
    SeasonView,
)
from app.services.pagination import Page


class SeasonNotFoundError(ValueError):
    pass


class SeasonNameAlreadyExistsError(ValueError):
    pass


class SeasonNameInvalidError(ValueError):
    pass


class SeasonScoringConfigNotFoundError(ValueError):
    pass


class SeasonScoringConfigAmbiguousError(ValueError):
    pass


class SeasonStartDateError(ValueError):
    pass


class SeasonConflictError(ValueError):
    pass


class SeasonCurrentNotFoundError(ValueError):
    pass


class SeasonScheduledConflictError(ValueError):
    pass


class SeasonDateOverlapError(ValueError):
    pass


class SeasonProposalNotFoundError(ValueError):
    pass


class SeasonProposalAlreadyResolvedError(ValueError):
    pass


class SeasonProposalInvalidPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class SeasonProposalPayload:
    name: str
    starts_at: date
    scoring_config_id: int

    @classmethod
    def create(
        cls,
        *,
        name: object,
        starts_at: date,
        scoring_config_id: int,
    ) -> "SeasonProposalPayload":
        return cls(
            name=validate_season_name(name),
            starts_at=starts_at,
            scoring_config_id=scoring_config_id,
        )

    @classmethod
    def from_json(cls, raw_payload: str) -> "SeasonProposalPayload":
        try:
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise SeasonProposalInvalidPayloadError
            return cls.create(
                name=payload.get("name"),
                starts_at=date.fromisoformat(str(payload["starts_at"])),
                scoring_config_id=int(payload["scoring_config_id"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SeasonProposalInvalidPayloadError from error

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "starts_at": self.starts_at.isoformat(),
                "scoring_config_id": self.scoring_config_id,
            },
            ensure_ascii=False,
        )

    def with_name(self, name: str) -> "SeasonProposalPayload":
        return SeasonProposalPayload.create(
            name=name,
            starts_at=self.starts_at,
            scoring_config_id=self.scoring_config_id,
        )

    def with_starts_at(self, starts_at: date) -> "SeasonProposalPayload":
        return SeasonProposalPayload.create(
            name=self.name,
            starts_at=starts_at,
            scoring_config_id=self.scoring_config_id,
        )


SEASON_NAME_BY_QUARTER = {
    1: "Зима",
    2: "Весна",
    3: "Лето",
    4: "Осень",
}
SEASON_PROPOSAL_SCOPE_KEY = "season"


class SeasonService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_active_season(self, today: date | None = None) -> SeasonView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            season = await SeasonRepository(session).get_for_date(business_date)
            if season is None:
                raise SeasonNotFoundError
            return season_view(season, today=business_date)

    async def list_seasons(self, today: date | None = None) -> list[SeasonView]:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            seasons = await SeasonRepository(session).list_all()
            return [season_view(season, today=business_date) for season in seasons]

    async def get_season_timeline(
        self,
        admin_telegram_id: int,
        today: date | None = None,
    ) -> SeasonTimelineView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            return await self._season_timeline_view(session, today=business_date)

    async def list_seasons_page_for_admin(
        self,
        admin_telegram_id: int,
        *,
        page: int,
        page_size: int,
        today: date | None = None,
    ) -> Page[SeasonView]:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            seasons = await SeasonRepository(session).list_all_ordered()
            total_items = len(seasons)
            total_pages = max(1, (total_items + page_size - 1) // page_size)
            normalized_page = min(max(0, page), total_pages - 1)
            start = normalized_page * page_size
            end = start + page_size
            return Page(
                items=[season_view(season, today=business_date) for season in seasons[start:end]],
                page=normalized_page,
                page_size=page_size,
                total_items=total_items,
            )

    async def list_scoring_configs(self, admin_telegram_id: int) -> list[ScoringConfigView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            configs = await ScoringConfigRepository(session).list_all()
            return [scoring_config_view(config) for config in configs]

    async def create_season_proposal(
        self,
        admin_telegram_id: int,
        starts_at: date | None = None,
        today: date | None = None,
    ) -> SeasonProposalView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            repository = AdminPromptRepository(session)
            pending_proposal = await repository.get_pending_by_scope(
                AdminPromptKind.SEASON_PROPOSAL,
                SEASON_PROPOSAL_SCOPE_KEY,
            )
            if pending_proposal is not None:
                return await self._season_proposal_view(
                    session,
                    pending_proposal,
                    today=business_date,
                )

            timeline = await self._season_timeline_view(session, today=business_date)
            if timeline.has_future_season:
                raise SeasonScheduledConflictError
            proposal_starts_at = starts_at or timeline.suggested_start
            if proposal_starts_at is None:
                raise SeasonStartDateError
            await self._validate_new_season_timeline(
                session,
                starts_at=proposal_starts_at,
                today=business_date,
            )
            scoring_config = await self._default_scoring_config(session, proposal_starts_at)
            if scoring_config is None:
                raise SeasonScoringConfigNotFoundError
            proposal = await repository.create_prompt(
                key=await next_season_proposal_key(repository),
                kind=AdminPromptKind.SEASON_PROPOSAL,
                payload=SeasonProposalPayload.create(
                    name=season_name_for_date(proposal_starts_at),
                    starts_at=proposal_starts_at,
                    scoring_config_id=scoring_config.id,
                ).to_json(),
                scope_key=SEASON_PROPOSAL_SCOPE_KEY,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                recovered_proposal = await self._recover_pending_season_proposal(business_date)
                if recovered_proposal is not None:
                    return recovered_proposal
                raise SeasonConflictError from exc
            await session.refresh(proposal)
            return await self._season_proposal_view(
                session,
                proposal,
                proposal_starts_at,
                today=business_date,
            )

    async def _recover_pending_season_proposal(
        self,
        today: date,
    ) -> SeasonProposalView | None:
        async with self.session_factory() as session:
            pending_proposal = await AdminPromptRepository(session).get_pending_by_scope(
                AdminPromptKind.SEASON_PROPOSAL,
                SEASON_PROPOSAL_SCOPE_KEY,
            )
            if pending_proposal is None:
                return None
            return await self._season_proposal_view(
                session,
                pending_proposal,
                today=today,
            )

    async def get_season_proposal(
        self,
        admin_telegram_id: int,
        prompt_id: int,
        today: date | None = None,
    ) -> SeasonProposalView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            return await self._season_proposal_view(session, prompt, today=today)

    async def update_season_proposal_name(
        self,
        admin_telegram_id: int,
        prompt_id: int,
        name: str,
    ) -> SeasonProposalView:
        validated_name = validate_season_name(name)
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            payload = SeasonProposalPayload.from_json(prompt.payload)
            prompt.payload = payload.with_name(validated_name).to_json()
            await session.commit()
            await session.refresh(prompt)
            return await self._season_proposal_view(session, prompt)

    async def update_season_proposal_start_date(
        self,
        admin_telegram_id: int,
        prompt_id: int,
        starts_at: date,
    ) -> SeasonProposalView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            await self._validate_new_season_timeline(
                session,
                starts_at=starts_at,
                today=self.clock.today(),
            )
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            payload = SeasonProposalPayload.from_json(prompt.payload)
            prompt.payload = payload.with_starts_at(starts_at).to_json()
            await session.commit()
            await session.refresh(prompt)
            return await self._season_proposal_view(session, prompt, starts_at)

    async def delete_future_season(
        self,
        admin_telegram_id: int,
        season_id: int,
    ) -> SeasonTimelineView:
        business_date = self.clock.today()
        async with self.session_factory() as session:
            try:
                await access_policy.require_admin(session, admin_telegram_id)
                repository = SeasonRepository(session)
                future_season = await self._require_future_season(
                    repository,
                    season_id,
                    business_date,
                )
                previous_season = await repository.get_previous_before(future_season.starts_at)
                if previous_season is None:
                    raise SeasonCurrentNotFoundError
                await repository.delete(future_season)
                await session.flush()
                previous_season.ends_at = None
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise SeasonConflictError from exc
            except Exception:
                await session.rollback()
                raise
            return await self._season_timeline_view(session, today=business_date)

    async def confirm_season_proposal(
        self,
        admin_telegram_id: int,
        prompt_id: int,
        today: date | None = None,
    ) -> SeasonView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                actor = await access_policy.require_admin(session, admin_telegram_id)
                prompt = await self._get_pending_season_proposal(session, prompt_id)
                payload = SeasonProposalPayload.from_json(prompt.payload)
                season = await self._create_proposed_season_in_session(
                    session=session,
                    name=payload.name,
                    starts_at=payload.starts_at,
                    scoring_config_id=payload.scoring_config_id,
                    today=business_date,
                )
                admin_prompt_service.confirm(
                    prompt,
                    actor=actor,
                    resolved_at=self.clock.now(),
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise SeasonConflictError from exc
            except Exception:
                await session.rollback()
                raise
            await session.refresh(season)
            return season_view(season, today=business_date)

    async def cancel_season_proposal(
        self,
        admin_telegram_id: int,
        prompt_id: int,
    ) -> None:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            admin_prompt_service.cancel(
                prompt,
                actor=actor,
                resolved_at=self.clock.now(),
            )
            await session.commit()

    async def open_season(
        self,
        admin_telegram_id: int,
        name: str,
        starts_at: date,
        scoring_config_id: int,
    ) -> SeasonView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_admin(session, admin_telegram_id)
                season = await self._open_season_in_session(
                    session=session,
                    name=name,
                    scoring_config_id=scoring_config_id,
                    starts_at=starts_at,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise SeasonConflictError from exc
            except Exception:
                await session.rollback()
                raise
            await session.refresh(season)
            return season_view(season, today=starts_at)

    @classmethod
    async def _open_season_in_session(
        cls,
        session: AsyncSession,
        name: str,
        starts_at: date,
        scoring_config_id: int,
    ) -> Season:
        name = validate_season_name(name)
        repository = SeasonRepository(session)
        if await repository.get_by_name(name) is not None:
            raise SeasonNameAlreadyExistsError
        if await ScoringConfigRepository(session).get_by_id(scoring_config_id) is None:
            raise SeasonScoringConfigNotFoundError

        active_season = await repository.get_for_date(starts_at)
        if active_season is not None:
            if active_season.ends_at is not None:
                raise SeasonDateOverlapError
            if starts_at <= active_season.starts_at:
                raise SeasonStartDateError
            active_season.ends_at = starts_at - timedelta(days=1)
        else:
            overlaps = await repository.find_overlapping(starts_at=starts_at, ends_at=None)
            if overlaps:
                starts_before_open_ended = any(
                    season.ends_at is None and starts_at < season.starts_at for season in overlaps
                )
                if starts_before_open_ended:
                    raise SeasonStartDateError
                raise SeasonDateOverlapError

        season = Season(
            name=name,
            scoring_config_id=scoring_config_id,
            starts_at=starts_at,
            ends_at=None,
        )
        repository.add(season)
        return season

    @classmethod
    async def _create_proposed_season_in_session(
        cls,
        session: AsyncSession,
        name: str,
        starts_at: date,
        scoring_config_id: int,
        today: date,
    ) -> Season:
        name = validate_season_name(name)
        repository = SeasonRepository(session)
        if await repository.get_by_name(name) is not None:
            raise SeasonNameAlreadyExistsError
        if await ScoringConfigRepository(session).get_by_id(scoring_config_id) is None:
            raise SeasonScoringConfigNotFoundError

        if starts_at < today:
            raise SeasonStartDateError

        await cls._validate_new_season_timeline(
            session,
            starts_at=starts_at,
            today=today,
        )

        active_season = await repository.get_for_date(today)
        if active_season is not None:
            if starts_at == today:
                raise SeasonConflictError
            if starts_at <= active_season.starts_at:
                raise SeasonStartDateError
            active_ends_at = starts_at - timedelta(days=1)
            if active_ends_at < active_season.starts_at:
                raise SeasonStartDateError
            overlaps = await repository.find_overlapping(
                starts_at=starts_at,
                ends_at=None,
                exclude_id=active_season.id,
            )
            if overlaps:
                raise SeasonDateOverlapError
            active_season.ends_at = active_ends_at

        if await repository.get_for_date(starts_at) is not None:
            raise SeasonConflictError

        season = Season(
            name=name,
            scoring_config_id=scoring_config_id,
            starts_at=starts_at,
            ends_at=None,
        )
        repository.add(season)
        return season

    @staticmethod
    async def _default_scoring_config(
        session: AsyncSession,
        starts_at: date,
    ) -> ScoringConfig | None:
        active_season = await SeasonRepository(session).get_for_date(starts_at)
        if active_season is not None:
            return await ScoringConfigRepository(session).get_by_id(active_season.scoring_config_id)

        configs = await ScoringConfigRepository(session).list_all()
        if not configs:
            return None
        if len(configs) > 1:
            raise SeasonScoringConfigAmbiguousError
        return configs[0]

    async def _season_proposal_view(
        self,
        session: AsyncSession,
        prompt: AdminPrompt,
        starts_at: date | None = None,
        today: date | None = None,
    ) -> SeasonProposalView:
        proposal = season_proposal_view(prompt)
        proposal_starts_at = starts_at or proposal.starts_at
        active_season = await SeasonRepository(session).get_for_date(today or self.clock.today())
        active_season_ends_at = (
            proposal_starts_at - timedelta(days=1) if active_season is not None else None
        )
        return SeasonProposalView(
            id=proposal.id,
            name=proposal.name,
            starts_at=proposal.starts_at,
            scoring_config_id=proposal.scoring_config_id,
            active_season_ends_at=active_season_ends_at,
        )

    @classmethod
    async def _season_timeline_view(
        cls,
        session: AsyncSession,
        today: date,
    ) -> SeasonTimelineView:
        repository = SeasonRepository(session)
        seasons = await repository.list_all_ordered()
        completed = [
            season_view(season, today=today)
            for season in seasons
            if season.ends_at is not None and season.ends_at < today
        ]
        current = next(
            (
                season_view(season, today=today)
                for season in seasons
                if season.starts_at <= today and (season.ends_at is None or season.ends_at >= today)
            ),
            None,
        )
        future = [
            season_view(season, today=today) for season in seasons if season.starts_at > today
        ]
        if len(future) > 1:
            raise SeasonScheduledConflictError
        pending_prompt = await AdminPromptRepository(session).get_pending_by_scope(
            AdminPromptKind.SEASON_PROPOSAL,
            SEASON_PROPOSAL_SCOPE_KEY,
        )
        pending_proposal = (
            season_proposal_view(pending_prompt) if pending_prompt is not None else None
        )
        return SeasonTimelineView(
            completed_seasons=completed,
            current_season=current,
            future_seasons=future,
            pending_proposal=pending_proposal,
            suggested_start=cls._suggested_next_start(seasons, today),
        )

    @staticmethod
    def _suggested_next_start(seasons: list[Season], today: date) -> date | None:
        if not seasons:
            return None
        if any(season.starts_at > today for season in seasons):
            return None
        last_season = seasons[-1]
        if last_season.ends_at is None:
            return None
        return last_season.ends_at + timedelta(days=1)

    @staticmethod
    async def _get_pending_season_proposal(
        session: AsyncSession,
        prompt_id: int,
    ) -> AdminPrompt:
        prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
        if prompt is None or prompt.kind != AdminPromptKind.SEASON_PROPOSAL:
            raise SeasonProposalNotFoundError
        if prompt.status != AdminPromptStatus.PENDING:
            raise SeasonProposalAlreadyResolvedError
        SeasonProposalPayload.from_json(prompt.payload)
        return prompt

    @staticmethod
    async def _require_future_season(
        repository: SeasonRepository,
        season_id: int,
        today: date,
    ) -> Season:
        season = await repository.get_by_id(season_id)
        if season is None:
            raise SeasonNotFoundError
        if season.starts_at <= today:
            raise SeasonDateOverlapError
        return season

    @classmethod
    async def _validate_season_start_date(
        cls,
        session: AsyncSession,
        starts_at: date,
    ) -> None:
        open_ended_season = await SeasonRepository(session).get_open_ended()
        if open_ended_season is not None and starts_at <= open_ended_season.starts_at:
            raise SeasonStartDateError

    @classmethod
    async def _validate_new_season_timeline(
        cls,
        session: AsyncSession,
        starts_at: date,
        today: date,
    ) -> None:
        if starts_at < today:
            raise SeasonStartDateError

        seasons = await SeasonRepository(session).list_all_ordered()
        if not seasons:
            raise SeasonCurrentNotFoundError

        repository = SeasonRepository(session)
        current_season = await repository.get_for_date(today)
        if current_season is None:
            raise SeasonCurrentNotFoundError

        if any(season.starts_at > today for season in seasons):
            raise SeasonScheduledConflictError

        if starts_at <= today or starts_at <= current_season.starts_at:
            raise SeasonStartDateError

        if current_season.ends_at is not None and starts_at <= current_season.ends_at:
            raise SeasonDateOverlapError


def season_view(season: Season, *, today: date) -> SeasonView:
    return SeasonView(
        id=season.id,
        name=season.name,
        starts_at=season.starts_at,
        ends_at=season.ends_at,
        lifecycle_state=season_lifecycle_state(
            starts_at=season.starts_at,
            ends_at=season.ends_at,
            today=today,
        ),
        scoring_config_id=season.scoring_config_id,
    )


def season_lifecycle_state(
    *,
    starts_at: date,
    ends_at: date | None,
    today: date,
) -> SeasonLifecycleStateView:
    if starts_at > today:
        return SeasonLifecycleStateView.SCHEDULED
    if ends_at is not None and ends_at < today:
        return SeasonLifecycleStateView.COMPLETED
    return SeasonLifecycleStateView.CURRENT


def scoring_config_view(config: ScoringConfig) -> ScoringConfigView:
    return ScoringConfigView(
        id=config.id,
        place_1_coefficient=config.place_1_coefficient,
        place_2_coefficient=config.place_2_coefficient,
        place_3_coefficient=config.place_3_coefficient,
        place_4_coefficient=config.place_4_coefficient,
        place_5_coefficient=config.place_5_coefficient,
        knockout_small_points=config.knockout_small_points,
        knockout_big_points=config.knockout_big_points,
    )


def season_proposal_view(prompt: AdminPrompt) -> SeasonProposalView:
    payload = SeasonProposalPayload.from_json(prompt.payload)
    return SeasonProposalView(
        id=prompt.id,
        name=payload.name,
        starts_at=payload.starts_at,
        scoring_config_id=payload.scoring_config_id,
    )


def validate_season_name(value: object) -> str:
    if not isinstance(value, str):
        raise SeasonNameInvalidError
    name = " ".join(value.split())
    if not name:
        raise SeasonNameInvalidError
    return name


def season_name_for_date(value: date) -> str:
    quarter = (value.month - 1) // 3 + 1
    return f"{SEASON_NAME_BY_QUARTER[quarter]} {value.year}"


async def next_season_proposal_key(repository: AdminPromptRepository) -> str:
    prompts = await repository.list_by_scope(
        AdminPromptKind.SEASON_PROPOSAL,
        SEASON_PROPOSAL_SCOPE_KEY,
    )
    return f"{SEASON_PROPOSAL_SCOPE_KEY}:{len(prompts) + 1}"


season_service = SeasonService(SessionFactory)
