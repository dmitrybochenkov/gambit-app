from typing import Protocol


class TitleBadge(Protocol):
    kind: str


TITLE_EMOJI_BY_KIND = {
    "champion": "💍",
    "knockout": "💥",
}


def title_emojis(title_badges: tuple[TitleBadge, ...]) -> str:
    return "".join(TITLE_EMOJI_BY_KIND[badge.kind] for badge in title_badges)
