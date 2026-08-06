# ruff: noqa: F401,F403

from app.bot.telegram.keyboards.superadmin.administrators import *
from app.bot.telegram.keyboards.superadmin.panel import *
from app.bot.telegram.keyboards.superadmin.registrations import *
from app.bot.telegram.keyboards.superadmin.seasons import *
from app.bot.telegram.keyboards.superadmin.tournament_close import *

__all__ = [name for name in globals() if not name.startswith("_")]
