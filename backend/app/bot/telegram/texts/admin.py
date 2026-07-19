from collections.abc import Sequence

from app.services.dto import PlayerView, RegistrationMatchView
from app.services.pagination import Page

ACCESS_DENIED = "У тебя нет доступа в админ-панель!"
INSUFFICIENT_RIGHTS = "Недостаточно прав."
ADMIN_PANEL_WELCOME = "Добро пожаловать в админ-панель."
ADMIN_PANEL_EXITED = "Главное меню."
ADMIN_ADD_NO_CANDIDATES = "Некого назначать админом."
ADMIN_ADD_LIST_TITLE = "Кого назначаем админом?"
ADMIN_ADD_CONFIRMATION = "Сделать админом: {display_name}?"
ADMIN_ADDED = "Админ добавлен."
ADMIN_ADDED_FOR_PLAYER = "Тебе назначена роль админа."
ADMIN_ALREADY_ASSIGNED = "Игрок уже админ."
ADMIN_RESULTS_NO_TOURNAMENTS = "Сегодня нет активных турниров."
ADMIN_RESULTS_TOURNAMENT_LIST_TITLE = "Выбери турнир для внесения результатов:"
ADMIN_RESULTS_MENU_TITLE = "Внесение результатов"
ADMIN_RESULTS_PLAYERS_TITLE = "Игроки турнира"
ADMIN_RESULTS_POOL_PROMPT = "Введи пул турнира в рублях."
ADMIN_RESULTS_INVALID_POOL = "Пул должен быть положительным числом."
ADMIN_RESULTS_PLAYER_PROMPT = (
    "Введи результат игрока в формате:\n"
    "место - КО - Босс КО\n"
    "Если места нет, поставь 0 или -."
)
ADMIN_RESULTS_INVALID_PLAYER_DATA = (
    "Введи результат в формате: место - КО - Босс КО."
)
ADMIN_RESULTS_SAVED = "Результат сохранен."
ADMIN_RESULTS_CLOSED = "Турнир закрыт."
ADMIN_RESULTS_CHECK_OK = "Ошибок нет. Можно закрывать турнир."
ADMIN_RESULTS_CHECK_FAILED = "Нужно поправить:\n{errors}"
ADMIN_RESULTS_CHECK_FAILED_SHORT = "Нужно поправить ошибки."
ADMIN_RESULTS_CANCELLED = "Отмена."
ADMIN_RESULTS_NOT_FOUND = "Турнир не найден или уже закрыт."
ADMIN_TOURNAMENT_REGISTRATION_NO_TOURNAMENTS = "Нет активных турниров для записи."
ADMIN_TOURNAMENT_REGISTRATION_TOURNAMENT_LIST_TITLE = (
    "Выбери турнир для регистрации игрока:"
)
ADMIN_TOURNAMENT_REGISTRATION_NO_PLAYERS = "Нет активных игроков для регистрации."
ADMIN_TOURNAMENT_REGISTRATION_PLAYER_LIST_TITLE = "Кого регистрируем?"
ADMIN_TOURNAMENT_REGISTRATION_SEARCH_PROMPT = "Введи имя или ник игрока."
ADMIN_TOURNAMENT_REGISTRATION_SEARCH_RESULTS_TITLE = "Нашел похожих игроков:"
ADMIN_TOURNAMENT_REGISTRATION_SEARCH_EMPTY = "Игроки не найдены."
ADMIN_TOURNAMENT_REGISTRATION_SUCCESS = (
    "Игрок зарегистрирован на турнир:\n{player}\n{tournament}"
)
ADMIN_TOURNAMENT_REGISTRATION_CANCELLED = "Отмена."
ADMIN_TOURNAMENT_REGISTRATION_NOT_FOUND = "Турнир или игрок уже недоступен."
NO_PENDING_REGISTRATIONS = "Новых заявок нет."
PENDING_REGISTRATIONS_COUNT = "Заявок на проверке: {count}"
REGISTRATION_LIST_TITLE = "Заявки на регистрацию"
REGISTRATION_LIST_PAGE = "Страница {page}/{total_pages}"

REGISTRATION_REVIEW_TITLE = "Новая заявка на регистрацию"
FULL_NAME_LABEL = "Фамилия и имя"
NICKNAME_LABEL = "Никнейм"
REGISTRATION_APPROVED = "Заявка одобрена"
REGISTRATION_APPROVED_AS_NEW = "Заявка одобрена как новый игрок"
REGISTRATION_REJECTED = "Заявка отклонена"
REGISTRATION_REJECTION_MESSAGE = (
    "Ты не зарегистрирован/а. Попробуй другой никнейм или имя через /start."
)
REGISTRATION_CANCELLED = "Заявка скрыта"
PLAYER_NOT_FOUND = "Игрок не найден."
REGISTRATION_ALREADY_REVIEWED = "Заявка уже обработана."

