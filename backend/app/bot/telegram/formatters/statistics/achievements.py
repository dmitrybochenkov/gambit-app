from app.domain.hall_of_fame import ACHIEVEMENT_KIND_ORDER as DOMAIN_ACHIEVEMENT_KIND_ORDER

ACHIEVEMENT_KIND_ORDER = tuple(kind.value for kind in DOMAIN_ACHIEVEMENT_KIND_ORDER)

_DATED_ACHIEVEMENT_KINDS = {"grand_month", "grand_knockout"}


def achievement_shows_date(kind: str) -> bool:
    return kind in _DATED_ACHIEVEMENT_KINDS
