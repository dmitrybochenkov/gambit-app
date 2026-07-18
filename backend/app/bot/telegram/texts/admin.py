from collections.abc import Sequence

from app.services.dto import PlayerView, RegistrationMatchView
from app.services.pagination import Page

ACCESS_DENIED = "У тебя нет доступа в админ-панель!"
ADMIN_PANEL_WELCOME = "Добро пожаловать в админ-панель."
ADMIN_PANEL_EXITED = "Главное меню."
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
ADMIN_CALENDAR_EMPTY_TOURNAMENTS = "Турниры на ближайшие две недели уже созданы."
ADMIN_CALENDAR_SEASON_CREATED = "Сезон создан."
ADMIN_CALENDAR_TOURNAMENTS_CREATED = "Турниры созданы."
ADMIN_CALENDAR_EDIT_SEASON = "Ок, не открываю сезон. Пришли правки отдельным сообщением."

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
TOURNAMENTS_PROPOSAL_TITLE = "Нужно создать турниры на две недели вперед."
CONFIRM_CREATION_PROMPT = "Подтвердить создание?"
REGISTRATION_MATCHES_TITLE = "Возможные совпадения с историей:"
REGISTRATION_MATCH_TOURNAMENTS_LABEL = "турниров"
REGISTRATION_MATCH_POINTS_LABEL = "очков"
REGISTRATION_MATCH_KNOCKOUTS_LABEL = "КО"


def pending_registrations_count(count: int) -> str:
    return PENDING_REGISTRATIONS_COUNT.format(count=count)


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
