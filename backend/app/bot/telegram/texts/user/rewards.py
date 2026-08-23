from app.bot.telegram.formatters import common as fmt_common


def prize_stack_bonus_notification(reward: object) -> str:
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
