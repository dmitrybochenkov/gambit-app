from app.bot.telegram.texts.user import profile as profile_texts


def message(title: str, stats: object | None) -> str:
    return profile_texts.message(title, stats)


def prize_tournaments(page: object) -> str:
    return profile_texts.prize_tournaments(page)
