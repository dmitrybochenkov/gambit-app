from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminPrompt
from app.db.models.enums import AdminPromptKind, AdminPromptStatus


class AdminPromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, prompt_id: int) -> AdminPrompt | None:
        return await self.session.get(AdminPrompt, prompt_id)

    async def get_by_key(self, key: str) -> AdminPrompt | None:
        result = await self.session.execute(select(AdminPrompt).where(AdminPrompt.key == key))
        return result.scalar_one_or_none()

    async def get_pending_by_scope(
        self,
        kind: AdminPromptKind,
        scope_key: str,
    ) -> AdminPrompt | None:
        result = await self.session.execute(
            select(AdminPrompt).where(
                AdminPrompt.kind == kind,
                AdminPrompt.scope_key == scope_key,
                AdminPrompt.status == AdminPromptStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_scope(
        self,
        kind: AdminPromptKind,
        scope_key: str,
    ) -> list[AdminPrompt]:
        result = await self.session.execute(
            select(AdminPrompt)
            .where(
                AdminPrompt.kind == kind,
                AdminPrompt.scope_key == scope_key,
            )
            .order_by(AdminPrompt.id)
        )
        return list(result.scalars())

    async def get_latest_confirmed_by_scope(
        self,
        kind: AdminPromptKind,
        scope_key: str,
    ) -> AdminPrompt | None:
        result = await self.session.execute(
            select(AdminPrompt)
            .where(
                AdminPrompt.kind == kind,
                AdminPrompt.scope_key == scope_key,
                AdminPrompt.status == AdminPromptStatus.CONFIRMED,
            )
            .order_by(AdminPrompt.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_prompt(
        self,
        key: str,
        kind: AdminPromptKind,
        payload: str,
        scope_key: str | None = None,
    ) -> AdminPrompt:
        prompt = AdminPrompt(
            key=key,
            scope_key=scope_key,
            kind=kind,
            payload=payload,
            status=AdminPromptStatus.PENDING,
        )
        self.session.add(prompt)
        return prompt
