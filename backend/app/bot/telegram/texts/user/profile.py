from app.bot.telegram.formatters import common as fmt_common

PROFILE_UNAVAILABLE = "Профиль доступен зарегистрированным игрокам. Нажми /start."
PROFILE_MENU_PROMPT = "За какой период ты хочешь посмотреть свои достижения?"
PROFILE_ACTIVE_ONLY = "Профиль доступен только активным игрокам."
PROFILE_NOT_FOUND = "Профиль не найден. Нажми /start."
PROFILE_PRIZE_PLACES_LABEL = "Количество призовых мест:"
PROFILE_REWARD_TEASER = "У тебя есть активные бонусы! Не забудь их использовать."
PROFILE_PRIZE_TOURNAMENTS_TITLE = "История призовых мест"
PROFILE_PRIZE_TOURNAMENTS_EMPTY = "Призовых турниров пока нет."


def message(title: str, stats: object | None, *, show_reward_teaser: bool = True) -> str:
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
        (
            f"⭐ {points}{_rating_position(stats)} | 🎯 {_prize_percent(stats)} | "
            f"🥊 {stats.total_knockouts_count} | 🎲 {stats.tournaments_count}"
        ),
    ]
    if show_reward_teaser and stats.active_rewards:
        lines.extend(["", PROFILE_REWARD_TEASER])
    return "\n".join(lines)


def achievements_block(title: str, stats: object, season_id: int) -> str:
    honours = [honour for honour in stats.honours if honour.season_id == season_id]
    season_name = honours[0].season_name
    lines = [message(title, stats, show_reward_teaser=False), "", f"Награды — {season_name}"]
    for honour in honours:
        label = honour.title
        if honour.kind in {"grand_month", "grand_knockout"}:
            label = f"{label} ({honour.awarded_at:%d.%m.%Y})"
        lines.append(f"{honour.emoji} {label}")
    return "\n".join(lines)


def rewards_block(title: str, stats: object) -> str:
    return "\n".join(
        [
            message(title, stats, show_reward_teaser=False),
            "",
            "🎁 Активные бонусы",
            "",
            *_reward_lines(stats),
        ]
    )


def placements_block(title: str, stats: object) -> str:
    return "\n".join(
        [
            message(title, stats, show_reward_teaser=False),
            "",
            PROFILE_PRIZE_PLACES_LABEL,
            *_prize_place_lines(stats),
        ]
    )


def combinations_block(title: str, stats: object) -> str:
    combinations = (
        ("👑 Роял-флеш", stats.royal_flush_count),
        ("⚡ Стрит-флеш", stats.straight_flush_count),
        ("4️⃣ Каре", stats.four_of_a_kind_count),
    )
    return "\n".join(
        [
            message(title, stats, show_reward_teaser=False),
            "",
            "🃏 Покерные комбинации",
            "",
            *(f"{label} — {count}" for label, count in combinations if count > 0),
        ]
    )


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


def _reward_lines(stats: object) -> list[str]:
    lines = []
    for reward in stats.active_rewards:
        lines.extend(
            [
                f"🎁 +{fmt_common.number(reward.chips_amount)} фишек к первому стеку",
                (
                    f"За {reward.source_place} место — {reward.source_tournament_name}, "
                    f"{fmt_common.date_long(reward.source_tournament_date)}"
                ),
                f"Действует до {fmt_common.date_long(reward.valid_through)}",
                "",
            ]
        )
    if lines:
        lines.pop()
    return lines


def prize_tournaments(page: object) -> str:
    lines = [PROFILE_PRIZE_TOURNAMENTS_TITLE]
    if not page.items:
        lines.extend(["", PROFILE_PRIZE_TOURNAMENTS_EMPTY])
    else:
        lines.extend(["", *[_prize_tournament_line(item) for item in page.items]])
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def _prize_tournament_line(tournament: object) -> str:
    return (
        f"{_place_label(tournament.place)} {tournament.date:%d.%m.%y} — {tournament.display_name}"
    )


def _place_label(place: int) -> str:
    return {
        1: "🥇",
        2: "🥈",
        3: "🥉",
        4: "4️⃣",
        5: "5️⃣",
    }[place]
