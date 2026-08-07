from dataclasses import dataclass

from app.db.models.enums import AdminPromptKind, AdminPromptStatus


@dataclass(frozen=True)
class AdminPromptView:
    id: int
    kind: AdminPromptKind
    payload: str
    status: AdminPromptStatus
