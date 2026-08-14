from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts.user import history as history_texts


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
    name_width = 20
    header = f"{'Место':<5}  {'Игрок':<{name_width}}"
    if show_knockouts:
        header += f" {'КО':>3}"
    if show_big_knockouts:
        header += f" {'БКО':>4}"
    if show_bonus:
        header += f" {'Бонус':>6}"
    header += f" {'Очки':>6}"
    lines = [header]
    for row in rows:
        place = str(row.place) if row.place is not None else "—"
        line = f"{place:<5}  {fmt_common.code_cell(row.display_name, name_width):<{name_width}}"
        if show_knockouts:
            line += f" {row.knockouts_count:>3}"
        if show_big_knockouts:
            line += f" {row.big_knockouts_count:>4}"
        if show_bonus:
            line += f" {row.bonus_points:>6}"
        line += f" {fmt_common.decimal(row.total_points):>6}"
        lines.append(line)
    return lines
