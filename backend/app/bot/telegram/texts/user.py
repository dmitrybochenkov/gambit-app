from decimal import Decimal

from app.db.repositories.profile_repository import PlayerProfileStats
from app.db.repositories.rating_repository import (
    KnockoutsRatingRow,
    PointsRatingRow,
)

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

RATING_UNAVAILABLE = "Рейтинг доступен зарегистрированным игрокам. Нажми /start."
RATING_MENU_PROMPT = "Какой рейтинг ты хочешь посмотреть?"
RATING_ACTIVE_ONLY = "Рейтинг доступен только активным игрокам."
RATING_EMPTY = "В рейтинге пока нет данных."

PROFILE_UNAVAILABLE = "Профиль доступен зарегистрированным игрокам. Нажми /start."
PROFILE_MENU_PROMPT = "За какой период ты хочешь посмотреть свои достижения?"
PROFILE_ACTIVE_ONLY = "Профиль доступен только активным игрокам."
PROFILE_NOT_FOUND = "Профиль не найден. Нажми /start."
PROFILE_RATING_LABEL = "Рейтинг"
PROFILE_KNOCKOUTS_LABEL = "Количество КО"
PROFILE_TOURNAMENTS_LABEL = "Количество турниров"
PROFILE_PRIZE_PLACES_LABEL = "Количество призовых мест:"

TOURNAMENTS_EMPTY = "Ближайших турниров пока нет."
TOURNAMENT_REGISTRATION_UNAVAILABLE = (
    "Запись доступна зарегистрированным игрокам. Нажми /start."
)
TOURNAMENT_REGISTRATION_ACTIVE_ONLY = "Запись доступна только активным игрокам."
TOURNAMENT_REGISTRATION_EMPTY = "Ближайших турниров для записи пока нет."
TOURNAMENT_REGISTRATION_PROMPT = (
    "Выбери даты турниров, на которые хочешь записаться, и нажми «Подтвердить»."
)
TOURNAMENT_REMOVED_FROM_SELECTION = "Турнир убран из выбранных."
TOURNAMENT_ADDED_TO_SELECTION = "Турнир добавлен."
TOURNAMENT_SELECTION_EMPTY = "Сначала выбери хотя бы один турнир."
TOURNAMENT_UNAVAILABLE = "Этот турнир уже недоступен для записи."
TOURNAMENT_FULL = "К сожалению, свободных мест уже нет."
ACTION_DONE = "Готово!"
TOURNAMENT_REGISTRATION_CANCELLED = "Запись на турнир(ы) отменена."
TOURNAMENT_REGISTRATION_SINGLE_HEADING = "Вы записались на турнир:"
TOURNAMENT_REGISTRATION_MULTIPLE_HEADING = "Вы записались на турниры:"
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
    "Выбери турниры, на которые хочешь отменить запись, и нажми «Подтвердить»."
)
TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM = (
    "Одна из записей уже недоступна для отмены."
)
TOURNAMENT_CANCELLATION_CANCELLED = "Отмена записи на турниры отменена."
TOURNAMENT_CANCELLATION_SINGLE_HEADING = "Ты отменил запись на турнир:"
TOURNAMENT_CANCELLATION_MULTIPLE_HEADING = "Ты отменил запись на турниры:"

TOURNAMENT_SCHEDULE_TITLE = "Расписание турниров"
TOURNAMENT_CAPACITY_LABEL = "до {capacity} игроков"
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
    rows: list[PointsRatingRow] | list[KnockoutsRatingRow],
) -> str:
    if not rows:
        return f"{title}\n\n{RATING_EMPTY}"

    lines = [title, ""]
    for position, row in enumerate(rows, start=1):
        if isinstance(row, PointsRatingRow):
            points = _format_decimal(row.total_points)
            lines.append(
                f"{position}. {row.display_name} — {points} очков "
                f"(турниров: {row.tournaments_count})"
            )
        else:
            lines.append(
                f"{position}. {row.display_name} — "
                f"всего КО: {row.total_knockouts_count}, "
                f"Босс КО: {row.boss_knockouts_count}"
            )
    return "\n".join(lines)


def profile_message(title: str, stats: PlayerProfileStats | None) -> str:
    if stats is None:
        return f"{title}\n\n{PROFILE_NOT_FOUND}"

    points = _format_decimal(stats.total_points)
    return "\n".join(
        [
            title,
            "",
            stats.display_name,
            f"{PROFILE_RATING_LABEL}: {points} очков",
            f"{PROFILE_KNOCKOUTS_LABEL}: {stats.total_knockouts_count}",
            f"{PROFILE_TOURNAMENTS_LABEL}: {stats.tournaments_count}",
            PROFILE_PRIZE_PLACES_LABEL,
            f"1 место: {stats.first_places_count}",
            f"2 место: {stats.second_places_count}",
            f"3 место: {stats.third_places_count}",
            f"4 место: {stats.fourth_places_count}",
            f"5 место: {stats.fifth_places_count}",
        ]
    )


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
