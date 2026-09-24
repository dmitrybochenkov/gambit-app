ACHIEVEMENT_EMOJI = {
    "rating_winner": "💍",
    "ko_rating_winner": "💥",
    "grand_season": "🏆",
    "grand_month": "🏅",
    "grand_knockout": "🥊",
}


def achievement_emoji(kind: str) -> str:
    return ACHIEVEMENT_EMOJI[kind]
