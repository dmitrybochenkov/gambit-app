import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
    TournamentResultDraft,
    TournamentTypeRule,
    User,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_participant_repository import (
    TournamentParticipantRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import (
    TournamentResultDraftPlayerView,
    TournamentResultDraftView,
    TournamentView,
)
from app.services.tournament_service import tournament_view
from app.services.user_service import AdminAccessDeniedError


class ResultTournamentNotFoundError(ValueError):
    pass


class ResultUserNotFoundError(ValueError):
    pass


class ResultInvalidPoolError(ValueError):
    pass


class ResultInvalidPlayerDataError(ValueError):
    pass


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class ResultField(StrEnum):
    KNOCKOUTS = "ko"
    BIG_KNOCKOUTS = "big"
    BONUS = "bonus"
    PLACE = "place"


class ResultService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def list_open_tournaments_for_admin(
        self,
        admin_telegram_id: int,
        today: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            business_date = today or _club_today()
            result = await session.execute(
                select(Tournament)
                .options(selectinload(Tournament.tournament_type))
                .where(
                    Tournament.status == TournamentStatus.ACTIVE,
                    Tournament.date == business_date,
                )
                .order_by(Tournament.date, Tournament.tournament_type_id)
            )
            return [tournament_view(tournament) for tournament in result.scalars()]

    async def get_or_create_draft(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultDraftView:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            await session.commit()
            return await self._draft_view(session, tournament.id)

    async def set_points_pool(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        points_pool: Decimal,
    ) -> TournamentResultDraftView:
        if points_pool <= 0:
            raise ResultInvalidPoolError
        async with self.session_factory() as session:
            await self._require_superadmin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            tournament.points_pool = points_pool
            await session.commit()
            return await self._draft_view(session, tournament.id)

    async def update_player_result(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        place: int | None,
        knockouts_count: int,
        big_knockouts_count: int,
        bonus_points: int = 0,
    ) -> TournamentResultDraftView:
        if knockouts_count < 0 or big_knockouts_count < 0 or bonus_points < 0:
            raise ResultInvalidPlayerDataError
        if place is not None and place not in {1, 2, 3, 4, 5}:
            raise ResultInvalidPlayerDataError
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            draft = await self._get_draft(session, tournament.id, player_id)
            if draft is None:
                raise ResultUserNotFoundError
            if place is not None:
                result = await session.execute(
                    select(TournamentResultDraft).where(
                        TournamentResultDraft.tournament_id == tournament.id,
                        TournamentResultDraft.place == place,
                        TournamentResultDraft.id != draft.id,
                    )
                )
                for other_draft in result.scalars():
                    other_draft.place = None
            draft.place = place
            draft.knockouts_count = knockouts_count
            draft.big_knockouts_count = big_knockouts_count
            draft.bonus_points = bonus_points
            await session.commit()
            return await self._draft_view(session, tournament.id)

    async def update_player_result_field(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        field: ResultField,
        value: int,
    ) -> TournamentResultDraftView:
        draft = await self.get_or_create_draft(
            admin_telegram_id=admin_telegram_id,
            tournament_id=tournament_id,
        )
        if field == ResultField.BONUS and not draft.supports_bonus_points:
            raise ResultInvalidPlayerDataError
        if field != ResultField.BONUS and not self.result_field_is_allowed(
            draft.knockout_mode,
            field,
        ):
            raise ResultInvalidPlayerDataError
        player = self.find_result_player(draft, player_id)
        if player is None:
            raise ResultUserNotFoundError

        place = player.place
        knockouts_count = player.knockouts_count
        big_knockouts_count = player.big_knockouts_count
        bonus_points = player.bonus_points
        if field == ResultField.PLACE:
            place = value
        elif field == ResultField.KNOCKOUTS:
            knockouts_count = value
        elif field == ResultField.BIG_KNOCKOUTS:
            big_knockouts_count = value
        elif field == ResultField.BONUS:
            bonus_points = value

        return await self.update_player_result(
            admin_telegram_id=admin_telegram_id,
            tournament_id=tournament_id,
            player_id=player_id,
            place=place,
            knockouts_count=knockouts_count,
            big_knockouts_count=big_knockouts_count,
            bonus_points=bonus_points,
        )

    async def close_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultDraftView:
        async with self.session_factory() as session:
            await self._require_superadmin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            draft = await self._draft_view(session, tournament.id)
            errors = self._validate_draft(draft)
            if errors:
                raise ResultValidationError(errors)

            scoring_config, rule = await self._scoring(session, tournament)
            result = await session.execute(
                select(TournamentResultDraft).where(
                    TournamentResultDraft.tournament_id == tournament.id
                )
            )
            drafts = list(result.scalars())
            for item in drafts:
                tournament_points = self._tournament_points(
                    points_pool=tournament.points_pool or Decimal("0"),
                    place=item.place,
                    scoring_config=scoring_config,
                    rule=rule,
                )
                knockout_points = self._knockout_points(
                    knockouts_count=item.knockouts_count,
                    big_knockouts_count=item.big_knockouts_count,
                    scoring_config=scoring_config,
                    rule=rule,
                )
                session.add(
                    TournamentResult(
                        tournament_id=tournament.id,
                        player_id=item.player_id,
                        place=item.place,
                        knockouts_count=item.knockouts_count,
                        big_knockouts_count=item.big_knockouts_count,
                        tournament_points=tournament_points,
                        knockout_points=knockout_points,
                        bonus_points=Decimal(item.bonus_points),
                    )
                )
            tournament.status = TournamentStatus.CLOSED
            await session.execute(
                delete(TournamentResultDraft).where(
                    TournamentResultDraft.tournament_id == tournament.id
                )
            )
            await session.commit()
            return draft

    async def submit_results_by_admin(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultDraftView:
        async with self.session_factory() as session:
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            draft = await self._draft_view(session, tournament.id)
            errors = self._validate_admin_draft(draft)
            if errors:
                raise ResultValidationError(errors)
            tournament.results_submitted_at = datetime.now(ZoneInfo(settings.club_timezone))
            tournament.results_submitted_by_user_id = admin.id
            await session.commit()
            return draft

    async def validate_draft(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> list[str]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            await session.commit()
            draft = await self._draft_view(session, tournament.id)
            return self._validate_draft(draft)

    async def _require_admin(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError
        return admin

    async def _require_superadmin(
        self,
        session: AsyncSession,
        telegram_id: int,
    ) -> User:
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if admin is None or admin.status != UserStatus.ACTIVE or admin.role != UserRole.SUPERADMIN:
            raise AdminAccessDeniedError
        return admin

    async def _require_active_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None or tournament.status != TournamentStatus.ACTIVE:
            raise ResultTournamentNotFoundError
        return tournament

    async def _ensure_drafts(self, session: AsyncSession, tournament_id: int) -> None:
        player_ids = await TournamentParticipantRepository(session).active_participant_user_ids(
            tournament_id
        )
        existing = await session.execute(
            select(TournamentResultDraft.player_id).where(
                TournamentResultDraft.tournament_id == tournament_id
            )
        )
        existing_ids = set(existing.scalars())
        for player_id in player_ids:
            if player_id not in existing_ids:
                session.add(
                    TournamentResultDraft(
                        tournament_id=tournament_id,
                        player_id=player_id,
                        place=None,
                        knockouts_count=0,
                        big_knockouts_count=0,
                        bonus_points=0,
                    )
                )
        await session.flush()

    async def _get_draft(
        self,
        session: AsyncSession,
        tournament_id: int,
        player_id: int,
    ) -> TournamentResultDraft | None:
        result = await session.execute(
            select(TournamentResultDraft).where(
                TournamentResultDraft.tournament_id == tournament_id,
                TournamentResultDraft.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def _draft_view(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> TournamentResultDraftView:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise ResultTournamentNotFoundError
        result = await session.execute(
            select(TournamentResultDraft, User)
            .join(User, User.id == TournamentResultDraft.player_id)
            .where(TournamentResultDraft.tournament_id == tournament_id)
            .order_by(User.id)
        )
        players = [
            TournamentResultDraftPlayerView(
                player_id=player.id,
                display_name=player.display_name,
                place=draft.place,
                knockouts_count=draft.knockouts_count,
                big_knockouts_count=draft.big_knockouts_count,
                bonus_points=draft.bonus_points,
            )
            for draft, player in result.all()
        ]
        players.sort(key=lambda player: player.display_name.casefold())
        rule_result = await session.execute(
            select(
                TournamentTypeRule.knockout_mode,
                TournamentTypeRule.supports_bonus_points,
            ).where(TournamentTypeRule.tournament_type_id == tournament.tournament_type_id)
        )
        rule_row = rule_result.one_or_none()
        knockout_mode = rule_row.knockout_mode if rule_row is not None else KnockoutMode.NONE
        supports_bonus_points = (
            bool(rule_row.supports_bonus_points) if rule_row is not None else False
        )
        participant_repository = TournamentParticipantRepository(session)
        no_result_players = [
            TournamentResultDraftPlayerView(
                player_id=player.id,
                display_name=player.display_name,
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
                bonus_points=0,
            )
            for player in await participant_repository.list_no_result_players(tournament.id)
        ]
        return TournamentResultDraftView(
            tournament=tournament_view(tournament),
            points_pool=tournament.points_pool,
            players=players,
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
            participant_count=await participant_repository.participant_count(tournament.id),
            no_result_count=await participant_repository.no_result_count(tournament.id),
            no_result_players=no_result_players,
        )

    @staticmethod
    def _validate_draft(draft: TournamentResultDraftView) -> list[str]:
        errors: list[str] = []
        if draft.points_pool is None or draft.points_pool <= 0:
            errors.append("Введи пул турнира.")
        errors.extend(ResultService._validate_admin_draft(draft))
        return errors

    @staticmethod
    def _validate_admin_draft(draft: TournamentResultDraftView) -> list[str]:
        errors: list[str] = []
        if not draft.players:
            errors.append("Нет участников турнира.")
        places = [player.place for player in draft.players if player.place is not None]
        participant_count = draft.participant_count or len(draft.players)
        required_places = set(range(1, min(5, participant_count) + 1))
        missing_places = sorted(required_places - set(places))
        if missing_places:
            errors.append("Введи места: " + ", ".join(str(place) for place in missing_places) + ".")
        duplicates = sorted({place for place in places if places.count(place) > 1})
        if duplicates:
            errors.append(
                "Дублируются места: " + ", ".join(str(place) for place in duplicates) + "."
            )
        small_knockouts = sum(player.knockouts_count for player in draft.players)
        big_knockouts = sum(player.big_knockouts_count for player in draft.players)
        if draft.knockout_mode == KnockoutMode.SMALL.value and small_knockouts <= 0:
            errors.append("Введи хотя бы один 🥊.")
        if (
            draft.knockout_mode == KnockoutMode.SMALL_BIG.value
            and (small_knockouts + big_knockouts) <= 0
        ):
            errors.append("Введи хотя бы один 🥊 или 👑🥊.")
        return errors

    async def _scoring(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> tuple[ScoringConfig, TournamentTypeRule | None]:
        season = await session.get(Season, tournament.season_id)
        if season is None:
            raise ResultTournamentNotFoundError
        scoring_config = await session.get(ScoringConfig, season.scoring_config_id)
        if scoring_config is None:
            raise ResultTournamentNotFoundError
        rule_result = await session.execute(
            select(TournamentTypeRule).where(
                TournamentTypeRule.tournament_type_id == tournament.tournament_type_id
            )
        )
        return scoring_config, rule_result.scalar_one_or_none()

    @staticmethod
    def _tournament_points(
        points_pool: Decimal,
        place: int | None,
        scoring_config: ScoringConfig,
        rule: TournamentTypeRule | None,
    ) -> Decimal:
        if place is None or place not in {1, 2, 3, 4, 5}:
            return Decimal("0")
        coefficient = getattr(scoring_config, f"place_{place}_coefficient")
        multiplier = rule.points_multiplier if rule is not None else Decimal("1")
        if rule is not None and rule.prize_place_multiplier_places:
            places = set(json.loads(rule.prize_place_multiplier_places))
            if place in places:
                multiplier *= rule.prize_place_multiplier
        return (points_pool * coefficient * multiplier).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _knockout_points(
        knockouts_count: int,
        big_knockouts_count: int,
        scoring_config: ScoringConfig,
        rule: TournamentTypeRule | None,
    ) -> Decimal:
        if rule is None or rule.knockout_mode == KnockoutMode.NONE:
            return Decimal("0")
        if rule.knockout_mode == KnockoutMode.SMALL:
            points = knockouts_count * scoring_config.knockout_small_points
        else:
            points = (
                knockouts_count * scoring_config.knockout_small_points
                + big_knockouts_count * scoring_config.knockout_big_points
            )
        return Decimal(points).quantize(Decimal("0.01"))

    @staticmethod
    def find_result_player(
        draft: TournamentResultDraftView,
        player_id: int,
    ) -> TournamentResultDraftPlayerView | None:
        return next(
            (player for player in draft.players if player.player_id == player_id),
            None,
        )

    @staticmethod
    def result_field_is_allowed(
        knockout_mode: str,
        field: ResultField,
    ) -> bool:
        if field == ResultField.KNOCKOUTS:
            return knockout_mode in {"small", "small_big"}
        if field == ResultField.BIG_KNOCKOUTS:
            return knockout_mode == "small_big"
        if field == ResultField.BONUS:
            return False
        return field == ResultField.PLACE

    @staticmethod
    def occupied_result_places(draft: TournamentResultDraftView) -> set[int]:
        return {player.place for player in draft.players if player.place is not None}


result_service = ResultService(SessionFactory)


def _club_today() -> date:
    return datetime.now(ZoneInfo(settings.club_timezone)).date()
