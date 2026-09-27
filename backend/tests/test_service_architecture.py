import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
APP_DIR = SERVICES_DIR.parent
SQLALCHEMY_QUERY_NAMES = {"select", "insert", "update", "delete"}
SESSION_QUERY_METHODS = {"execute", "scalar", "scalars"}
SESSION_PERSISTENCE_METHODS = {"add", "delete"}
INTERNAL_ACTOR_SERVICE_METHODS = {
    "profile_service.py": {
        "get_profile_for_player",
        "list_profile_seasons",
        "list_prize_tournaments_for_player",
    },
    "rating_service.py": {"get_rating_for_player", "list_rating_seasons"},
    "user_statistics_service.py": {
        "list_history_years",
        "list_history_months",
        "list_history_tournaments",
        "get_historical_tournament_result",
        "list_player_history",
        "get_player_history_tournament_result",
        "get_hall_of_fame",
        "_ensure_user_can_view_statistics",
    },
    "tournament_service.py": {
        "get_schedule_for_player",
        "get_schedule_tournament_details_for_player",
        "get_registration_options_for_player",
        "get_player_upcoming_registrations",
        "get_current_week_tournaments_for_player",
        "get_current_week_tournament_for_player",
        "get_current_week_registrations_for_player",
        "register_player_for_tournaments",
        "cancel_player_tournament_registrations",
    },
    "player_reward_service.py": {
        "list_current_active_rewards_for_player",
        "list_active_rewards_for_check_in",
        "get_active_reward_for_player",
        "redeem_reward",
    },
    "tournament_check_in_service.py": {
        "list_today_tournaments",
        "get_check_in",
        "get_checked_in_players",
        "search_registered",
        "search_users",
        "find_new_player_candidates",
        "get_user_check_in_confirmation",
        "get_user_check_in_decision",
        "complete_user_check_in",
        "get_registered_check_in_decision",
        "get_existing_user_check_in_decision",
        "get_new_user_check_in_confirmation",
        "check_in_registered",
        "check_in_user",
        "check_in_existing_user",
        "create_user_and_check_in",
    },
    "result_service.py": {
        "get_today_tournament_results",
        "list_editable_tournaments",
        "get_tournament_results",
        "update_player_result_field",
        "validate_results",
    },
    "tournament_combination_service.py": {
        "list_for_tournament",
        "add_combination",
        "delete_combination",
    },
    "tournament_participant_service.py": {
        "search_existing_users_for_tournament",
        "get_existing_player_add_confirmation",
        "get_new_player_add_confirmation",
        "add_existing_player_to_tournament",
        "add_new_player_to_tournament",
    },
    "tournament_photo_service.py": {
        "list_for_tournament",
        "count_for_tournament",
        "add_photo",
        "delete_photos",
    },
}

INTERNAL_ADMIN_ACTOR_METHODS = {
    method_name
    for filename in (
        "tournament_check_in_service.py",
        "result_service.py",
        "tournament_combination_service.py",
        "tournament_participant_service.py",
        "tournament_photo_service.py",
    )
    for method_name in INTERNAL_ACTOR_SERVICE_METHODS[filename]
} | {
    "list_active_rewards_for_check_in",
    "get_active_reward_for_player",
    "redeem_reward",
}


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


def test_access_policy_uses_only_internal_actor_identity() -> None:
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
        assert method_name not in methods
    for method_name, method in methods.items():
        if not method_name.startswith("_") and "get_by_telegram_id" in _method_calls(method):
            assert method_name.endswith("_by_telegram_id")

    ambiguous_callers: list[str] = []
    for path in sorted(SERVICES_DIR.glob("*.py")):
        if path == policy_path or path.name == "user_access_service.py":
            continue
        caller_tree = ast.parse(path.read_text(), filename=str(path))
        for method in ast.walk(caller_tree):
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(method):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "access_policy"
                    and node.func.attr
                    in {"require_active_user", "require_admin", "require_superadmin"}
                    and "actor_user_id"
                    not in {
                        argument.arg for argument in (*method.args.args, *method.args.kwonlyargs)
                    }
                ):
                    ambiguous_callers.append(
                        f"{path.name}:{node.lineno} {method.name} calls {node.func.attr}"
                    )

    assert ambiguous_callers == []


