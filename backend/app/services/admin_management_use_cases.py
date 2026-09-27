import logging
from typing import Protocol

from app.services.admin_management_service import (
    AdminManagementService,
    admin_management_service,
)
from app.services.dto.users import UserView

logger = logging.getLogger(__name__)


class AdminPromotionNotificationDelivery(Protocol):
    async def deliver(self, promoted_user: UserView) -> None: ...


class AdminManagementUseCases:
    def __init__(self, service: AdminManagementService) -> None:
        self._service = service

    async def promote_admin(
        self,
        *,
        superadmin_telegram_id: int,
        user_id: int,
        delivery: AdminPromotionNotificationDelivery,
    ) -> UserView:
        promoted_user = await self._service.add_admin(
            superadmin_telegram_id=superadmin_telegram_id,
            user_id=user_id,
        )
        try:
            await delivery.deliver(promoted_user)
        except Exception:
            logger.exception(
                "Admin promotion notification delivery failed",
                extra={"promoted_user_id": promoted_user.id},
            )
        return promoted_user


admin_management_use_cases = AdminManagementUseCases(admin_management_service)
