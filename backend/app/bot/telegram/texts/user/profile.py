from app.bot.telegram.formatters import common as fmt_common

PROFILE_UNAVAILABLE = "Профиль доступен зарегистрированным игрокам. Нажми /start."
PROFILE_MENU_PROMPT = "За какой период ты хочешь посмотреть свои достижения?"
PROFILE_ACTIVE_ONLY = "Профиль доступен только активным игрокам."
PROFILE_NOT_FOUND = "Профиль не найден. Нажми /start."
PROFILE_PRIZE_PLACES_LABEL = "Количество призовых мест:"


def message(title: str, stats: object | None) -> str:
    if stats is None:
        return f"{title}\n\n{PROFILE_NOT_FOUND}"

    points = fmt_common.points(stats.total_points)
    lines = [
        title,
        "⭐ - количество очков",
        "🎯 - процент попадания в пятерку лидеров",
        "🥊 - количество нокаутов",
        "🎲 - количество турниров",
        "",
        stats.display_name,
        f"⭐ {points}{_rating_position(stats)} | 🎯 {_prize_percent(stats)} | 🥊 {stats.total_knockouts_count} | 🎲 {stats.tournaments_count}" 
    ]
    prize_place_lines = _prize_place_lines(stats)
    if prize_place_lines:
        lines.extend(["", PROFILE_PRIZE_PLACES_LABEL, *prize_place_lines])
    honour_lines = _honour_lines(stats)
    if honour_lines:
        lines.extend(["", *honour_lines])
    return "\n".join(lines)


def _rating_position(stats: object) -> str:
    position = getattr(stats, "rating_position", None)
    participants_count = getattr(stats, "rating_participants_count", 0)

    if position is None or participants_count == 0:
        return ""

    return f" ({position} место из {participants_count})"


def _prize_percent(stats: object) -> str:
    value = getattr(stats, "prize_percent", None)

    if value is None:
        return "—"

    return f"{value}%"


def _prize_place_lines(stats: object) -> list[str]:
    prize_places = [
        ("🥇", stats.first_places_count),
        ("🥈", stats.second_places_count),
        ("🥉", stats.third_places_count),
        ("4️⃣", stats.fourth_places_count),
        ("5️⃣", stats.fifth_places_count),
    ]
    return [f"{label} x{count}" for label, count in prize_places if count > 0]


def _honour_lines(stats: object) -> list[str]:
    lines = []
    for honour in stats.honours:
        if honour.kind == "champion":
            lines.append(f"💍 Победитель сезона «{honour.season_name}»")
        elif honour.kind == "knockout":
            lines.append(f"💥 Лучший нокаутер сезона «{honour.season_name}»")
    return lines
