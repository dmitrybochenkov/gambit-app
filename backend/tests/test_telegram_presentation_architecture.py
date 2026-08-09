from pathlib import Path

from app.bot.telegram.handlers import admin, superadmin, user
from app.bot.telegram.keyboards import admin as admin_keyboards
from app.bot.telegram.keyboards import superadmin as superadmin_keyboards
from app.bot.telegram.keyboards import user as user_keyboards

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_ROOT = PROJECT_ROOT / "app" / "bot" / "telegram"


def test_role_handler_inits_only_assemble_routers() -> None:
    assert admin.__all__ == ["router"]
    assert user.__all__ == ["router"]
    assert superadmin.__all__ == ["router"]


def test_role_keyboard_inits_export_modules_only() -> None:
    assert admin_keyboards.__all__ == ["calendar", "check_in", "panel", "results", "schedule"]
    assert user_keyboards.__all__ == [
        "history",
        "menu",
        "profile",
        "rating",
        "registration",
        "tournaments",
    ]
    assert superadmin_keyboards.__all__ == [
        "administrators",
        "hall_of_fame",
        "panel",
        "registrations",
        "seasons",
        "tournament_close",
    ]


def test_handler_dependency_aggregators_are_removed() -> None:
    assert not (TELEGRAM_ROOT / "handlers" / "admin" / "common.py").exists()
    assert not (TELEGRAM_ROOT / "handlers" / "user" / "common.py").exists()


def test_presentation_layer_has_no_wildcard_imports() -> None:
    offenders = []
    for path in TELEGRAM_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        if " import *" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_handlers_do_not_import_global_keyboard_or_text_facades() -> None:
    offenders = []
    for path in (TELEGRAM_ROOT / "handlers").rglob("*.py"):
        text = path.read_text()
        if "from app.bot.telegram import keyboards" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        if "from app.bot.telegram import texts" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        if "from app.bot.telegram.texts import admin" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        if "from app.bot.telegram.texts import user" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        flat_buttons_import = "from app.bot.telegram.keyboards import " + "buttons"
        if flat_buttons_import in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_flat_formatter_and_text_monoliths_are_removed() -> None:
    assert not (TELEGRAM_ROOT / "formatters.py").exists()
    assert not (TELEGRAM_ROOT / "texts" / "admin.py").exists()
    assert not (TELEGRAM_ROOT / "texts" / "user.py").exists()


def test_handlers_do_not_import_formatter_functions_from_top_level_package() -> None:
    offenders = []
    for path in (TELEGRAM_ROOT / "handlers").rglob("*.py"):
        text = path.read_text()
        if "from app.bot.telegram.formatters import (" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
            continue
        for line in text.splitlines():
            if not line.startswith("from app.bot.telegram.formatters import "):
                continue
            imported = line.removeprefix("from app.bot.telegram.formatters import ").strip()
            if imported.startswith("format_"):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_formatter_text_and_keyboard_modules_keep_presentation_boundaries() -> None:
    forbidden_in_formatters = (
        "app.services",
        "app.db.repositories",
        "app.db.models",
    )
    forbidden_in_texts = (
        "app.services",
        "app.db.repositories",
        "app.db.models",
        "app.bot.telegram.handlers",
    )
    offenders = []

    for path in (TELEGRAM_ROOT / "formatters").rglob("*.py"):
        text = path.read_text()
        if any(pattern in text for pattern in forbidden_in_formatters):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    for path in (TELEGRAM_ROOT / "texts").rglob("*.py"):
        text = path.read_text()
        if any(pattern in text for pattern in forbidden_in_texts):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    for path in (TELEGRAM_ROOT / "keyboards").rglob("*.py"):
        text = path.read_text()
        if "app.bot.telegram.handlers" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_message_edit_helper_keeps_presentation_boundary() -> None:
    source = (TELEGRAM_ROOT / "message_edit.py").read_text()

    assert "app.services" not in source
    assert "app.db.repositories" not in source
    assert "app.db.models" not in source
    assert "app.domain" not in source


def test_inline_navigation_uses_idempotent_edit_helpers() -> None:
    offenders = []
    for path in (TELEGRAM_ROOT / "handlers").rglob("*.py"):
        source = path.read_text()
        if ".edit_text(" in source or ".edit_reply_markup(" in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []

    expected_users = {
        "handlers/admin/check_in.py": "edit_message_if_changed",
        "handlers/admin/results.py": "edit_message_if_changed",
        "handlers/superadmin/registrations.py": "edit_message_if_changed",
        "handlers/superadmin/seasons.py": "edit_message_if_changed",
        "handlers/superadmin/tournament_close.py": "edit_message_if_changed",
        "handlers/user/rating.py": "edit_message_if_changed",
        "handlers/user/shared.py": "edit_message_if_changed",
        "handlers/user/tournaments.py": "edit_reply_markup_if_changed",
    }
    missing = []
    for relative_path, helper_name in expected_users.items():
        source = (TELEGRAM_ROOT / relative_path).read_text()
        if helper_name not in source:
            missing.append(relative_path)

    assert missing == []
