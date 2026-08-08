NO_PENDING_REGISTRATIONS = "Новых заявок нет."
PENDING_REGISTRATIONS_COUNT = "Заявок на проверке: {count}"
REGISTRATION_LIST_TITLE = "Заявки на регистрацию"
REGISTRATION_LIST_PAGE = "Страница {page}/{total_pages}"

REGISTRATION_REVIEW_TITLE = "Новая заявка на регистрацию"
DISPLAY_NAME_LABEL = "Имя игрока"
REGISTRATION_APPROVED = "Заявка одобрена"
REGISTRATION_APPROVED_AS_NEW = "Заявка одобрена как новый игрок"
REGISTRATION_REJECTED = "Заявка отклонена"
REGISTRATION_REJECTION_MESSAGE = "Ты не зарегистрирован/а. Попробуй другое имя игрока через /start."
REGISTRATION_CANCELLED = "Заявка скрыта"
PLAYER_NOT_FOUND = "Игрок не найден."
REGISTRATION_ALREADY_REVIEWED = "Заявка уже обработана."
REGISTRATION_NOT_ALLOWED = "Заявку нельзя одобрить."
REGISTRATION_MATCHES_TITLE = "Возможные совпадения с историей:"
REGISTRATION_MATCH_TOURNAMENTS_LABEL = "турниров"
REGISTRATION_MATCH_POINTS_LABEL = "очков"
REGISTRATION_MATCH_KNOCKOUTS_LABEL = "🥊"


def registration_list(page: object) -> str:
    lines = [REGISTRATION_LIST_TITLE, ""]
    for review in page.items:
        name = review.request.requested_display_name or review.request.requested_link_name or "—"
        lines.append(f"{review.request.id} — {name}")

    if page.total_pages > 1:
        lines.extend(
            [
                "",
                REGISTRATION_LIST_PAGE.format(
                    page=page.page + 1,
                    total_pages=page.total_pages,
                ),
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
        if request.candidate_user_id is not None:
            lines.append(f"Выбран игрок id {request.candidate_user_id}")
    lines.append(f"Создана: {request.created_at}")
    if review.candidates:
        lines.extend(["", REGISTRATION_MATCHES_TITLE])
        for position, candidate in enumerate(
            review.candidates,
            start=1,
        ):
            lines.append(f"{position}. {candidate.user.display_name} — {candidate.reason}")
    return "\n".join(lines)


def reviewed_by_admin(review_text: str, result_text: str, admin_name: str) -> str:
    return f"{review_text}\n\n{result_text}: {admin_name}"
