from app.bot.telegram.texts.user import rating as rating_texts


def message(
    title: str,
    page: object,
    current_player_id: int,
) -> str:
    return rating_texts.message(title, page, current_player_id)
