from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"
API_ROOT = APP_ROOT / "api"
SERVICES_ROOT = APP_ROOT / "services"


def test_api_layer_does_not_import_orm_or_repositories() -> None:
    offenders = []
    forbidden = ("app.db.models", "app.db.repositories")
    for path in API_ROOT.rglob("*.py"):
        source = path.read_text()
        if any(pattern in source for pattern in forbidden):
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
