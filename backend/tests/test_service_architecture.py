import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
APP_DIR = SERVICES_DIR.parent
SQLALCHEMY_QUERY_NAMES = {"select", "insert", "update", "delete"}
SESSION_QUERY_METHODS = {"execute", "scalar", "scalars"}
SESSION_PERSISTENCE_METHODS = {"add", "delete"}


def _method_calls(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


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


def test_access_policy_keeps_internal_and_telegram_identity_namespaces_explicit() -> None:
    policy_path = SERVICES_DIR / "access_policy.py"
    tree = ast.parse(policy_path.read_text(), filename=str(policy_path))
    policy_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AccessPolicy"
    )
    methods = {
        node.name: node
        for node in policy_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "get_by_id" in _method_calls(methods["require_active_user"])
    for method_name in ("require_active_user", "require_admin", "require_superadmin"):
        assert "get_by_telegram_id" not in _method_calls(methods[method_name])
    for method_name in (
        "require_active_user_by_telegram_id",
        "require_admin_by_telegram_id",
        "require_superadmin_by_telegram_id",
    ):
        assert method_name in methods
    for method_name, method in methods.items():
        if not method_name.startswith("_") and "get_by_telegram_id" in _method_calls(method):
            assert method_name.endswith("_by_telegram_id")

    ambiguous_callers: list[str] = []
    for path in sorted(SERVICES_DIR.glob("*.py")):
        if path == policy_path:
            continue
        caller_tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(caller_tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "access_policy"
                and node.func.attr in {"require_active_user", "require_admin", "require_superadmin"}
            ):
                ambiguous_callers.append(f"{path.name}:{node.lineno} {node.func.attr}")

    assert ambiguous_callers == []


def test_result_service_does_not_own_photo_or_combination_repositories() -> None:
    result_service = SERVICES_DIR / "result_service.py"
    source = result_service.read_text()

    assert "TournamentPhotoRepository" not in source
    assert "TournamentCombinationRepository" not in source
    assert (
        "class TournamentPhotoService" in (SERVICES_DIR / "tournament_photo_service.py").read_text()
    )
    assert (
        "class TournamentCombinationService"
        in (SERVICES_DIR / "tournament_combination_service.py").read_text()
    )


def test_result_service_does_not_own_open_participant_roster_use_cases() -> None:
    result_service_source = (SERVICES_DIR / "result_service.py").read_text()
    participant_service_source = (SERVICES_DIR / "tournament_participant_service.py").read_text()

    for method_name in (
        "search_existing_users_for_tournament",
        "get_existing_player_add_confirmation",
        "get_new_player_add_confirmation",
        "add_existing_player_to_tournament",
        "add_new_player_to_tournament",
        "get_open_tournament_player_delete_preview",
        "list_open_tournament_players_for_delete",
        "delete_player_from_open_tournament",
    ):
        assert method_name not in result_service_source
        assert method_name in participant_service_source

    assert "app.bot" not in participant_service_source
    assert "fastapi" not in participant_service_source
    assert "TournamentCheckInService" not in participant_service_source


def test_closed_correction_does_not_access_private_result_service_members() -> None:
    path = SERVICES_DIR / "closed_tournament_correction_service.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "ResultService":
                violations.append(f"line {node.lineno}: constructs ResultService")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "ResultService" and node.attr.startswith("_"):
                violations.append(f"line {node.lineno}: accesses private ResultService.{node.attr}")
        elif isinstance(node, ast.arg) and isinstance(node.annotation, ast.Name):
            if node.annotation.id == "ResultService":
                violations.append(
                    f"line {node.lineno}: accepts ResultService dependency as {node.arg}"
                )

    assert violations == []


def test_telegram_check_in_uses_shared_application_mutation_boundary() -> None:
    path = SERVICES_DIR.parent / "bot" / "telegram" / "handlers" / "admin" / "check_in.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    forbidden_calls = {
        "check_in_existing_user",
        "check_in_registered",
        "check_in_user",
        "redeem_reward",
        "set_user_gender",
    }
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden_calls:
                violations.append(f"line {node.lineno}: calls {node.func.attr}()")
            if node.func.attr.startswith("_") and isinstance(node.func.value, ast.Name):
                if node.func.value.id.endswith("_service"):
                    violations.append(
                        f"line {node.lineno}: accesses private service method {node.func.attr}()"
                    )

    assert violations == []


def test_check_in_reward_queries_do_not_exchange_sessions_between_services() -> None:
    reward_service_source = (SERVICES_DIR / "player_reward_service.py").read_text()
    check_in_source = (SERVICES_DIR / "tournament_check_in_service.py").read_text()

    assert "list_active_reward_views_in_session" not in reward_service_source
    assert "list_active_reward_views_in_session" not in check_in_source

    tree = ast.parse(check_in_source)
    reward_decision = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_reward_decision_view"
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlayerRewardService"
        for node in ast.walk(reward_decision)
    )


def test_registration_review_application_boundary_is_transport_neutral() -> None:
    service_source = (SERVICES_DIR / "registration_review_service.py").read_text()
    use_case_source = (SERVICES_DIR / "registration_review_use_cases.py").read_text()
    dto_source = (SERVICES_DIR / "dto" / "registrations.py").read_text()

    for source in (service_source, use_case_source, dto_source):
        assert "aiogram" not in source
        assert "app.bot.telegram" not in source
        assert "CallbackQuery" not in source
        assert "Message" not in source
        assert "Bot" not in source

    assert "AsyncSession" not in use_case_source
    assert "Repository" not in use_case_source


def test_registration_review_handler_does_not_own_notification_policy() -> None:
    handler_source = (
        APP_DIR / "bot" / "telegram" / "handlers" / "superadmin" / "registrations.py"
    ).read_text()

    assert "list_active_superadmins_with_telegram" not in handler_source
    assert "notification_recipients" not in handler_source
    assert ".send_message(" not in handler_source
    assert "TelegramRegistrationReviewNotificationDelivery" in handler_source
    assert "RegistrationReviewUseCases" in handler_source


def test_admin_promotion_boundary_is_transport_neutral_and_shared() -> None:
    use_case_source = (SERVICES_DIR / "admin_management_use_cases.py").read_text()
    handler_source = (
        APP_DIR / "bot" / "telegram" / "handlers" / "superadmin" / "administrators.py"
    ).read_text()

    assert "aiogram" not in use_case_source
    assert "app.bot.telegram" not in use_case_source
    assert "AsyncSession" not in use_case_source
    assert "Repository" not in use_case_source
    assert ".send_message(" not in handler_source
    assert "AdminManagementUseCases" in handler_source
    assert "TelegramAdminPromotionNotificationDelivery" in handler_source
