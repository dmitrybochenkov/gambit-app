from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts.user import history as history_texts

MAX_TABLE_WIDTH = 35
MAX_PLAYER_NAME_WIDTH = 21
_PLACE_WIDTH = 1
_KNOCKOUT_WIDTH = 2
_BIG_KNOCKOUT_WIDTH = 3
_BONUS_WIDTH = 5
_POINTS_WIDTH = 4


def years(page: object) -> str:
    lines = [history_texts.HISTORY_YEARS_PROMPT]
    if not page.items:
        lines.extend(["", history_texts.HISTORY_EMPTY])
    elif page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def months(
    year: int,
    page: object,
) -> str:
    lines = [history_texts.HISTORY_MONTHS_PROMPT, f"{year} год"]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def tournaments(
    year: int,
    month: int,
    page: object,
) -> str:
    lines = [
        history_texts.HISTORY_TOURNAMENTS_PROMPT,
        f"{fmt_common.month_name(month)} {year}",
    ]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def tournament_result(
    result: object,
    page: object,
) -> str:
    tournament = result.tournament
    lines = [
        "⏳ История",
        "",
        fmt_common.date_long(tournament.date),
        fmt_common.markdown_escape(tournament.display_name),
        "",
        "```",
        *_table_lines(
            page.items,
            show_knockouts=result.has_knockouts,
            show_big_knockouts=result.has_big_knockouts,
            show_bonus=result.has_bonus_points,
        ),
        "```",
    ]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def _table_lines(
    rows: list,
    *,
    show_knockouts: bool,
    show_big_knockouts: bool,
    show_bonus: bool,
) -> list[str]:
    columns = _history_table_columns(
        show_knockouts=show_knockouts,
        show_big_knockouts=show_big_knockouts,
        show_bonus=show_bonus,
    )
    name_width = _history_table_name_width(rows, columns)
    header = " ".join(["№", f"{'Игрок':<{name_width}}", *[column[0] for column in columns]])
    lines = [header.rstrip()]
    for row in rows:
        place = str(row.place) if row.place is not None else "—"
        cells = [
            f"{place:>{_PLACE_WIDTH}}",
            f"{fmt_common.code_cell(row.display_name, name_width):<{name_width}}",
        ]
        if show_knockouts:
            cells.append(f"{row.knockouts_count:>{_KNOCKOUT_WIDTH}}")
        if show_big_knockouts:
            cells.append(f"{row.big_knockouts_count:>{_BIG_KNOCKOUT_WIDTH}}")
        if show_bonus:
            cells.append(f"{row.bonus_points:>{_BONUS_WIDTH}}")
        cells.append(f"{fmt_common.points(row.total_points):>{_POINTS_WIDTH}}")
        lines.append(" ".join(cells).rstrip())
    return lines


def _history_table_columns(
    *,
    show_knockouts: bool,
    show_big_knockouts: bool,
    show_bonus: bool,
) -> list[tuple[str, int]]:
    columns: list[tuple[str, int]] = []
    if show_knockouts:
        columns.append((f"{'КО':>{_KNOCKOUT_WIDTH}}", _KNOCKOUT_WIDTH))
    if show_big_knockouts:
        columns.append((f"{'БКО':>{_BIG_KNOCKOUT_WIDTH}}", _BIG_KNOCKOUT_WIDTH))
    if show_bonus:
        columns.append((f"{'Бонус':>{_BONUS_WIDTH}}", _BONUS_WIDTH))
    columns.append((f"{'Очки':>{_POINTS_WIDTH}}", _POINTS_WIDTH))
    return columns


def _history_table_name_width(rows: list[object], columns: list[tuple[str, int]]) -> int:
    separators_width = 1 + len(columns)
    technical_width = _PLACE_WIDTH + separators_width + sum(width for _label, width in columns)
    available_width = MAX_TABLE_WIDTH - technical_width
    longest_name = max([len("Игрок"), *[len(str(row.display_name)) for row in rows]])
    return min(longest_name, MAX_PLAYER_NAME_WIDTH, available_width)
