import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import (
    Player,
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
    TournamentResult,
    TournamentResultDraft,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    PlayerRole,
    PlayerStatus,
    RegistrationStatus,
    TournamentStatus,
)
from app.db.repositories.player_repository import PlayerRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory
from app.services.dto import (
    TournamentResultDraftPlayerView,
    TournamentResultDraftView,
    TournamentView,
)
from app.services.player_service import AdminAccessDeniedError
from app.services.tournament_service import tournament_view


class ResultTournamentNotFoundError(ValueError):
    pass


class ResultPlayerNotFoundError(ValueError):
    pass


class ResultInvalidPoolError(ValueError):
    pass


class ResultInvalidPlayerDataError(ValueError):
    pass


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


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
            result = await session.execute(
                select(Tournament)
                .options(selectinload(Tournament.tournament_type))
                .where(
                    Tournament.status == TournamentStatus.ACTIVE,
                    Tournament.date <= (today or date.today()),
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
            await self._require_admin(session, admin_telegram_id)
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
    ) -> TournamentResultDraftView:
        if knockouts_count < 0 or big_knockouts_count < 0:
            raise ResultInvalidPlayerDataError
        if place is not None and place not in {1, 2, 3, 4, 5}:
            raise ResultInvalidPlayerDataError
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_active_tournament(session, tournament_id)
            await self._ensure_drafts(session, tournament.id)
            draft = await self._get_draft(session, tournament.id, player_id)
            if draft is None:
                raise ResultPlayerNotFoundError
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
            await session.commit()
            return await self._draft_view(session, tournament.id)

    async def close_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultDraftView:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
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
                        bonus_points=Decimal("0"),
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
    ) -> Player:
        admin = await PlayerRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != PlayerStatus.ACTIVE
            or admin.role not in {PlayerRole.ADMIN, PlayerRole.SUPERADMIN}
        ):
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
        registered = await session.execute(
            select(TournamentRegistration.player_id).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
            )
        )
        player_ids = list(registered.scalars())
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
            select(TournamentResultDraft, Player)
            .join(Player, Player.id == TournamentResultDraft.player_id)
            .where(TournamentResultDraft.tournament_id == tournament_id)
            .order_by(Player.id)
        )
        players = [
            TournamentResultDraftPlayerView(
                player_id=player.id,
                display_name=player.display_name,
                place=draft.place,
                knockouts_count=draft.knockouts_count,
                big_knockouts_count=draft.big_knockouts_count,
            )
            for draft, player in result.all()
        ]
        players.sort(key=lambda player: player.display_name.casefold())
        rule_result = await session.execute(
            select(TournamentTypeRule.knockout_mode).where(
                TournamentTypeRule.tournament_type_id == tournament.tournament_type_id
            )
        )
        knockout_mode = rule_result.scalar_one_or_none() or KnockoutMode.NONE
        return TournamentResultDraftView(
            tournament=tournament_view(tournament),
            points_pool=tournament.points_pool,
            players=players,
            knockout_mode=knockout_mode.value,
        )

    @staticmethod
    def _validate_draft(draft: TournamentResultDraftView) -> list[str]:
        errors: list[str] = []
        if draft.points_pool is None or draft.points_pool <= 0:
            errors.append("Введи пул турнира.")
        if not draft.players:
            errors.append("Нет зарегистрированных игроков.")
        places = [player.place for player in draft.players if player.place is not None]
        missing_places = sorted({1, 2, 3, 4, 5} - set(places))
        if missing_places:
            errors.append("Введи места: " + ", ".join(str(place) for place in missing_places) + ".")
        duplicates = sorted({place for place in places if places.count(place) > 1})
        if duplicates:
            errors.append(
                "Дублируются места: " + ", ".join(str(place) for place in duplicates) + "."
            )
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


result_service = ResultService(SessionFactory)
