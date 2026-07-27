from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.normalization import normalize_display_name
from app.db.factories import create_player
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


class InvalidDisplayNameError(ValueError):
    pass


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


class PlayerRoleAlreadyAssignedError(ValueError):
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
        display_name: str,
    ) -> None:
        display_name_normalized = _require_valid_display_name(display_name)
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            if (
                display_name
                and display_name_normalized
                and await repository.display_name_exists(
                    display_name,
                    display_name_normalized,
                    telegram_id,
                )
            ):
                raise IdentityAlreadyExistsError("display_name")

    async def get_active_admins(self) -> list[PlayerView]:
        async with self.session_factory() as session:
            players = await PlayerRepository(session).list_active_admins()
            return [required_player_view(player) for player in players]

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

    async def require_superadmin(self, telegram_id: int) -> PlayerView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            admin = await self._require_superadmin(repository, telegram_id)
            return required_player_view(admin)

    async def list_admin_candidates_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[PlayerView]:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_superadmin(repository, superadmin_telegram_id)
            players = await repository.list_active_non_admins()
            return [required_player_view(player) for player in players]

    async def add_admin(
        self,
        superadmin_telegram_id: int,
        player_id: int,
    ) -> PlayerView:
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            await self._require_superadmin(repository, superadmin_telegram_id)
            player = await repository.get_by_id(player_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise PlayerNotFoundError
            if player.role != PlayerRole.USER:
                raise PlayerRoleAlreadyAssignedError

            player.role = PlayerRole.ADMIN
            await session.commit()
            await session.refresh(player)
            return required_player_view(player)

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
                    display_name=player.display_name,
                    display_name_normalized=player.display_name_normalized,
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
        display_name: str,
    ) -> PlayerView:
        display_name_normalized = _require_valid_display_name(display_name)
        async with self.session_factory() as session:
            repository = PlayerRepository(session)
            current_player = await repository.get_by_telegram_id(telegram_id)
            if current_player and current_player.status in {
                PlayerStatus.ACTIVE,
                PlayerStatus.BLOCKED,
            }:
                raise RegistrationNotAllowedError

            if (
                display_name
                and await repository.display_name_exists(
                    display_name,
                    display_name_normalized,
                    telegram_id,
                )
            ):
                raise IdentityAlreadyExistsError("display_name")

            if current_player is None:
                player = create_player(
                    telegram_id=telegram_id,
                    display_name=display_name,
                    status=PlayerStatus.PENDING,
                )
                repository.add(player)
            else:
                player = current_player
                self._update_pending_registration_player(
                    player,
                    display_name=display_name,
                    display_name_normalized=display_name_normalized or display_name,
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
    def _update_pending_registration_player(
        player: Player,
        display_name: str,
        display_name_normalized: str,
    ) -> None:
        player.display_name = display_name
        player.display_name_normalized = display_name_normalized
        player.status = PlayerStatus.PENDING
        player.approved_at = None
        player.approved_by_admin_id = None

    @staticmethod
    def _approve_player(
        player: Player,
        admin: Player,
        telegram_id: int | None = None,
        display_name: str | None = None,
        display_name_normalized: str | None = None,
    ) -> None:
        if telegram_id is not None:
            player.telegram_id = telegram_id
        if display_name and not player.display_name:
            player.display_name = display_name
            player.display_name_normalized = display_name_normalized or normalize_display_name(
                display_name
            )
        if player.display_name and not player.display_name_normalized:
            player.display_name_normalized = normalize_display_name(player.display_name) or ""
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
    async def _require_superadmin(
        repository: PlayerRepository,
        telegram_id: int,
    ) -> Player:
        admin = await repository.get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != PlayerStatus.ACTIVE
            or admin.role != PlayerRole.SUPERADMIN
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


def _require_valid_display_name(display_name: str) -> str:
    display_name_normalized = normalize_display_name(display_name)
    if display_name_normalized is None or len(display_name) > 255:
        raise InvalidDisplayNameError
    return display_name_normalized


def _score_registration_match(
    pending_player: Player,
    historical_player: Player,
) -> tuple[int, str] | None:
    pending_display_name = pending_player.display_name_normalized or normalize_display_name(
        pending_player.display_name
    )
    historical_display_name = historical_player.display_name_normalized or normalize_display_name(
        historical_player.display_name
    )
    if not pending_display_name or not historical_display_name:
        return None

    score = _similarity_score(pending_display_name, historical_display_name)
    if score == 100:
        return 100, "имя игрока совпадает"
    if score >= 88:
        return score, f"имя игрока похоже на {score}%"
    return None


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
