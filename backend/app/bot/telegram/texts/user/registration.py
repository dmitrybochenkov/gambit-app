REGISTRATION_GREETING = (
    "🤚 Добро пожаловать в покерный клуб Гамбит. Я бот, который поможет тебе "
    "стать участником нашего комьюнити.\n\n"
    "Вы уже играли в нашем клубе?"
)
REGISTRATION_NEW_PLAYER_PROMPT = "Введите имя, под которым вы будете играть."
REGISTRATION_LINK_NAME_PROMPT = "Введите имя, под которым вы играли."
REGISTRATION_LINK_NOT_FOUND = "Игрок с похожим именем не найден."
REGISTRATION_CONFIRMATION_TITLE = "Проверь введенные данные:"
DISPLAY_NAME_LABEL = "Имя игрока"
INVALID_DISPLAY_NAME = "Имя игрока должно содержать от 1 до 255 символов."
DISPLAY_NAME_ALREADY_LINKED = (
    "Это имя уже занято.\n\nПопробуй зарегистрироваться под другим именем через /start."
)
DISPLAY_NAME_ALREADY_HISTORICAL = (
    "С таким именем уже играли в нашем клубе.\n\n"
    "Если это ты — начни регистрацию через /start и выбери «Да, играл ранее».\n\n"
    "Если это не ты, зарегистрироваться под этим именем не получится. "
    "Попробуй выбрать другое имя через /start."
)
REGISTRATION_DATA_ALREADY_EXISTS = "Такое имя уже используется. Введите другое имя."
REGISTRATION_EXPIRED = "Данные регистрации устарели. Начни заново: /start"
REGISTRATION_NOT_ALLOWED = "Повторная регистрация недоступна."
REGISTRATION_PENDING = "Ваша заявка ожидает рассмотрения."
REGISTRATION_SUBMITTED = "Заявка отправлена. Ожидайте одобрения."
REGISTRATION_CANCELLED = "Отмена."
REGISTRATION_APPROVED = "Ваша заявка одобрена."
REGISTRATION_REJECTED = (
    "Ваша заявка отклонена.\n\nТы не зарегистрирован/а. Попробуй другое имя игрока через /start."
)


def new_player_confirmation(display_name: str) -> str:
    return (
        "Проверь имя:\n\n"
        f"{display_name}\n\n"
        "Под этим именем ты будешь отображаться в клубе.\n\n"
        "Всё верно?"
    )
