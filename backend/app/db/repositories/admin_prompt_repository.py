from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminPrompt
from app.db.models.enums import AdminPromptStatus


class AdminPromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, prompt_id: int) -> AdminPrompt | None:
        return await self.session.get(AdminPrompt, prompt_id)

    async def get_by_key(self, key: str) -> AdminPrompt | None:
        result = await self.session.execute(
            select(AdminPrompt).where(AdminPrompt.key == key)
        )
        return result.scalar_one_or_none()

    async def get_or_create_pending(
        self,
        key: str,
        kind: str,
        payload: str,
    ) -> AdminPrompt:
        prompt = await self.get_by_key(key)
        if prompt is not None:
            return prompt

        prompt = AdminPrompt(
            key=key,
            kind=kind,
            payload=payload,
            status=AdminPromptStatus.PENDING,
        )
        self.session.add(prompt)
        await self.session.flush()
        return prompt
