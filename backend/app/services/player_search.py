from dataclasses import dataclass
from difflib import SequenceMatcher

from app.common.normalization import normalize_display_name


class InvalidDisplayNameError(ValueError):
    pass


@dataclass(frozen=True)
class PlayerSearchCandidate:
    user: object
    score: int
    reason: str


def validate_display_name(display_name: str) -> str:
    normalized = normalize_display_name(display_name)
    if normalized is None or len(display_name) > 255:
        raise InvalidDisplayNameError
    return normalized


def player_search_score(player: object, query: str) -> int:
    normalized_query = normalize_display_name(query)
    if not normalized_query:
        return 0

    display_name = getattr(player, "display_name", None)
    display_name_normalized = getattr(player, "display_name_normalized", None)
    candidate = display_name_normalized or normalize_display_name(display_name)
    if not candidate:
        return 0

    if normalized_query == candidate:
        return 300
    if normalized_query in candidate:
        return 200 + len(normalized_query)
    ratio = SequenceMatcher(None, normalized_query, candidate).ratio()
    if ratio >= 0.55:
        return int(ratio * 100)
    return 0


def rank_player_candidates[
    UserT: object,
](
    users: list[UserT],
    query: str,
    *,
    limit: int = 10,
) -> list[PlayerSearchCandidate]:
    candidates: list[PlayerSearchCandidate] = []
    normalized = normalize_display_name(query)
    if normalized is None:
        return []
    for user in users:
        display_name_normalized = getattr(user, "display_name_normalized", None)
        candidate_name = display_name_normalized or normalize_display_name(user.display_name)
        score = player_search_score(user, query)
        if score <= 0 or candidate_name is None:
            continue
        if score == 300:
            reason = "имя игрока совпадает"
        elif normalized in candidate_name:
            reason = "имя игрока частично совпадает"
        else:
            reason = f"имя игрока похоже на {score}%"
        candidates.append(PlayerSearchCandidate(user=user, score=score, reason=reason))
    candidates.sort(key=_candidate_sort_key)
    return candidates[:limit]


def _candidate_sort_key(candidate: PlayerSearchCandidate) -> tuple[int, str, int]:
    user_id = getattr(candidate.user, "id", None)
    if user_id is None:
        user_id = getattr(candidate.user, "user_id")
    return -candidate.score, getattr(candidate.user, "display_name").casefold(), user_id
