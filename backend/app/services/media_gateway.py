from dataclasses import dataclass
from typing import Protocol


class MediaGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaContent:
    data: bytes
    content_type: str


class TelegramMediaGateway(Protocol):
    async def download_photo(self, source_reference: str) -> MediaContent: ...
