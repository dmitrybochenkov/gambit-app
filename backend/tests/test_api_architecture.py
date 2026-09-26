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
