from decimal import Decimal

PROFILE_UNAVAILABLE = "Профиль доступен зарегистрированным игрокам. Нажми /start."
PROFILE_MENU_PROMPT = "За какой период ты хочешь посмотреть свои достижения?"
PROFILE_ACTIVE_ONLY = "Профиль доступен только активным игрокам."
PROFILE_NOT_FOUND = "Профиль не найден. Нажми /start."
PROFILE_PRIZE_PLACES_LABEL = "Количество призовых мест:"


def message(title: str, stats: object | None) -> str:
    if stats is None:
        return f"{title}\n\n{PROFILE_NOT_FOUND}"

    points = _format_decimal(stats.total_points)
    lines = [
        title,
        "⭐ - количество очков",
        "🥊 - количество нокаутов",
        "🎲 - количество турниров",
        "",
        stats.display_name,
        f"⭐ {points} | 🥊 {stats.total_knockouts_count} | 🎲 {stats.tournaments_count}",
    ]
    prize_place_lines = _prize_place_lines(stats)
    if prize_place_lines:
        lines.extend(["", PROFILE_PRIZE_PLACES_LABEL, *prize_place_lines])
    return "\n".join(lines)


def _prize_place_lines(stats: object) -> list[str]:
    prize_places = [
        ("🥇", stats.first_places_count),
        ("🥈", stats.second_places_count),
        ("🥉", stats.third_places_count),
        ("4️⃣", stats.fourth_places_count),
        ("5️⃣", stats.fifth_places_count),
    ]
    return [f"{label} x{count}" for label, count in prize_places if count > 0]


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
