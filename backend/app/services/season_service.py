import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AdminPrompt, ScoringConfig, Season
from app.db.models.enums import AdminPromptStatus, UserRole, UserStatus
from app.db.repositories.admin_prompt_repository import AdminPromptRepository
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import (
    ScoringConfigView,
    SeasonLifecycleStateView,
    SeasonProposalView,
    SeasonView,
)
from app.services.user_service import AdminAccessDeniedError


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


SEASON_PROPOSAL_KIND = "season_proposal"
SEASON_NAME_BY_QUARTER = {
    1: "Зима",
    2: "Весна",
    3: "Лето",
    4: "Осень",
}


class SeasonService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_active_season(self, today: date | None = None) -> SeasonView:
        business_date = today or date.today()
        async with self.session_factory() as session:
            season = await SeasonRepository(session).get_for_date(business_date)
            if season is None:
                raise SeasonNotFoundError
            return season_view(season, today=business_date)

    async def list_seasons(self, today: date | None = None) -> list[SeasonView]:
        business_date = today or date.today()
        async with self.session_factory() as session:
            seasons = await SeasonRepository(session).list_all()
            return [season_view(season, today=business_date) for season in seasons]

    async def list_scoring_configs(self, admin_telegram_id: int) -> list[ScoringConfigView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            configs = await ScoringConfigRepository(session).list_all()
            return [scoring_config_view(config) for config in configs]

    async def create_season_proposal(
        self,
        admin_telegram_id: int,
        today: date | None = None,
    ) -> SeasonProposalView:
        business_date = today or date.today()
        starts_at = business_date + timedelta(days=1)
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            scoring_config = await self._default_scoring_config(session, starts_at)
            if scoring_config is None:
                raise SeasonScoringConfigNotFoundError
            proposal = AdminPrompt(
                key=season_proposal_key(admin_telegram_id),
                kind=SEASON_PROPOSAL_KIND,
                payload=season_proposal_payload(
                    name=season_name_for_date(starts_at),
                    starts_at=starts_at,
                    scoring_config_id=scoring_config.id,
                ),
                status=AdminPromptStatus.PENDING,
            )
            session.add(proposal)
            await session.commit()
            await session.refresh(proposal)
            return await self._season_proposal_view(
                session,
                proposal,
                starts_at,
                today=business_date,
            )

    async def get_season_proposal(
        self,
        prompt_id: int,
        today: date | None = None,
    ) -> SeasonProposalView:
        async with self.session_factory() as session:
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            return await self._season_proposal_view(session, prompt, today=today)

    async def update_season_proposal_name(
        self,
        prompt_id: int,
        name: str,
    ) -> SeasonProposalView:
        validated_name = validate_season_name(name)
        async with self.session_factory() as session:
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            payload = season_proposal_dict(prompt)
            payload["name"] = validated_name
            prompt.payload = json.dumps(payload, ensure_ascii=False)
            await session.commit()
            await session.refresh(prompt)
            return await self._season_proposal_view(session, prompt)

    async def update_season_proposal_start_date(
        self,
        prompt_id: int,
        starts_at: date,
    ) -> SeasonProposalView:
        async with self.session_factory() as session:
            await self._validate_season_start_date(session, starts_at)
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            payload = season_proposal_dict(prompt)
            payload["starts_at"] = starts_at.isoformat()
            prompt.payload = json.dumps(payload, ensure_ascii=False)
            await session.commit()
            await session.refresh(prompt)
            return await self._season_proposal_view(session, prompt, starts_at)

    async def confirm_season_proposal(
        self,
        admin_telegram_id: int,
        prompt_id: int,
        today: date | None = None,
    ) -> SeasonView:
        business_date = today or date.today()
        async with self.session_factory() as session:
            try:
                prompt = await self._get_pending_season_proposal(session, prompt_id)
                payload = season_proposal_dict(prompt)
                season = await self._create_proposed_season_in_session(
                    session=session,
                    admin_telegram_id=admin_telegram_id,
                    name=str(payload["name"]),
                    starts_at=date.fromisoformat(str(payload["starts_at"])),
                    scoring_config_id=int(payload["scoring_config_id"]),
                    today=business_date,
                )
                prompt.status = AdminPromptStatus.CONFIRMED
                prompt.resolved_at = datetime.now(UTC)
                prompt.resolved_by_admin_id = admin_telegram_id
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
            await self._require_admin(session, admin_telegram_id)
            prompt = await self._get_pending_season_proposal(session, prompt_id)
            prompt.status = AdminPromptStatus.CANCELLED
            prompt.resolved_at = datetime.now(UTC)
            prompt.resolved_by_admin_id = admin_telegram_id
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
                season = await self._open_season_in_session(
                    session=session,
                    admin_telegram_id=admin_telegram_id,
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
        admin_telegram_id: int,
        name: str,
        starts_at: date,
        scoring_config_id: int,
    ) -> Season:
        name = validate_season_name(name)
        await cls._require_admin(session, admin_telegram_id)
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
        admin_telegram_id: int,
        name: str,
        starts_at: date,
        scoring_config_id: int,
        today: date,
    ) -> Season:
        name = validate_season_name(name)
        await cls._require_admin(session, admin_telegram_id)
        repository = SeasonRepository(session)
        if await repository.get_by_name(name) is not None:
            raise SeasonNameAlreadyExistsError
        if await ScoringConfigRepository(session).get_by_id(scoring_config_id) is None:
            raise SeasonScoringConfigNotFoundError

        if starts_at < today:
            raise SeasonStartDateError

        active_season = await repository.get_for_date(today)
        scheduled_season = await repository.get_scheduled_after(today)
        if scheduled_season is not None:
            raise SeasonScheduledConflictError

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
        else:
            overlaps = await repository.find_overlapping(starts_at=starts_at, ends_at=None)
            if overlaps:
                raise SeasonDateOverlapError

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

    @staticmethod
    async def _season_proposal_view(
        session: AsyncSession,
        prompt: AdminPrompt,
        starts_at: date | None = None,
        today: date | None = None,
    ) -> SeasonProposalView:
        proposal = season_proposal_view(prompt)
        proposal_starts_at = starts_at or proposal.starts_at
        active_season = await SeasonRepository(session).get_for_date(today or date.today())
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

    @staticmethod
    async def _get_pending_season_proposal(
        session: AsyncSession,
        prompt_id: int,
    ) -> AdminPrompt:
        prompt = await AdminPromptRepository(session).get_by_id(prompt_id)
        if prompt is None or prompt.kind != SEASON_PROPOSAL_KIND:
            raise SeasonProposalNotFoundError
        if prompt.status != AdminPromptStatus.PENDING:
            raise SeasonProposalAlreadyResolvedError
        season_proposal_dict(prompt)
        return prompt

    @classmethod
    async def _validate_season_start_date(
        cls,
        session: AsyncSession,
        starts_at: date,
    ) -> None:
        open_ended_season = await SeasonRepository(session).get_open_ended()
        if open_ended_season is not None and starts_at <= open_ended_season.starts_at:
            raise SeasonStartDateError

    @staticmethod
    async def _require_admin(session: AsyncSession, telegram_id: int) -> None:
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError


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
    payload = season_proposal_dict(prompt)
    return SeasonProposalView(
        id=prompt.id,
        name=str(payload["name"]),
        starts_at=date.fromisoformat(str(payload["starts_at"])),
        scoring_config_id=int(payload["scoring_config_id"]),
    )


def season_proposal_dict(prompt: AdminPrompt) -> dict[str, object]:
    try:
        payload = json.loads(prompt.payload)
        if not isinstance(payload, dict):
            raise SeasonProposalInvalidPayloadError
        name = validate_season_name(payload.get("name"))
        starts_at = date.fromisoformat(str(payload["starts_at"]))
        scoring_config_id = int(payload["scoring_config_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SeasonProposalInvalidPayloadError from error
    return {
        "name": name,
        "starts_at": starts_at.isoformat(),
        "scoring_config_id": scoring_config_id,
    }


def season_proposal_payload(
    *,
    name: str,
    starts_at: date,
    scoring_config_id: int,
) -> str:
    return json.dumps(
        {
            "name": validate_season_name(name),
            "starts_at": starts_at.isoformat(),
            "scoring_config_id": scoring_config_id,
        },
        ensure_ascii=False,
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


def season_proposal_key(admin_telegram_id: int) -> str:
    return f"season:{admin_telegram_id}:{datetime.now(UTC).isoformat()}:{uuid4().hex}"


season_service = SeasonService(SessionFactory)
