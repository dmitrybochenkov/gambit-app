from datetime import date

from app.bot.telegram.texts import common
from app.services.dto import RegistrationReviewView
from app.services.pagination import Page

ACCESS_DENIED = "У тебя нет доступа в админ-панель!"
INSUFFICIENT_RIGHTS = "Недостаточно прав."
ADMIN_PANEL_WELCOME = "Добро пожаловать в админ-панель."
SUPERADMIN_PANEL_WELCOME = "Суперадмин."
ADMIN_PANEL_EXITED = "Главное меню."
ADMIN_ADD_NO_CANDIDATES = "Некого назначать админом."
ADMIN_ADD_LIST_TITLE = "Кого назначаем админом?"
ADMIN_ADD_CONFIRMATION = "Сделать админом: {display_name}?"
ADMIN_ADDED = "Админ добавлен."
ADMIN_ADDED_FOR_PLAYER = "Тебе назначена роль админа."
ADMIN_ALREADY_ASSIGNED = "Игрок уже админ."
ADMIN_RESULTS_NO_TOURNAMENTS = "На сегодня нет активного турнира."
ADMIN_RESULTS_PLAYERS_TITLE = "Игроки турнира"
ADMIN_RESULTS_PLAYERS_EMPTY = "Результаты еще не внесены."
ADMIN_RESULTS_MANUAL_VALUE_PROMPTS = {
    "ko": "Введи количество 🥊 числом.",
    "big": "Введи количество 👑🥊 числом.",
    "bonus": "Введи бонусные очки числом.",
    "place": "Введи место числом от 1 до 5.",
}
ADMIN_RESULTS_INVALID_MANUAL_VALUE = {
    "ko": "🥊 должно быть неотрицательным числом.",
    "big": "👑🥊 должно быть неотрицательным числом.",
    "bonus": "Бонус должен быть неотрицательным числом.",
    "place": "Место должно быть числом от 1 до 5.",
}
ADMIN_RESULTS_SAVED = "Результат сохранен."
ADMIN_RESULTS_CLOSED = "Турнир закрыт."
ADMIN_RESULTS_CHECK_FAILED = "Нужно поправить:\n{errors}"
ADMIN_RESULTS_CHECK_FAILED_SHORT = "Нужно поправить ошибки."
ADMIN_RESULTS_CANCELLED = "Отмена."
ADMIN_RESULTS_NOT_FOUND = "Турнир не найден или уже закрыт."
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

ADMIN_CALENDAR_PROMPT = "Меню для создания сезонов и турниров в базе данных."
ADMIN_CALENDAR_CANCELLED = "Отмена."
ADMIN_CALENDAR_EMPTY_SEASONS = "Нет конфигураций начисления рейтинга."
ADMIN_CALENDAR_EMPTY_TOURNAMENTS = "Не удалось создать расписание."
ADMIN_CALENDAR_TOURNAMENT_DATE_EXISTS = "На эту дату турнир уже создан."
ADMIN_CALENDAR_SEASON_CREATED = "Сезон создан."
SEASON_CREATED_TITLE = "Создан новый сезон:"
SEASON_PROPOSAL_PREVIEW_TITLE = "🏆 Новый сезон"
SEASON_NAME_LABEL = "Название"
SEASON_CURRENT_END_LABEL = "Текущий сезон завершится"
SEASON_NEW_START_LABEL = "Новый сезон начнётся"
ADMIN_CALENDAR_TOURNAMENTS_CREATED = "Расписание создано."
TOURNAMENTS_MANUAL_PROPOSAL_TITLE = "Будет создано расписание:"
TOURNAMENTS_CREATED_TITLE = "Создано расписание:"
TOURNAMENT_ENTRY_LABEL = "Вход:"
TOURNAMENT_REBUYS_LABEL = "Ребаи:"
TOURNAMENT_ADDON_LABEL = "Аддон:"
ADMIN_CALENDAR_EDIT_SEASON = "Ок, не открываю сезон. Пришли правки отдельным сообщением."
ADMIN_CALENDAR_EDIT_MENU = "Что меняем?"
ADMIN_CALENDAR_ENTER_SEASON_NEW_NAME = "Введи новое название сезона."
ADMIN_CALENDAR_ENTER_SEASON_NEW_START = "Введи новую дату начала в формате 1.09.2026."
ADMIN_CALENDAR_INVALID_DATE = "Дата должна быть в формате 1.09.2026."
ADMIN_CALENDAR_SEASON_NAME_EXISTS = "Сезон с таким названием уже существует."
ADMIN_CALENDAR_SCORING_CONFIG_NOT_FOUND = "Конфигурация начисления рейтинга не найдена."
ADMIN_CALENDAR_SEASON_START_INVALID = (
    "Дата начала нового сезона должна быть позже даты начала текущего активного сезона."
)
ADMIN_CALENDAR_SEASON_CONFLICT = "Не удалось открыть сезон. Попробуй ещё раз."
ADMIN_CALENDAR_SEASON_ALREADY_HANDLED = "Сценарий открытия сезона уже завершён."

