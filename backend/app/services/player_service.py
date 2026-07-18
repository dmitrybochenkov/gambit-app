import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Player, RegistrationMatch
from app.db.models.enums import PlayerRole, PlayerStatus
from app.db.repositories.player_repository import PlayerRepository
from app.db.session import SessionFactory
from app.services.dto import (
    AdminPanelView,
    PlayerRoleView,
    PlayerStatusView,
    PlayerView,
    RegistrationMatchView,
    RegistrationNotificationView,
    RegistrationReviewResultView,
    RegistrationReviewView,
)


class IdentityAlreadyExistsError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already exists")


class RegistrationNotAllowedError(ValueError):
    pass


class AdminAccessDeniedError(ValueError):
    pass


class PlayerNotFoundError(ValueError):
    pass


class RegistrationAlreadyReviewedError(ValueError):
    pass


class RegistrationMatchNotFoundError(ValueError):
    pass


class PlayerService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_telegram_id(self, telegram_id: int) -> PlayerView | None:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            return player_view(player)

    async def validate_unique_identity(
        self,
        telegram_id: int,
        full_name: str | None,
        nickname: str | None,
    ) -> None:
        full_name_normalized = normalize_full_name(full_name)
        nickname_normalized = normalize_nickname(nickname)
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            if full_name and full_name_normalized and await repository.full_name_exists(
                full_name,
                full_name_normalized,
                telegram_id,
            ):
                raise IdentityAlreadyExistsError("full_name")
            if nickname and nickname_normalized and await repository.nickname_exists(
                nickname,
                nickname_normalized,
                telegram_id,
            ):
                raise IdentityAlreadyExistsError("nickname")

    async def get_active_admins(self) -> list[PlayerView]:
        async with self.session_factory() as session:
            players = await PlayerRepository(session).list_active_admins()
            return [required_player_view(player) for player in players]

    async def get_pending_reviews_for_admin(
        self,
        admin_telegram_id: int,
    ) -> list[RegistrationReviewView]:
        admin_panel = await self.get_admin_panel_for_admin(admin_telegram_id)
        return admin_panel.reviews

    async def get_admin_panel_for_admin(
        self,
        admin_telegram_id: int,
    ) -> AdminPanelView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            admin = await self._require_admin(repository, admin_telegram_id)
            reviews: list[RegistrationReviewView] = []
            for player in await repository.list_pending():
                matches = await repository.list_registration_matches(player.id)
                reviews.append(
                    RegistrationReviewView(
                        player=required_player_view(player),
                        matches=[
                            registration_match_view(match, historical_player)
                            for match, historical_player in matches
                        ],
                    )
                )
            return AdminPanelView(
                admin=required_player_view(admin),
                reviews=reviews,
            )

    async def get_registration_matches_for_admin(
        self,
        admin_telegram_id: int,
        pending_player_id: int,
    ) -> list[RegistrationMatchView]:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_admin(repository, admin_telegram_id)
            await self._require_pending_player(repository, pending_player_id)
            matches = await repository.list_registration_matches(pending_player_id)
            return [registration_match_view(match, player) for match, player in matches]

    async def get_registration_review_for_admin(
        self,
        admin_telegram_id: int,
        pending_player_id: int,
    ) -> RegistrationReviewView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_admin(repository, admin_telegram_id)
            player = await self._require_pending_player(repository, pending_player_id)
            matches = await repository.list_registration_matches(player.id)
            return RegistrationReviewView(
                player=required_player_view(player),
                matches=[
                    registration_match_view(match, historical_player)
                    for match, historical_player in matches
                ],
            )

    async def approve_registration(
        self,
        admin_telegram_id: int,
        player_id: int,
        use_registration_match: bool = True,
        historical_player_id: int | None = None,
    ) -> RegistrationReviewResultView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            admin = await self._require_admin(repository, admin_telegram_id)
            player = await self._require_pending_player(repository, player_id)
            registration_matches = await repository.list_registration_matches(player.id)
            admins = await repository.list_active_admins()

            if use_registration_match and registration_matches:
                historical_player = _select_registration_match(
                    registration_matches=registration_matches,
                    historical_player_id=historical_player_id,
                )
                await session.delete(player)
                await session.flush()
                self._approve_player(
                    player=historical_player,
                    admin=admin,
                    telegram_id=player.telegram_id,
                    full_name=player.full_name,
                    full_name_normalized=player.full_name_normalized,
                    nickname=player.nickname,
                    nickname_normalized=player.nickname_normalized,
                )
                await session.commit()
                await session.refresh(historical_player)
                return RegistrationReviewResultView(
                    player=required_player_view(historical_player),
                    admins=[required_player_view(admin) for admin in admins],
                )

            self._approve_player(player=player, admin=admin)
            await session.commit()
            await session.refresh(player)
            return RegistrationReviewResultView(
                player=required_player_view(player),
                admins=[required_player_view(admin) for admin in admins],
            )

    async def get_registration_notification(
        self,
        player_id: int,
    ) -> RegistrationNotificationView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            player = await repository.get_by_id(player_id)
            if player is None:
                raise PlayerNotFoundError
            matches = await repository.list_registration_matches(player.id)
            admins = await repository.list_active_admins()
            return RegistrationNotificationView(
                player=required_player_view(player),
                admins=[required_player_view(admin) for admin in admins],
                matches=[
                    registration_match_view(match, historical_player)
                    for match, historical_player in matches
                ],
            )

    async def reject_registration(
        self,
        admin_telegram_id: int,
        player_id: int,
    ) -> RegistrationReviewResultView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_admin(repository, admin_telegram_id)
            player = await self._require_pending_player(repository, player_id)
            player_result = required_player_view(player)
            admins = await repository.list_active_admins()
            await repository.delete_registration_matches(player.id)
            await session.delete(player)
            await session.commit()
            return RegistrationReviewResultView(
                player=player_result,
                admins=[required_player_view(admin) for admin in admins],
            )

    async def submit_registration(
        self,
        telegram_id: int,
        full_name: str | None,
        nickname: str | None,
    ) -> PlayerView:
        full_name_normalized = normalize_full_name(full_name)
        nickname_normalized = normalize_nickname(nickname)
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            current_player = await repository.get_by_telegram_id(telegram_id)
            if current_player and current_player.status in {
                PlayerStatus.ACTIVE,
                PlayerStatus.BLOCKED,
            }:
                raise RegistrationNotAllowedError

            if full_name and full_name_normalized and await repository.full_name_exists(
                full_name,
                full_name_normalized,
                telegram_id,
            ):
                raise IdentityAlreadyExistsError("full_name")
            if nickname and nickname_normalized and await repository.nickname_exists(
                nickname,
                nickname_normalized,
                telegram_id,
            ):
                raise IdentityAlreadyExistsError("nickname")

            player = await repository.save_pending_registration(
                telegram_id=telegram_id,
                full_name=full_name,
                full_name_normalized=full_name_normalized,
                nickname=nickname,
                nickname_normalized=nickname_normalized,
            )
            await session.flush()
            match_candidates = await self._find_registration_match_candidates(
                repository=repository,
                pending_player=player,
            )
            await repository.replace_registration_matches(player.id, match_candidates)
            await session.commit()
            await session.refresh(player)
            return required_player_view(player)

    @staticmethod
    def _approve_player(
        player: Player,
        admin: Player,
        telegram_id: int | None = None,
        full_name: str | None = None,
        full_name_normalized: str | None = None,
        nickname: str | None = None,
        nickname_normalized: str | None = None,
    ) -> None:
        if telegram_id is not None:
            player.telegram_id = telegram_id
        if full_name and not player.full_name:
            player.full_name = full_name
            player.full_name_normalized = full_name_normalized
        if nickname and not player.nickname:
            player.nickname = nickname
            player.nickname_normalized = nickname_normalized
        if player.full_name and not player.full_name_normalized:
            player.full_name_normalized = normalize_full_name(player.full_name)
        if player.nickname and not player.nickname_normalized:
            player.nickname_normalized = normalize_nickname(player.nickname)
        player.status = PlayerStatus.ACTIVE
        player.approved_at = datetime.now(UTC)
        player.approved_by_admin_id = admin.id

    @staticmethod
    async def _find_registration_match_candidates(
        repository: PlayerRepository,
        pending_player: Player,
    ) -> list[tuple[int, int, str]]:
        historical_players = await repository.list_historical_players()
        candidates = []
        for historical_player in historical_players:
            candidate = _score_registration_match(pending_player, historical_player)
            if candidate is not None:
                candidates.append((historical_player.id, *candidate))
        return sorted(candidates, key=lambda item: (-item[1], item[0]))[:3]

    @staticmethod
    async def _require_admin(
        repository: PlayerRepository,
        telegram_id: int,
    ) -> Player:
        admin = await repository.get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != PlayerStatus.ACTIVE
            or admin.role not in {PlayerRole.ADMIN, PlayerRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError
        return admin

    @staticmethod
    async def _require_pending_player(
        repository: PlayerRepository,
        player_id: int,
    ) -> Player:
        player = await repository.get_by_id(player_id)
        if player is None:
            raise PlayerNotFoundError
        if player.status != PlayerStatus.PENDING:
            raise RegistrationAlreadyReviewedError
        return player


player_service = PlayerService(SessionFactory)


def player_view(player: Player | None) -> PlayerView | None:
    if player is None:
        return None
    return required_player_view(player)


def required_player_view(player: Player) -> PlayerView:
    return PlayerView(
        id=player.id,
        telegram_id=player.telegram_id,
        display_name=player.display_name,
        full_name=player.full_name,
        nickname=player.nickname,
        status=PlayerStatusView(player.status.value),
        role=PlayerRoleView(player.role.value),
    )


def registration_match_view(
    registration_match: RegistrationMatch,
    historical_player: Player,
) -> RegistrationMatchView:
    return RegistrationMatchView(
        score=registration_match.score,
        reason=registration_match.reason,
        historical_player=required_player_view(historical_player),
    )


def normalize_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized or None


def normalize_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().replace("ё", "е").strip()
    normalized = normalized.removeprefix("@")
    normalized = re.sub(r"[\s._-]+", "", normalized)
    normalized = re.sub(r"[^0-9a-zа-я]+", "", normalized)
    return normalized or None


def _score_registration_match(
    pending_player: Player,
    historical_player: Player,
) -> tuple[int, str] | None:
    scores: list[tuple[int, str]] = []
    pending_full_name = pending_player.full_name_normalized or normalize_full_name(
        pending_player.full_name
    )
    historical_full_name = historical_player.full_name_normalized or normalize_full_name(
        historical_player.full_name
    )
    pending_nickname = pending_player.nickname_normalized or normalize_nickname(
        pending_player.nickname
    )
    historical_nickname = historical_player.nickname_normalized or normalize_nickname(
        historical_player.nickname
    )

    if pending_nickname and historical_nickname:
        nickname_score = _similarity_score(pending_nickname, historical_nickname)
        if nickname_score == 100:
            scores.append((100, "никнейм совпал"))
        elif nickname_score >= 88:
            scores.append((nickname_score, f"никнейм похож на {nickname_score}%"))

    if pending_full_name and historical_full_name:
        full_name_score = _similarity_score(pending_full_name, historical_full_name)
        if full_name_score == 100:
            scores.append((100, "имя совпало"))
        elif full_name_score >= 82:
            scores.append((full_name_score, f"имя похоже на {full_name_score}%"))

    if not scores:
        return None

    score = max(item[0] for item in scores)
    reason = ", ".join(item[1] for item in sorted(scores, reverse=True))
    return score, reason


def _select_registration_match(
    registration_matches: list[tuple[RegistrationMatch, Player]],
    historical_player_id: int | None,
) -> Player:
    if historical_player_id is None:
        return registration_matches[0][1]

    for _, historical_player in registration_matches:
        if historical_player.id == historical_player_id:
            return historical_player
    raise RegistrationMatchNotFoundError


def _similarity_score(left: str, right: str) -> int:
    return round(SequenceMatcher(None, left, right).ratio() * 100)