def test_migrated_admin_telegram_handlers_resolve_actor_before_service_calls() -> None:
    handler_paths = [
        APP_DIR / "bot" / "telegram" / "handlers" / "admin" / filename
        for filename in ("calendar.py", "schedule.py", "results.py")
    ] + [
        APP_DIR / "bot" / "telegram" / "handlers" / "superadmin" / filename
        for filename in (
            "administrators.py",
            "hall_of_fame.py",
            "registrations.py",
            "seasons.py",
            "tournament_close.py",
            "tournaments.py",
            "users.py",
        )
    ]
    violations: list[str] = []
    for path in handler_paths:
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if "from_user.id" not in line:
                continue
            if any(
                allowed in line
                for allowed in (
                    "resolve_admin_actor_user_id",
                    "user_access_service",
                    "superadmin_telegram_id=",
                )
            ):
                continue
            violations.append(f"{path.name}:{line_number} passes raw from_user.id")

    assert violations == []


def test_migrated_service_slices_use_internal_actor_identity() -> None:
    for filename, method_names in INTERNAL_ACTOR_SERVICE_METHODS.items():
        path = SERVICES_DIR / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for method_name in method_names:
            method = methods[method_name]
            argument_names = {
                argument.arg for argument in (*method.args.args, *method.args.kwonlyargs)
            }
            assert "actor_user_id" in argument_names, f"{filename}:{method_name}"
            assert not any(name.endswith("_by_telegram_id") for name in _method_calls(method)), (
                f"{filename}:{method_name}"
            )

    for filename in (
        "profile.py",
        "ratings.py",
        "history.py",
        "hall_of_fame.py",
        "rewards.py",
        "tournaments.py",
    ):
        source = (APP_DIR / "api" / "v1" / filename).read_text()
        assert "actor.telegram_id" not in source


def test_admin_http_routes_pass_internal_actor_to_migrated_services() -> None:
    for filename in ("admin_check_in.py", "admin_tournaments.py"):
        path = APP_DIR / "api" / "v1" / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in INTERNAL_ADMIN_ACTOR_METHODS
            ):
                continue
            arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
            assert not any(
                isinstance(argument, ast.Attribute)
                and argument.attr == "telegram_id"
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "actor"
                for argument in arguments
            ), f"{filename}:{node.lineno} passes actor.telegram_id"


def test_migrated_telegram_player_handlers_resolve_actor_before_service_call() -> None:
    migrated_methods = {
        "get_profile_for_player",
        "list_profile_seasons",
        "list_prize_tournaments_for_player",
        "get_rating_for_player",
        "list_rating_seasons",
        "list_history_years",
        "list_history_months",
        "list_history_tournaments",
        "get_historical_tournament_result",
        "get_hall_of_fame",
        "get_schedule_for_player",
        "get_schedule_tournament_details_for_player",
        "get_registration_options_for_player",
        "get_player_upcoming_registrations",
        "register_player_for_tournaments",
        "cancel_player_tournament_registrations",
    }
    handler_dir = APP_DIR / "bot" / "telegram" / "handlers" / "user"
    violations: list[str] = []

    for filename in ("profile.py", "rating.py", "history.py", "hall_of_fame.py", "tournaments.py"):
        path = handler_dir / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in migrated_methods
            ):
                continue
            direct_arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
            for argument in direct_arguments:
                if (
                    isinstance(argument, ast.Attribute)
                    and argument.attr == "id"
                    and isinstance(argument.value, ast.Attribute)
                    and argument.value.attr == "from_user"
                ):
                    violations.append(f"{filename}:{node.lineno} passes from_user.id directly")

    assert violations == []


def test_migrated_telegram_admin_handlers_resolve_actor_before_service_call() -> None:
    violations: list[str] = []
    for path in (
        APP_DIR / "bot" / "telegram" / "handlers" / "admin" / "check_in.py",
        APP_DIR / "bot" / "telegram" / "handlers" / "admin" / "results.py",
        APP_DIR / "bot" / "telegram" / "handlers" / "superadmin" / "tournament_close.py",
    ):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in INTERNAL_ADMIN_ACTOR_METHODS
            ):
                continue
            arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
            for argument in arguments:
                if (
                    isinstance(argument, ast.Attribute)
                    and argument.attr == "id"
                    and isinstance(argument.value, ast.Attribute)
                    and argument.value.attr == "from_user"
                ):
                    violations.append(f"{path.name}:{node.lineno} passes from_user.id directly")

    assert violations == []


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