ADMIN_CALENDAR_PROMPT = "Меню для создания сезонов и турниров в базе данных."
ADMIN_CALENDAR_CANCELLED = "Отмена."
ADMIN_CALENDAR_EMPTY_SEASONS = "Новый сезон пока не требуется."
ADMIN_CALENDAR_EMPTY_TOURNAMENTS = "Турниры на ближайшую неделю уже созданы."
ADMIN_CALENDAR_SEASON_CREATED = "Сезон создан."
SEASON_CREATED_TITLE = "Создан новый сезон:"
ADMIN_CALENDAR_TOURNAMENTS_CREATED = "Турниры созданы."
TOURNAMENTS_MANUAL_PROPOSAL_TITLE = "Будут созданы турниры на ближайшую неделю:"
TOURNAMENTS_CREATED_TITLE = "Созданы турниры:"
TOURNAMENT_ENTRY_LABEL = "Вход:"
TOURNAMENT_REBUYS_LABEL = "Ребаи:"
TOURNAMENT_ADDON_LABEL = "Аддон:"
ADMIN_CALENDAR_EDIT_SEASON = "Ок, не открываю сезон. Пришли правки отдельным сообщением."
ADMIN_CALENDAR_EDIT_MENU = "Что меняем?"
ADMIN_CALENDAR_ENTER_SEASON_NAME = "Введи новое название сезона."
ADMIN_CALENDAR_ENTER_SEASON_START = "Введи дату начала в формате 1.09.2026."
ADMIN_CALENDAR_ENTER_SEASON_END = "Введи дату окончания в формате 30.11.2026."
ADMIN_CALENDAR_INVALID_DATE = "Дата должна быть в формате 1.09.2026."
ADMIN_CALENDAR_INVALID_PERIOD = (
    "Дата начала не может быть позже даты окончания. {retry_prompt}"
)

CALENDAR_PROMPT_NOT_FOUND = "Предложение не найдено."
CALENDAR_PROMPT_ALREADY_RESOLVED = "Предложение уже обработано."
CALENDAR_PROMPT_CONFIRMED = "Подтверждено"
CALENDAR_PROMPT_CANCELLED = "Отменено"
CALENDAR_PROMPT_NEEDS_CHANGES = (
    "Нужны правки. Ручное редактирование добавим в админке."
)

SEASON_PROPOSAL_TITLE = "Нужно подготовить следующий сезон."
SEASON_MANUAL_PROPOSAL_TITLE = "Будет создан новый сезон:"
SEASON_PROPOSAL_LABEL = "Предложение"
SEASON_PERIOD_LABEL = "Период"
TOURNAMENTS_PROPOSAL_TITLE = "Нужно создать турниры на ближайшую неделю."
CONFIRM_CREATION_PROMPT = "Подтвердить создание?"
REGISTRATION_MATCHES_TITLE = "Возможные совпадения с историей:"
REGISTRATION_MATCH_TOURNAMENTS_LABEL = "турниров"
REGISTRATION_MATCH_POINTS_LABEL = "очков"
REGISTRATION_MATCH_KNOCKOUTS_LABEL = "КО"


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
    return ADMIN_RESULTS_CHECK_FAILED.format(
        errors="\n".join(f"• {error}" for error in errors)
    )


def admin_tournament_registration_success(player: str, tournament: str) -> str:
    return ADMIN_TOURNAMENT_REGISTRATION_SUCCESS.format(
        player=player,
        tournament=tournament,
    )


def registration_list(page: Page) -> str:
    lines = [REGISTRATION_LIST_TITLE, ""]
    for review in page.items:
        lines.append(f"{review.player.id} — {review.player.display_name}")

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


def registration_review(
    player: PlayerView,
    matches: Sequence[RegistrationMatchView] = (),
) -> str:
    lines = [REGISTRATION_REVIEW_TITLE, ""]
    if player.full_name:
        lines.append(f"{FULL_NAME_LABEL}: {player.full_name}")
    if player.nickname:
        lines.append(f"{NICKNAME_LABEL}: {player.nickname}")
    if matches:
        lines.extend(["", REGISTRATION_MATCHES_TITLE])
        for position, registration_match in enumerate(
            matches,
            start=1,
        ):
            lines.append(
                f"{position}. {registration_match.historical_player.display_name} "
                f"— {registration_match.reason}"
            )
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


def invalid_calendar_period(retry_prompt: str) -> str:
    return ADMIN_CALENDAR_INVALID_PERIOD.format(retry_prompt=retry_prompt)
