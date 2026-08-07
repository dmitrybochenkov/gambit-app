from datetime import datetime

from app.db.models import AdminPrompt, User
from app.db.models.enums import AdminPromptStatus


class AdminPromptService:
    @staticmethod
    def require_pending(
        prompt: AdminPrompt,
        error: type[Exception],
    ) -> None:
        if prompt.status != AdminPromptStatus.PENDING:
            raise error()

    @staticmethod
    def confirm(
        prompt: AdminPrompt,
        *,
        actor: User,
        resolved_at: datetime,
    ) -> None:
        AdminPromptService._resolve(
            prompt,
            actor=actor,
            resolved_at=resolved_at,
            status=AdminPromptStatus.CONFIRMED,
        )

    @staticmethod
    def cancel(
        prompt: AdminPrompt,
        *,
        actor: User,
        resolved_at: datetime,
    ) -> None:
        AdminPromptService._resolve(
            prompt,
            actor=actor,
            resolved_at=resolved_at,
            status=AdminPromptStatus.CANCELLED,
        )

    @staticmethod
    def _resolve(
        prompt: AdminPrompt,
        *,
        actor: User,
        resolved_at: datetime,
        status: AdminPromptStatus,
    ) -> None:
        prompt.status = status
        prompt.resolved_at = resolved_at
        prompt.resolved_by_user_id = actor.id


admin_prompt_service = AdminPromptService()
