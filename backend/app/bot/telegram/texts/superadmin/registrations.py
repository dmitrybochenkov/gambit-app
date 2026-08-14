NO_PENDING_REGISTRATIONS = "Заявок на регистрацию нет."
PENDING_REGISTRATIONS_COUNT = "Заявок на проверке: {count}"
REGISTRATION_LIST_TITLE = "Регистрации"
REGISTRATIONS_EMPTY = "Регистраций нет."
TOURNAMENT_REGISTRATIONS_TITLE = "🎲 Регистрации на турниры"

REGISTRATION_REVIEW_TITLE = "Новая заявка на регистрацию"
DISPLAY_NAME_LABEL = "Имя игрока"
REGISTRATION_APPROVED = "Заявка одобрена"
REGISTRATION_APPROVED_AS_NEW = "Заявка одобрена как новый игрок"
REGISTRATION_REJECTED = "Заявка отклонена"
REGISTRATION_CANCELLED = "Заявка скрыта"
PLAYER_NOT_FOUND = "Игрок не найден."
REGISTRATION_ALREADY_REVIEWED = "Заявка уже обработана."
REGISTRATION_NOT_ALLOWED = "Заявку нельзя одобрить."
REGISTRATION_CANDIDATE_SELECTED = "Игрок выбран."
REGISTRATION_MATCHES_TITLE = "Возможные совпадения с историей:"
REGISTRATION_LINK_NO_CANDIDATES = "Подходящий игрок больше не найден.\n\nЗаявку можно отклонить."
REGISTRATION_MATCH_TOURNAMENTS_LABEL = "турниров"
REGISTRATION_MATCH_POINTS_LABEL = "очков"
REGISTRATION_MATCH_KNOCKOUTS_LABEL = "🥊"


def registration_list(page: object) -> str:
    del page
    return REGISTRATION_LIST_TITLE


def tournament_registrations_overview(tournaments: list[object]) -> str:
    lines = [TOURNAMENT_REGISTRATIONS_TITLE]
    for tournament in tournaments:
        lines.extend(
            [
                "",
                _tournament_line(tournament),
                f"Зарегистрировано: {tournament.registrations_count}",
            ]
        )
    return "\n".join(lines)


def registration_review(review: object) -> str:
    lines = [REGISTRATION_REVIEW_TITLE, ""]
    request = review.request
    if request.request_type == "new_player":
        lines.extend(
            [
                "Тип: новый игрок",
                f"{DISPLAY_NAME_LABEL}: {request.requested_display_name}",
            ]
        )
    else:
        lines.extend(["Тип: привязка к истории", f"Искали: {request.requested_link_name}"])
    lines.append(f"Создана: {request.created_at}")
    if request.request_type == "link_existing_player":
        lines.extend(["", _link_candidates_text(review)])
    return "\n".join(lines)


def _link_candidates_text(review: object) -> str:
    if review.selected_candidate is not None:
        return f"Выбран игрок: {review.selected_candidate.user.display_name}"
    if not review.candidates:
        return REGISTRATION_LINK_NO_CANDIDATES
    if len(review.candidates) == 1:
        return f"Найден игрок:\n{review.candidates[0].user.display_name}"
    return "Найдено несколько похожих игроков.\nВыбери нужного игрока."


def registration_candidate_confirmation(display_name: str) -> str:
    return f"Привязать Telegram-пользователя к игроку:\n\n{display_name}?"


def reviewed_by_admin(review_text: str, result_text: str, admin_name: str) -> str:
    return f"{review_text}\n\n{result_text}: {admin_name}"


def _tournament_line(tournament: object) -> str:
    from app.bot.telegram.texts import common

    weekday = common.WEEKDAYS[tournament.date.weekday()]
    month = common.MONTHS[tournament.date.month]
    return f"{weekday}, {tournament.date.day} {month} — {tournament.tournament_type_name}"