def test_result_rules_are_pure_and_have_one_canonical_owner() -> None:
    rules_path = SERVICES_DIR / "result_rules.py"
    rules_tree = ast.parse(rules_path.read_text(), filename=str(rules_path))
    forbidden_import_prefixes = (
        "sqlalchemy",
        "fastapi",
        "aiogram",
        "app.bot",
        "app.db.repositories",
        "app.services.access_policy",
        "app.services.result_service",
    )
    imports = [
        node.module or "" for node in ast.walk(rules_tree) if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(rules_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imports
        for prefix in forbidden_import_prefixes
    )

    extracted_rules = {
        "validate_game_results",
        "validate_tournament_fund",
        "calculate_tournament_points",
        "calculate_knockout_points",
        "find_result_player",
        "result_field_is_allowed",
        "editable_result_fields",
        "occupied_result_places",
    }
    assert {
        node.name
        for node in rules_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } >= extracted_rules

    result_service_tree = ast.parse((SERVICES_DIR / "result_service.py").read_text())
    result_service_class = next(
        node
        for node in result_service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResultService"
    )
    assert (
        not {
            node.name
            for node in result_service_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        & extracted_rules
    )


def test_result_service_private_names_are_not_imported_by_other_modules() -> None:
    violations: list[str] = []
    repository_root = APP_DIR.parents[1]
    production_paths = [*APP_DIR.rglob("*.py")]
    scripts_dir = repository_root / "scripts"
    production_paths.extend(scripts_dir.rglob("*.py"))
    for path in sorted(production_paths):
        if path == SERVICES_DIR / "result_service.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.services.result_service":
                for alias in node.names:
                    if alias.name.startswith("_"):
                        violations.append(
                            f"{path.relative_to(repository_root)}:{node.lineno} {alias.name}"
                        )

    assert violations == []


def test_closed_correction_uses_result_rules_without_result_service_dependency() -> None:
    path = SERVICES_DIR / "closed_tournament_correction_service.py"
    tree = ast.parse(path.read_text(), filename=str(path))

    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "app.services.result_service"
        for node in ast.walk(tree)
    )
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "app.services.result_rules"
        for node in ast.walk(tree)
    )


def test_application_actor_parameters_do_not_regress_to_transport_identity() -> None:
    violations: list[str] = []
    for path in sorted(SERVICES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            argument_names = {argument.arg for argument in (*node.args.args, *node.args.kwonlyargs)}
            forbidden = argument_names & {"actor_telegram_id", "reviewer_telegram_id"}
            for name in sorted(forbidden):
                violations.append(f"{path.name}:{node.lineno} {node.name} accepts {name}")

    assert violations == []


def test_audited_services_do_not_call_private_methods_of_service_dependencies() -> None:
    violations: list[str] = []
    for filename in (
        "result_service.py",
        "closed_tournament_correction_service.py",
        "tournament_planning_service.py",
    ):
        path = SERVICES_DIR / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if node.func.attr.startswith("_") and (
                (
                    isinstance(receiver, ast.Attribute)
                    and isinstance(receiver.value, ast.Name)
                    and receiver.value.id == "self"
                    and receiver.attr.endswith("service")
                )
                or (
                    isinstance(receiver, ast.Name)
                    and receiver.id.endswith("service")
                    and receiver.id != "self"
                )
                or (
                    isinstance(receiver, ast.Call)
                    and isinstance(receiver.func, ast.Name)
                    and receiver.func.id.endswith("Service")
                )
            ):
                violations.append(
                    f"{filename}:{node.lineno} calls private dependency method {node.func.attr}()"
                )

    assert violations == []


def test_repositories_do_not_own_transaction_completion() -> None:
    repositories_dir = APP_DIR / "db" / "repositories"
    violations: list[str] = []
    for path in sorted(repositories_dir.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"commit", "rollback"}
            ):
                violations.append(f"{path.name}:{node.lineno} calls {node.func.attr}()")

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
