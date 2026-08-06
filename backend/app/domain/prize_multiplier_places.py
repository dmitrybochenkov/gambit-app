from __future__ import annotations

import json
from collections.abc import Iterable


class PrizeMultiplierPlacesError(ValueError):
    pass


def parse_prize_multiplier_places(value: str | None) -> tuple[int, ...]:
    if value is None:
        return ()
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PrizeMultiplierPlacesError from exc
    return _normalize_places(decoded)


def serialize_prize_multiplier_places(places: Iterable[int] | None) -> str | None:
    if places is None:
        return None
    normalized = _normalize_places(list(places))
    if not normalized:
        return None
    return json.dumps(list(normalized), separators=(",", ":"))


def _normalize_places(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise PrizeMultiplierPlacesError
    normalized: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            raise PrizeMultiplierPlacesError
        if item < 1 or item > 5:
            raise PrizeMultiplierPlacesError
        if item in normalized:
            raise PrizeMultiplierPlacesError
        normalized.append(item)
    return tuple(sorted(normalized))
