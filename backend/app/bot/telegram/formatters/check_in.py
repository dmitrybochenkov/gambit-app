from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import tournaments as tournament_fmt


def tournament_list(page: object) -> str:
    lines = ["Выбери турнир:", ""]
    for tournament in page.items:
        lines.append(f"{tournament.id} — {tournament_fmt.label(tournament)}")
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def summary(view: object) -> str:
    lines = [
        "✅ Чек-ин на турнир",
        tournament_fmt.label(view.tournament),
        "",
        f"Зарегистрировано: {view.registered_count}",
        f"Из них пришло: {view.registered_checked_in_count}",
        "",
        f"Пришло без регистрации: {view.walk_in_count}",
        "",
        f"Всего в турнире: {view.checked_in_count}",
        "",
    ]
    if getattr(view, "is_superadmin_late_override", False):
        lines.extend(
            [
                "Обычное окно чекина закрыто.",
                "Для суперадмина доступен ручной чекин до закрытия турнира.",
                "",
            ]
        )
    lines.append("Выбери тип игрока:")
    return "\n".join(lines)


def checked_in_players(view: object) -> str:
    lines = ["✅ Уже отметились", ""]
    if not view.players:
        lines.append("Пока никто не прошёл check-in.")
    else:
        lines.extend(
            f"{index}. {player.display_name}" for index, player in enumerate(view.players, start=1)
        )
    lines.extend(["", f"Всего: {view.total_count}"])
    return "\n".join(lines)


def registered_confirmation(tournament: object, user: object) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в сегодняшний турнир?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def existing_confirmation(tournament: object, user: object) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в турнир без предварительной регистрации?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def new_confirmation(tournament: object, display_name: str) -> str:
    return "\n".join(
        [
            f"Создать нового игрока «{display_name}» и добавить в турнир?",
            "",
            tournament_fmt.type_name(tournament),
            fmt_common.date_long(tournament.date),
        ]
    )


def unknown_gender(user: object) -> str:
    return "\n".join(
        [
            "У игрока не указан пол.",
            "",
            user.display_name,
            "",
            "Выбери:",
        ]
    )


def player_notification(tournament: object) -> str:
    return "\n".join(
        [
            f"✅ Вы прошли check-in на турнир «{tournament_fmt.type_name(tournament)}».",
            fmt_common.date_long(tournament.date),
        ]
    )


def admin_success(tournament: object, user: object) -> str:
    return "\n".join(
        [
            "✅ Игрок добавлен в турнир",
            "",
            user.display_name,
            tournament_fmt.label(tournament),
        ]
    )


def reward_selection(result: object) -> str:
    lines = [
        f"Добавить {result.user.display_name} в турнир?",
        "",
    ]
    if len(result.active_rewards) == 1:
        reward = result.active_rewards[0]
        lines.extend(
            [
                "🎁 У игрока есть бонус:",
                f"+{fmt_common.number(reward.chips_amount)} фишек к первому стеку",
                f"Действует до {fmt_common.date_long(reward.valid_through)}",
                "",
                "Использовать бонус при check-in?",
            ]
        )
    else:
        lines.extend(["🎁 Активные бонусы:", ""])
        lines.extend(
            f"+{fmt_common.number(reward.chips_amount)} — до "
            f"{fmt_common.date_long(reward.valid_through)}"
            for reward in result.active_rewards
        )
    return "\n".join(lines)


def reward_confirmation(user: object, reward: object) -> str:
    return "\n".join(
        [
            f"Добавить {user.display_name} в турнир и выдать "
            f"+{fmt_common.number(reward.chips_amount)} фишек к первому стеку?",
            "",
            "После подтверждения игрок пройдёт check-in, а бонус будет использован.",
        ]
    )
