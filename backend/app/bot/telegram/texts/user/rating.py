from decimal import ROUND_HALF_UP, Decimal

RATING_UNAVAILABLE = (
    "Рейтинг доступен зарегистрированным игрокам. Нажми /start, чтобы зарегистрироваться!"
)
RATING_MENU_PROMPT = "Какой рейтинг ты хочешь посмотреть?"
RATING_ACTIVE_ONLY = "Рейтинг доступен только активным игрокам."
RATING_EMPTY = "В рейтинге пока нет данных."


def message(
    title: str,
    page: object,
    current_player_id: int,
) -> str:
    if not page.items:
        return f"{title}\n\n{RATING_EMPTY}"

    has_points_rows = hasattr(page.items[0], "total_points")
    lines = [title]
    if has_points_rows:
        lines.extend(["🎲 - количество турниров"])
    else:
        lines.extend(
            [
                "🎲 - количество турниров с нокаутами",
            ]
        )
    lines.append("")
    start_position = page.page * page.page_size + 1
    for position, row in enumerate(page.items, start=start_position):
        position_label = _position_label(position, row.player_id == current_player_id)
        display_name = _display_name(row, current_player_id)
        if hasattr(row, "total_points"):
            points = _format_points(row.total_points)
            lines.append(f"{position_label} {display_name} — {points} | 🎲 {row.tournaments_count}")
        else:
            lines.append(
                f"{position_label} {display_name} — {row.total_knockouts_count} | "
                f"🎲 {row.knockout_tournaments_count}"
            )
    return "\n".join(lines)


def _position_label(position: int, is_current_player: bool = False) -> str:
    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }
    label = medals.get(position, f"{position}.")
    if is_current_player:
        return f"👉 {position}."
    return label


def _display_name(row: object, current_player_id: int) -> str:
    if row.player_id == current_player_id:
        display_name = _escape_markdown(row.display_name)
        honours = _honours(row)
        if honours:
            return f"*{display_name}* {honours}"
        return f"*{display_name}*"
    return _escape_markdown(_display_name_with_honours(row))


def _display_name_with_honours(row: object) -> str:
    honours = _honours(row)
    return f"{row.display_name} {honours}" if honours else row.display_name


def _honours(row: object) -> str:
    honours = []
    if row.season_champion_titles_count > 0:
        honours.extend("💍" for _ in range(row.season_champion_titles_count))
    knockout_titles = getattr(row, "season_knockout_leader_titles_count", 0)
    if knockout_titles > 0:
        honours.extend("🥊" for _ in range(knockout_titles))
    return "".join(honours)


def _format_points(value: Decimal) -> str:
    return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _escape_markdown(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )
