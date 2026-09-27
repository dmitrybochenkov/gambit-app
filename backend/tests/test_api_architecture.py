import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"
API_ROOT = APP_ROOT / "api"
SERVICES_ROOT = APP_ROOT / "services"


def test_api_layer_does_not_import_orm_or_repositories() -> None:
    offenders = []
    for path in API_ROOT.rglob("*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        forbidden_import = any(
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module.startswith("app.db.repositories")
                or (
                    node.module.startswith("app.db.models") and node.module != "app.db.models.enums"
                )
            )
            for node in ast.walk(tree)
        )
        if forbidden_import:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_api_routes_do_not_own_transactions_or_depend_on_telegram_presentation() -> None:
    offenders = []
    for path in (API_ROOT / "v1").glob("*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        private_service_access = any(
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id.endswith("_service")
            for node in ast.walk(tree)
        )
        if (
            any(module.startswith("app.bot.telegram") for module in imports)
            or "AsyncSession" in source
            or "session_factory" in source
            or any(call in {"commit", "rollback"} for call in calls)
            or private_service_access
        ):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_tournament_api_does_not_import_orm_or_repositories() -> None:
    source = (API_ROOT / "v1" / "tournaments.py").read_text()

    assert "app.db.models" not in source
    assert "app.db.repositories" not in source


def test_services_do_not_import_fastapi_or_api_layer() -> None:
    offenders = []
    forbidden = ("fastapi", "app.api")
    for path in SERVICES_ROOT.rglob("*.py"):
        source = path.read_text()
        if any(pattern in source for pattern in forbidden):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_api_schemas_do_not_leak_into_services() -> None:
    offenders = []
    forbidden = ("app.api.v1.schemas", "PlayerTournamentResponse")
    for path in SERVICES_ROOT.rglob("*.py"):
        source = path.read_text()
        if any(pattern in source for pattern in forbidden):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_registration_review_api_uses_shared_application_boundary() -> None:
    path = API_ROOT / "v1" / "admin_registrations.py"
    source = path.read_text()
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert "app.bot.telegram" not in source
    assert "app.db.repositories" not in source
    assert "app.db.models" not in source
    assert "AsyncSession" not in source
    assert "notification_recipients" not in source
    assert "send_message" not in source
    assert any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "registration_review_use_cases"
        and call.func.attr == "approve"
        for call in calls
    )
    assert any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "registration_review_use_cases"
        and call.func.attr == "reject"
        for call in calls
    )
    assert not any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "registration_review_service"
        and call.func.attr in {"approve_registration", "reject_registration"}
        for call in calls
    )


def test_registration_review_http_delivery_uses_existing_bot_adapter() -> None:
    source = (API_ROOT / "registration_review_dependencies.py").read_text()

    assert "from app.bot.telegram import runtime" in source
    assert "bot = runtime.telegram_bot" in source
    assert "TelegramRegistrationReviewNotificationDelivery(bot)" in source
    assert "Bot(" not in source


def test_admin_users_api_uses_shared_application_boundaries() -> None:
    path = API_ROOT / "v1" / "admin_users.py"
    source = path.read_text()
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert "app.db.repositories" not in source
    assert "app.db.models" not in source
    assert "AsyncSession" not in source
    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert "telegram_id:" not in source
    assert any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "admin_management_use_cases"
        and call.func.attr == "promote_admin"
        for call in calls
    )
    assert not any(
        isinstance(call.func.value, ast.Name)
        and call.func.value.id == "admin_management_service"
        and call.func.attr == "add_admin"
        for call in calls
    )


def test_admin_users_api_exposes_no_generic_privilege_mutation() -> None:
    source = (API_ROOT / "v1" / "admin_users.py").read_text()
    schema_source = (API_ROOT / "v1" / "schemas" / "admin_users.py").read_text()
    schema_tree = ast.parse(schema_source)
    command_fields = {
        node.name: {
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
        for node in schema_tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Command")
    }

    assert '@router.patch("/{user_id}")' not in source
    assert '@router.delete("/{user_id}")' not in source
    assert "demote-admin" not in source
    assert '"/{user_id}/block"' not in source
    assert '"/{user_id}/unblock"' not in source
    assert all("role" not in fields for fields in command_fields.values())
    assert all("status" not in fields for fields in command_fields.values())


def test_admin_promotion_http_delivery_uses_current_runtime_bot() -> None:
    source = (API_ROOT / "admin_management_dependencies.py").read_text()

    assert "from app.bot.telegram import runtime" in source
    assert "bot = runtime.telegram_bot" in source
    assert "TelegramAdminPromotionNotificationDelivery(bot)" in source
    assert "Bot(" not in source
