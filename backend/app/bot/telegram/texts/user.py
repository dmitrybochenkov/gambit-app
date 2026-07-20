from decimal import Decimal

from app.services.dto import (
    KnockoutsRatingView,
    PlayerProfileView,
    PointsRatingView,
)
from app.services.pagination import Page

REGISTRATION_GREETING = (
    "🤚 Добро пожаловать в покерный клуб Гамбит. Я бот, который поможет тебе "
    "стать участником нашего комьюнити.\n\n"
    "Чтобы я знал, как к тебе обращаться, и мог отслеживать твои достижения, "
    "введи свои фамилию и имя и/или никнейм.\n\n"
    "❌ Запрещено использовать ненормативную лексику!\n\n"
    "✅ Чтобы корректно учесть твои достижения, вводи никнейм, под которым "
    "ты играл в клубе ранее."
)
REGISTRATION_MODE_PROMPT = "Выбери вариант регистрации:"
REGISTRATION_CONFIRMATION_TITLE = "Проверь введенные данные:"
FULL_NAME_LABEL = "Фамилия и имя"
NICKNAME_LABEL = "Никнейм"
ENTER_NICKNAME = "Введи никнейм."
ENTER_FULL_NAME = "Введи фамилию и имя."
ENTER_NICKNAME_AFTER_FULL_NAME = "Теперь введи никнейм."
INVALID_FULL_NAME = "Введи фамилию и имя через пробел."
FULL_NAME_ALREADY_EXISTS = "Такие имя и фамилия уже существуют. Попробуй другие."
INVALID_NICKNAME = "Никнейм должен содержать от 2 до 100 символов."
NICKNAME_ALREADY_EXISTS = "Такой никнейм уже существует. Попробуй другой."
REGISTRATION_DATA_ALREADY_EXISTS = "Эти данные уже заняты. Введи другое значение."
REGISTRATION_EXPIRED = "Данные регистрации устарели. Начни заново: /start"
REGISTRATION_NOT_ALLOWED = "Повторная регистрация недоступна."
REGISTRATION_PENDING = "Твоя заявка на регистрацию находится на проверке."
BOT_ACCESS_BLOCKED = "Доступ к боту заблокирован."

SCHEDULE_UNAVAILABLE = "Расписание доступно зарегистрированным игрокам. Нажми /start."
ADDRESS_UNAVAILABLE = "Адрес доступен зарегистрированным игрокам. Нажми /start."
CLUB_ADDRESS = (
    "📍 Орехово-Зуево, ул. Ленина, 105\n"
    "🏆 Играем исключительно на рейтинг и спортивный интерес."
)

RATING_UNAVAILABLE = (
    "Рейтинг доступен зарегистрированным игрокам. "
    "Нажми /start, чтобы зарегистрироваться!"
)
RATING_MENU_PROMPT = "Какой рейтинг ты хочешь посмотреть?"
RATING_ACTIVE_ONLY = "Рейтинг доступен только активным игрокам."
RATING_EMPTY = "В рейтинге пока нет данных."

PROFILE_UNAVAILABLE = "Профиль доступен зарегистрированным игрокам. Нажми /start."
PROFILE_MENU_PROMPT = "За какой период ты хочешь посмотреть свои достижения?"
PROFILE_ACTIVE_ONLY = "Профиль доступен только активным игрокам."
PROFILE_NOT_FOUND = "Профиль не найден. Нажми /start."
PROFILE_PRIZE_PLACES_LABEL = "Количество призовых мест:"

TOURNAMENTS_EMPTY = "Ближайших турниров пока нет."
TOURNAMENT_REGISTRATION_UNAVAILABLE = (
    "Запись доступна зарегистрированным игрокам. Нажми /start."
)
TOURNAMENT_REGISTRATION_ACTIVE_ONLY = "Запись доступна только активным игрокам."
TOURNAMENT_REGISTRATION_EMPTY = "Ближайших турниров для записи пока нет."
TOURNAMENT_REGISTRATION_PROMPT = (
    "Выбери турниры, на которые хочешь записаться."
)
TOURNAMENT_REMOVED_FROM_SELECTION = "Турнир убран из выбранных."
TOURNAMENT_ADDED_TO_SELECTION = "Турнир добавлен."
TOURNAMENT_SELECTION_EMPTY = "Сначала выбери хотя бы один турнир."
TOURNAMENT_UNAVAILABLE = "Этот турнир уже недоступен для записи."
ACTION_DONE = "Готово!"
TOURNAMENT_REGISTRATION_CANCELLED = "Отмена"
TOURNAMENT_REGISTRATION_SINGLE_HEADING = "Ты записан на турнир:"
TOURNAMENT_REGISTRATION_MULTIPLE_HEADING = "Ты записан на турниры:"
TOURNAMENT_REGISTRATION_GRATITUDE = (
    "Будем благодарны, если при изменении планов, вы отмените запись заранее."
)

