from datetime import date

from app.bot.telegram.texts import common as common_texts


def date_long(value: date) -> str:
    return f"{value.day} {common_texts.MONTHS[value.month]} {value.year}"


def date_numeric(value: date) -> str:
    return f"{value.day}.{value.month:02d}.{value.year}"


def number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def decimal(value: object) -> str:
    text = f"{value}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def page_line(page: object) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


def markdown_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
    )


def month_name(month: int) -> str:
    return common_texts.MONTHS[month].capitalize()


def code_cell(value: str, width: int) -> str:
    compact = " ".join(value.replace("`", "'").split())
    if len(compact) <= width:
        return compact
    return f"{compact[: width - 1]}…"