CALENDAR_PROMPT_NOT_FOUND = "Предложение не найдено."
CALENDAR_PROMPT_STALE = "Предложение устарело. Открой Турниры заново."
CALENDAR_PROMPT_ALREADY_RESOLVED = "Предложение уже обработано."
CALENDAR_PROMPT_CONFIRMED = "Подтверждено"
CALENDAR_PROMPT_CANCELLED = "Отменено"
CALENDAR_WEEKLY_PROMPT_EMPTY = "В расписании должен остаться хотя бы один турнир."

SEASON_PROPOSAL_TITLE = "Нужно подготовить следующий сезон."
SEASON_PROPOSAL_LABEL = "Предложение"
SEASON_START_LABEL = "Дата начала"
SEASON_SCORING_CONFIG_LABEL = "Конфигурация рейтинга"
TOURNAMENTS_PROPOSAL_TITLE = "Нужно создать расписание."
CONFIRM_CREATION_PROMPT = "Подтвердить создание?"
REGISTRATION_MATCHES_TITLE = "Возможные совпадения с историей:"
REGISTRATION_MATCH_TOURNAMENTS_LABEL = "турниров"
REGISTRATION_MATCH_POINTS_LABEL = "очков"
REGISTRATION_MATCH_KNOCKOUTS_LABEL = "🥊"


def pending_registrations_count(count: int) -> str:
    return PENDING_REGISTRATIONS_COUNT.format(count=count)


def admin_candidate_list(page: Page) -> str:
    lines = [ADMIN_ADD_LIST_TITLE, ""]
    for player in page.items:
        lines.append(f"{player.id} — {player.display_name}")
    return "\n".join(lines)


def admin_add_confirmation(display_name: str) -> str:
    return ADMIN_ADD_CONFIRMATION.format(display_name=display_name)


def admin_result_check_failed(errors: list[str]) -> str:
    return ADMIN_RESULTS_CHECK_FAILED.format(errors="\n".join(f"• {error}" for error in errors))


def admin_calendar_tournament_type_prompt(tournament_date: date) -> str:
    weekday = common.WEEKDAYS[tournament_date.weekday()]
    month = common.MONTHS[tournament_date.month]
    return f"Выбери тип турнира:\n{weekday}, {tournament_date.day} {month}"


def registration_list(page: Page) -> str:
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


def registration_review(review: RegistrationReviewView) -> str:
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


def registration_approved_message(display_name: str) -> str:
    return f"{display_name}, ты успешно зарегистрирован/а!"


def reviewed_by_admin(review_text: str, result_text: str, admin_name: str) -> str:
    return f"{review_text}\n\n{result_text}: {admin_name}"


def calendar_reviewed_by_admin(
    prompt_text: str,
    result_text: str,
    admin_name: str,
) -> str:
    return f"{prompt_text}\n\n{result_text}: {admin_name}"