TOURNAMENT_CANCELLATION_UNAVAILABLE = (
    "Отмена записи доступна зарегистрированным игрокам. Нажми /start."
)
TOURNAMENT_CANCELLATION_ACTIVE_ONLY = (
    "Отмена записи доступна только активным игрокам."
)
TOURNAMENT_CANCELLATION_EMPTY = "Ты не записан ни на один турнир."
TOURNAMENT_CANCELLATION_PROMPT = (
    "Выбери турниры, с которых хочешь снять запись."
)
TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM = (
    "Одна из записей уже недоступна для отмены."
)
TOURNAMENT_CANCELLATION_CANCELLED = "Отмена"
TOURNAMENT_CANCELLATION_SINGLE_HEADING = "Ты отменил запись на турнир:"
TOURNAMENT_CANCELLATION_MULTIPLE_HEADING = "Ты отменил запись на турниры:"

TOURNAMENT_SCHEDULE_TITLE = "Расписание турниров"
TOURNAMENT_TYPE_FALLBACK = "Турнир {type_id}"


def welcome_back(display_name: str) -> str:
    return f"{display_name}, добро пожаловать!"


def registration_confirmation(full_name: str | None, nickname: str | None) -> str:
    lines = [REGISTRATION_CONFIRMATION_TITLE]
    if full_name:
        lines.append(f"{FULL_NAME_LABEL}: {full_name}")
    if nickname:
        lines.append(f"{NICKNAME_LABEL}: {nickname}")
    return "\n".join(lines)


def registration_submitted(display_name: str) -> str:
    return f"{display_name}, заявка отправлена на проверку администратору."


def tournament_registration_success(tournament_labels: list[str]) -> str:
    heading = (
        TOURNAMENT_REGISTRATION_SINGLE_HEADING
        if len(tournament_labels) == 1
        else TOURNAMENT_REGISTRATION_MULTIPLE_HEADING
    )
    return _tournament_list_message(
        heading=heading,
        tournament_labels=tournament_labels,
        footer=TOURNAMENT_REGISTRATION_GRATITUDE,
    )


def tournament_cancellation_success(tournament_labels: list[str]) -> str:
    heading = (
        TOURNAMENT_CANCELLATION_SINGLE_HEADING
        if len(tournament_labels) == 1
        else TOURNAMENT_CANCELLATION_MULTIPLE_HEADING
    )
    return _tournament_list_message(heading=heading, tournament_labels=tournament_labels)


def rating_message(
    title: str,
    page: Page,
    current_player_id: int,
) -> str:
    if not page.items:
        return f"{title}\n\n{RATING_EMPTY}"

    has_points_rows = isinstance(page.items[0], PointsRatingView)
    lines = [title]
    if has_points_rows:
        lines.extend(["⭐ - количество очков", "🎲 - количество турниров"])
    else:
        lines.extend(
            [
                "🥊 - количество нокаутов",
                "⭐🥊 - количество очков за нокауты",
                "🎲 - количество турниров",
            ]
        )
    lines.append("")
    start_position = page.page * page.page_size + 1
    for position, row in enumerate(page.items, start=start_position):
        position_label = _rating_position_label(position)
        display_name = _rating_display_name(row, current_player_id)
        if isinstance(row, PointsRatingView):
            points = _format_decimal(row.total_points)
            lines.append(
                f"{position_label} {display_name} — "
                f"⭐{points} | 🎲 {row.tournaments_count}"
            )
        else:
            knockout_points = _format_decimal(row.knockout_points)
            lines.append(
                f"{position_label} {display_name} — "
                f"🥊 {row.total_knockouts_count} | "
                f"⭐🥊 {knockout_points} | "
                f"🎲 {row.tournaments_count}"
            )
    return "\n".join(lines)


def _rating_position_label(position: int) -> str:
    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }
    return medals.get(position, f"{position}.")


def _rating_display_name(
    row: PointsRatingView | KnockoutsRatingView,
    current_player_id: int,
) -> str:
    display_name = _escape_markdown(row.display_name)
    if row.player_id == current_player_id:
        return f"*{display_name}*"
    return display_name


def _escape_markdown(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def profile_message(title: str, stats: PlayerProfileView | None) -> str:
    if stats is None:
        return f"{title}\n\n{PROFILE_NOT_FOUND}"

    points = _format_decimal(stats.total_points)
    lines = [
        title,
        "⭐ - количество очков",
        "🥊 - количество нокаутов",
        "⭐🥊 - количество очков за нокауты",
        "🎲 - количество турниров",
        "",
        stats.display_name,
        f"⭐ {points} | 🥊 {stats.total_knockouts_count} | "
        f"⭐🥊 {_format_decimal(stats.knockout_points)} | 🎲 {stats.tournaments_count}",
    ]
    prize_place_lines = _profile_prize_place_lines(stats)
    if prize_place_lines:
        lines.extend(["", PROFILE_PRIZE_PLACES_LABEL, *prize_place_lines])
    return "\n".join(lines)


def _profile_prize_place_lines(stats: PlayerProfileView) -> list[str]:
    prize_places = [
        ("🥇", stats.first_places_count),
        ("🥈", stats.second_places_count),
        ("🥉", stats.third_places_count),
        ("4️⃣", stats.fourth_places_count),
        ("5️⃣", stats.fifth_places_count),
    ]
    return [f"{label} x{count}" for label, count in prize_places if count > 0]


def _tournament_list_message(
    heading: str,
    tournament_labels: list[str],
    footer: str | None = None,
) -> str:
    tournament_lines = "\n".join(f"• {label}" for label in tournament_labels)
    lines = [heading, "", tournament_lines]
    if footer:
        lines.extend(["", footer])
    return "\n".join(lines)


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
