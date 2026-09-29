import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.db.models.enums import UserGender
from app.services.closed_tournament_correction_service import ClosedTournamentCorrectionService
from app.services.dto.check_in import CheckInGenderDecision
from app.services.dto.results import (
    ClosedTournamentCorrectionDraftView,
    ClosedTournamentCorrectionResultView,
    TournamentResultsView,
)
from app.services.dto.rewards import (
    PlayerRewardCorrectionNotificationView,
    PlayerRewardNotificationView,
)
from app.services.dto.tournaments import TournamentCancellationNotificationView, TournamentView
from app.services.result_service import ResultService
from app.services.tournament_check_in_service import CheckInResultView, TournamentCheckInService
from app.services.tournament_planning_service import TournamentPlanningService

logger = logging.getLogger(__name__)


class CheckInNotificationDelivery(Protocol):
    async def deliver(self, result: CheckInResultView) -> None: ...


class TournamentCancellationDelivery(Protocol):
    async def deliver(
        self,
        notifications: tuple[TournamentCancellationNotificationView, ...],
    ) -> None: ...


class PlayerRewardNotificationDelivery(Protocol):
    async def deliver_issued(
        self,
        rewards: tuple[PlayerRewardNotificationView, ...],
    ) -> None: ...

    async def deliver_corrections(
        self,
        rewards: tuple[PlayerRewardCorrectionNotificationView, ...],
    ) -> None: ...


async def _deliver_best_effort(
    deliver: Callable[[], Awaitable[None]],
    *,
    notification_kind: str,
    entity_id: int,
) -> None:
    try:
        await deliver()
    except Exception:
        logger.exception(
            "Business notification delivery failed",
            extra={"notification_kind": notification_kind, "entity_id": entity_id},
        )


class CheckInUseCases:
    def __init__(self, service: TournamentCheckInService) -> None:
        self._service = service

    async def complete_user_check_in(
        self,
        *,
        actor_user_id: int,
        tournament_id: int,
        user_id: int,
        delivery: CheckInNotificationDelivery,
        gender_decision: CheckInGenderDecision,
        reward_id: int | None = None,
    ) -> CheckInResultView:
        if reward_id is None:
            result = await self._service.complete_user_check_in(
                actor_user_id=actor_user_id,
                tournament_id=tournament_id,
                user_id=user_id,
                gender_decision=gender_decision,
            )
        else:
            result = await self._service.complete_user_check_in(
                actor_user_id=actor_user_id,
                tournament_id=tournament_id,
                user_id=user_id,
                gender_decision=gender_decision,
                reward_id=reward_id,
            )
        if result.created:
            await _deliver_best_effort(
                lambda: delivery.deliver(result),
                notification_kind="check_in_confirmation",
                entity_id=tournament_id,
            )
        return result

    async def create_user_and_check_in(
        self,
        *,
        actor_user_id: int,
        tournament_id: int,
        display_name: str,
        gender: UserGender | None,
        delivery: CheckInNotificationDelivery,
    ) -> CheckInResultView:
        result = await self._service.create_user_and_check_in(
            actor_user_id=actor_user_id,
            tournament_id=tournament_id,
            display_name=display_name,
            gender=gender,
        )
        if result.created:
            await _deliver_best_effort(
                lambda: delivery.deliver(result),
                notification_kind="check_in_confirmation",
                entity_id=tournament_id,
            )
        return result


class TournamentPlanningUseCases:
    def __init__(self, service: TournamentPlanningService) -> None:
        self._service = service

    async def delete_calendar_tournament(
        self,
        *,
        actor_user_id: int,
        tournament_id: int,
        delivery: TournamentCancellationDelivery,
    ) -> TournamentView:
        tournament, notifications = await self._service.delete_calendar_tournament(
            actor_user_id,
            tournament_id=tournament_id,
        )
        await _deliver_best_effort(
            lambda: delivery.deliver(notifications),
            notification_kind="tournament_cancellation",
            entity_id=tournament_id,
        )
        return tournament


class TournamentRewardUseCases:
    def __init__(
        self,
        result_service: ResultService,
        correction_service: ClosedTournamentCorrectionService,
    ) -> None:
        self._result_service = result_service
        self._correction_service = correction_service

    async def close_tournament(
        self,
        *,
        actor_user_id: int,
        tournament_id: int,
        tournament_fund: int,
        delivery: PlayerRewardNotificationDelivery,
    ) -> TournamentResultsView:
        result = await self._result_service.close_tournament(
            actor_user_id,
            tournament_id,
            tournament_fund,
        )
        if result.newly_issued_rewards:
            await _deliver_best_effort(
                lambda: delivery.deliver_issued(result.newly_issued_rewards),
                notification_kind="prize_reward_issued",
                entity_id=tournament_id,
            )
        return result

    async def apply_closed_tournament_correction(
        self,
        *,
        actor_user_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        delivery: PlayerRewardNotificationDelivery,
    ) -> ClosedTournamentCorrectionResultView:
        result = await self._correction_service.apply_closed_tournament_correction(
            actor_user_id,
            draft,
        )
        if result.player_notifications:
            await _deliver_best_effort(
                lambda: delivery.deliver_corrections(result.player_notifications),
                notification_kind="prize_reward_correction",
                entity_id=draft.tournament_id,
            )
        return result
