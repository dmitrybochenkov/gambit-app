# ruff: noqa: F401,F403

from app.bot.telegram.keyboards.user.history import *
from app.bot.telegram.keyboards.user.menu import *
from app.bot.telegram.keyboards.user.profile import *
from app.bot.telegram.keyboards.user.rating import *
from app.bot.telegram.keyboards.user.registration import *
from app.bot.telegram.keyboards.user.tournaments import *

__all__ = [name for name in globals() if not name.startswith("_")]
