from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ScoringConfig, Season
from app.db.models.enums import SeasonStatus, UserRole, UserStatus
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import ScoringConfigView, SeasonStatusView, SeasonView
from app.services.user_service import AdminAccessDeniedError


class SeasonNotFoundError(ValueError):
    pass


class SeasonNameAlreadyExistsError(ValueError):
    pass


class SeasonScoringConfigNotFoundError(ValueError):
    pass


class SeasonStartDateError(ValueError):
    pass


class SeasonConflictError(ValueError):
    pass


class SeasonService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_active_season(self) -> SeasonView:
        async with self.session_factory() as session:
            season = await SeasonRepository(session).get_active()
            if season is None:
                raise SeasonNotFoundError
            return season_view(season)

    async def list_seasons(self) -> list[SeasonView]:
        async with self.session_factory() as session:
            seasons = await SeasonRepository(session).list_all()
            return [season_view(season) for season in seasons]

    async def list_scoring_configs(self, admin_telegram_id: int) -> list[ScoringConfigView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            configs = await ScoringConfigRepository(session).list_all()
            return [scoring_config_view(config) for config in configs]

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
            return season_view(season)

    @classmethod
    async def _open_season_in_session(
        cls,
        session: AsyncSession,
        admin_telegram_id: int,
        name: str,
        starts_at: date,
        scoring_config_id: int,
    ) -> Season:
        await cls._require_admin(session, admin_telegram_id)
        repository = SeasonRepository(session)
        if await repository.get_by_name(name) is not None:
            raise SeasonNameAlreadyExistsError
        if await ScoringConfigRepository(session).get_by_id(scoring_config_id) is None:
            raise SeasonScoringConfigNotFoundError

        active_season = await repository.get_active()
        if active_season is not None:
            if starts_at <= active_season.starts_at:
                raise SeasonStartDateError
            active_season.status = SeasonStatus.CLOSED
            active_season.ends_at = starts_at - timedelta(days=1)

        season = Season(
            name=name,
            scoring_config_id=scoring_config_id,
            starts_at=starts_at,
            ends_at=None,
            status=SeasonStatus.ACTIVE,
        )
        repository.add(season)
        return season

    @staticmethod
    async def _require_admin(session: AsyncSession, telegram_id: int) -> None:
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError


def season_view(season: Season) -> SeasonView:
    return SeasonView(
        id=season.id,
        name=season.name,
        starts_at=season.starts_at,
        ends_at=season.ends_at,
        status=SeasonStatusView(season.status.value),
        scoring_config_id=season.scoring_config_id,
    )


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


season_service = SeasonService(SessionFactory)
