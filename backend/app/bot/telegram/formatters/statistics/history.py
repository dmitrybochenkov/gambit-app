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
        *_table_lines(page.items),
        "```",
    ]
    if page.total_pages > 1:
        lines.extend(["", fmt_common.page_line(page)])
    return "\n".join(lines)


def _table_lines(
    rows: list,
) -> list[str]:
    lines = [f"{'Место':<5}  {'Игрок':<20} {'КО':>3} {'БКО':>4} {'Очки':>6}"]
    for row in rows:
        place = str(row.place) if row.place is not None else "—"
        lines.append(
            f"{place:<5}  {fmt_common.code_cell(row.display_name, 20):<20} "
            f"{row.knockouts_count:>3} {row.big_knockouts_count:>4} "
            f"{fmt_common.decimal(row.total_points):>6}"
        )
    return lines
