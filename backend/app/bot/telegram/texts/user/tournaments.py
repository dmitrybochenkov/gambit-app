TOURNAMENTS_EMPTY = "Ближайших турниров пока нет."
SCHEDULE_UNAVAILABLE = "Расписание доступно зарегистрированным игрокам. Нажми /start."
TOURNAMENT_REGISTRATION_UNAVAILABLE = "Запись доступна зарегистрированным игрокам. Нажми /start."
TOURNAMENT_REGISTRATION_ACTIVE_ONLY = "Запись доступна только активным игрокам."
TOURNAMENT_REGISTRATION_EMPTY = "Ближайших турниров для записи пока нет."
TOURNAMENT_REGISTRATION_PROMPT = "Выбери турниры, на которые хочешь записаться."
TOURNAMENT_REMOVED_FROM_SELECTION = "Турнир убран из выбранных."
TOURNAMENT_ADDED_TO_SELECTION = "Турнир добавлен."
TOURNAMENT_SELECTION_EMPTY = "Сначала выбери хотя бы один турнир."
TOURNAMENT_UNAVAILABLE = "Этот турнир уже недоступен для записи."
ACTION_DONE = "Готово!"
TOURNAMENT_REGISTRATION_CANCELLED = "Отмена"
TOURNAMENT_REGISTRATION_SINGLE_HEADING = "Ты записан на турнир:"
TOURNAMENT_REGISTRATION_MULTIPLE_HEADING = "Ты записан на турниры:"
TOURNAMENT_REGISTRATION_GRATITUDE = (
    "Будем благодарны, если при изменении планов, ты отменишь запись заранее."
)

TOURNAMENT_CANCELLATION_UNAVAILABLE = (
    "Отмена записи доступна зарегистрированным игрокам. Нажми /start."
)
TOURNAMENT_CANCELLATION_ACTIVE_ONLY = "Отмена записи доступна только активным игрокам."
TOURNAMENT_CANCELLATION_EMPTY = "Ты не записан ни на один турнир."
TOURNAMENT_CANCELLATION_PROMPT = "Выбери турниры, с которых хочешь снять запись."
TOURNAMENT_CANCELLATION_UNAVAILABLE_ITEM = "Одна из записей уже недоступна для отмены."
TOURNAMENT_CANCELLATION_ALREADY_CHECKED_IN = (
    "Вы уже прошли check-in на этот турнир.\nОтменить запись после check-in нельзя."
)
TOURNAMENT_CANCELLATION_CANCELLED = "Отмена"
TOURNAMENT_CANCELLATION_SINGLE_HEADING = "Ты отменил запись на турнир:"
TOURNAMENT_CANCELLATION_MULTIPLE_HEADING = "Ты отменил запись на турниры:"

TOURNAMENT_SCHEDULE_TITLE = "Расписание турниров"
TOURNAMENT_TYPE_FALLBACK = "Неопределённый турнир"


def registration_success(tournament_labels: list[str]) -> str:
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


def cancellation_success(tournament_labels: list[str]) -> str:
    heading = (
        TOURNAMENT_CANCELLATION_SINGLE_HEADING
        if len(tournament_labels) == 1
        else TOURNAMENT_CANCELLATION_MULTIPLE_HEADING
    )
    return _tournament_list_message(heading=heading, tournament_labels=tournament_labels)


def _tournament_list_message(
    heading: str,
    tournament_labels: list[str],
    footer: str | None = None,
) -> str:
    tournament_lines = "\n".join(tournament_labels)
    lines = [heading, "", tournament_lines]
    if footer:
        lines.extend(["", footer])
    return "\n".join(lines)
