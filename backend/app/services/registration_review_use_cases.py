import logging
from typing import Protocol

from app.services.dto.registrations import RegistrationReviewOutcomeView
from app.services.registration_review_service import (
    RegistrationReviewService,
    registration_review_service,
)

logger = logging.getLogger(__name__)


class RegistrationReviewNotificationDelivery(Protocol):
    async def deliver(self, outcome: RegistrationReviewOutcomeView) -> None: ...


class RegistrationReviewUseCases:
    def __init__(self, service: RegistrationReviewService) -> None:
        self._service = service

    async def approve(
        self,
        *,
        actor_user_id: int,
        request_id: int,
        delivery: RegistrationReviewNotificationDelivery,
        candidate_user_id: int | None = None,
    ) -> RegistrationReviewOutcomeView:
        if candidate_user_id is None:
            outcome = await self._service.approve_registration(
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        else:
            outcome = await self._service.approve_registration(
                actor_user_id=actor_user_id,
                request_id=request_id,
                candidate_user_id=candidate_user_id,
            )
        await self._deliver_best_effort(delivery, outcome)
        return outcome

    async def reject(
        self,
        *,
        actor_user_id: int,
        request_id: int,
        delivery: RegistrationReviewNotificationDelivery,
    ) -> RegistrationReviewOutcomeView:
        outcome = await self._service.reject_registration(
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        await self._deliver_best_effort(delivery, outcome)
        return outcome

    @staticmethod
    async def _deliver_best_effort(
        delivery: RegistrationReviewNotificationDelivery,
        outcome: RegistrationReviewOutcomeView,
    ) -> None:
        try:
            await delivery.deliver(outcome)
        except Exception:
            logger.exception(
                "Registration review notification delivery failed",
                extra={"registration_request_id": outcome.request.id},
            )


registration_review_use_cases = RegistrationReviewUseCases(registration_review_service)
