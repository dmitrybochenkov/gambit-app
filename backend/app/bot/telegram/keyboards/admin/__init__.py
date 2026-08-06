# ruff: noqa: F401,F403

from app.bot.telegram.keyboards.admin.calendar import *
from app.bot.telegram.keyboards.admin.check_in import *
from app.bot.telegram.keyboards.admin.panel import *
from app.bot.telegram.keyboards.admin.results import *
from app.bot.telegram.keyboards.admin.schedule import *

__all__ = [name for name in globals() if not name.startswith("_")]
