from datetime import date
from typing import Any

from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.texts import common as common_texts

WEEKDAY_GENITIVE = {
    0: "понедельника",
    1: "вторника",
    2: "среды",
    3: "четверга",
    4: "пятницы",
    5: "субботы",
    6: "воскресенья",
}


def prize_stack_bonus_notification(reward: Any) -> str:
    return "\n".join(
        [
            "🎁 Ты получил бонус!",
            "",
            (
                f"За {reward.source_place} место в турнире "
                f"{reward.source_tournament_name} "
                f"{fmt_common.date_long(reward.source_tournament_date)} тебе начислено"
            ),
            f"+{fmt_common.number(reward.chips_amount)} фишек к первому стеку.",
            "",
            (
                "Бонус можно использовать на любом турнире до "
                f"{fmt_common.date_long(reward.valid_through)} включительно."
            ),
            "",
            "Если не хочешь использовать его сразу — можешь сохранить на другой день.",
        ]
    )


def prize_stack_bonus_expiration_reminder(group: Any, business_date: date) -> str:
    if len(group.rewards) == 1:
        reward = group.rewards[0]
        return "\n".join(
            [
                "🎁 Не забудь про бонус!",
                "",
                (
                    "У тебя есть бонус "
                    f"+{fmt_common.number(reward.chips_amount)} фишек к первому стеку."
                ),
                "",
                _days_left_line((reward.valid_through - business_date).days),
                (
                    "Бонус можно использовать до "
                    f"{_weekday_date(reward.valid_through)} включительно."
                ),
                "",
                "Если не хочешь использовать его сразу — можешь сохранить на другой день.",
            ]
        )

    lines = [
        "🎁 Не забудь про бонусы!",
        "",
        "У тебя есть активные бонусы:",
        "",
    ]
    lines.extend(
        f"• +{fmt_common.number(reward.chips_amount)} фишек — до "
        f"{_weekday_date(reward.valid_through)} включительно"
        for reward in group.rewards
    )
    lines.extend(
        [
            "",
            "Не забудь использовать их до окончания срока.",
            "За один игровой день можно использовать только один бонус.",
        ]
    )
    return "\n".join(lines)


def prize_stack_bonus_correction_notification(reward: Any) -> str:
    if reward.old_chips_amount is None and reward.new_chips_amount is not None:
        return "\n".join(
            [
                "🎁 Ты получил бонус!",
                "",
                (
                    "После исправления результатов турнира "
                    f"{reward.source_tournament_name} от "
                    f"{fmt_common.date_long(reward.source_tournament_date)}"
                ),
                (
                    "тебе начислено "
                    f"+{fmt_common.number(reward.new_chips_amount)} фишек к первому стеку."
                ),
                "",
                (
                    "Бонус можно использовать до "
                    f"{fmt_common.date_long(reward.valid_through)} включительно."
                ),
            ]
        )
    if reward.old_chips_amount is not None and reward.new_chips_amount is None:
        return "\n".join(
            [
                "🎁 Бонус скорректирован",
                "",
                (
                    "После исправления результатов турнира "
                    f"{reward.source_tournament_name} от "
                    f"{fmt_common.date_long(reward.source_tournament_date)}"
                ),
                (f"твой бонус +{fmt_common.number(reward.old_chips_amount)} фишек аннулирован."),
            ]
        )
    return "\n".join(
        [
            "🎁 Бонус скорректирован",
            "",
            (
                "После исправления результатов турнира "
                f"{reward.source_tournament_name} от "
                f"{fmt_common.date_long(reward.source_tournament_date)}"
            ),
            "твой бонус изменён:",
            "",
            (
                f"+{fmt_common.number(reward.old_chips_amount)} → "
                f"+{fmt_common.number(reward.new_chips_amount)} фишек."
            ),
            "",
            (
                "Бонус можно использовать до "
                f"{fmt_common.date_long(reward.valid_through)} включительно."
            ),
        ]
    )


def _days_left_line(days_left: int) -> str:
    if days_left <= 0:
        return "Сегодня последний день действия бонуса."
    if days_left % 10 == 1 and days_left % 100 != 11:
        return f"До окончания действия остался {days_left} день."
    if days_left % 10 in {2, 3, 4} and days_left % 100 not in {12, 13, 14}:
        return f"До окончания действия осталось {days_left} дня."
    return f"До окончания действия осталось {days_left} дней."


def _weekday_date(value: date) -> str:
    return f"{WEEKDAY_GENITIVE[value.weekday()]}, {value.day} {common_texts.MONTHS[value.month]}"
