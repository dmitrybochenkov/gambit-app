import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
SQLALCHEMY_QUERY_NAMES = {"select", "insert", "update", "delete"}
SESSION_QUERY_METHODS = {"execute", "scalar", "scalars"}
SESSION_PERSISTENCE_METHODS = {"add", "delete"}


def test_services_do_not_build_sqlalchemy_queries_directly() -> None:
    violations: list[str] = []
    for path in sorted(SERVICES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                imported_names = {alias.name for alias in node.names}
                forbidden_names = imported_names & SQLALCHEMY_QUERY_NAMES
                for name in sorted(forbidden_names):
                    violations.append(f"{path.relative_to(SERVICES_DIR.parent)} imports {name}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr in SESSION_QUERY_METHODS | SESSION_PERSISTENCE_METHODS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "session"
                ):
                    violations.append(
                        f"{path.relative_to(SERVICES_DIR.parent)} calls session.{node.func.attr}()"
                    )

    assert violations == []


def test_services_do_not_use_dunder_dict_as_dto_mapping() -> None:
    violations: list[str] = []
    for path in sorted(SERVICES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "__dict__":
                violations.append(f"{path.relative_to(SERVICES_DIR.parent)} uses .__dict__")

    assert violations == []
