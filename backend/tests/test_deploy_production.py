import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "deploy-production.sh"
LOCAL_DEPLOY_WRAPPER = PROJECT_ROOT / "scripts" / "deploy.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture
def deploy_checkout(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "checkout"
    scripts = root / "scripts"
    backend = root / "backend"
    data = root / "data"
    bin_dir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    backend.mkdir()
    data.mkdir()
    bin_dir.mkdir()
    (backend / "alembic.ini").write_text("[alembic]\n")
    (backend / "pyproject.toml").write_text("[project]\n")
    (data / "gambit.db").write_bytes(b"database")
    script = scripts / "deploy-production.sh"
    script.write_text(DEPLOY_SCRIPT.read_text())
    script.chmod(0o755)

    command_log = tmp_path / "commands.log"
    common_header = '#!/usr/bin/env bash\nset -eu\nprintf \'%s\\n\' "$0 $*" >> "$COMMAND_LOG"\n'
    _write_executable(
        bin_dir / "git",
        common_header
        + """
case "$*" in
  *"rev-parse --show-toplevel"*) printf '%s\n' "$TEST_REPO_ROOT" ;;
  *"branch --show-current"*) printf 'main\n' ;;
  *"merge --ff-only"*) [[ "${FAIL_UPDATE:-0}" != 1 ]] ;;
  *"rev-parse HEAD"*) printf '0123456789abcdef0123456789abcdef01234567\n' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "sqlite3",
        common_header
        + """
if [[ "$2" == .backup* ]]; then
  backup_path="${2:9:${#2}-10}"
  printf 'backup\n' > "$backup_path"
else
  printf 'ok\n'
fi
""",
    )
    _write_executable(
        bin_dir / "uv",
        common_header
        + """
case "$*" in
  "run alembic heads") printf 'd4e5f6a7b8c9 (head)\n' ;;
  "run alembic upgrade head") [[ "${FAIL_MIGRATION:-0}" != 1 ]] ;;
  "run alembic current") printf 'd4e5f6a7b8c9 (head)\n' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "sudo",
        common_header + 'exec "$@"\n',
    )
    _write_executable(bin_dir / "systemctl", common_header + "exit 0\n")
    _write_executable(bin_dir / "journalctl", common_header + "exit 0\n")
    _write_executable(bin_dir / "curl", common_header + "exit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "COMMAND_LOG": str(command_log),
            "TEST_REPO_ROOT": str(root),
            "GAMBIT_HEALTH_ATTEMPTS": "1",
            "GAMBIT_HEALTH_DELAY_SECONDS": "0",
        }
    )
    return script, command_log, env


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=script.parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_deploy_script_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(DEPLOY_SCRIPT)], check=True)
    subprocess.run(["bash", "-n", str(LOCAL_DEPLOY_WRAPPER)], check=True)


def test_local_deploy_wrapper_calls_expected_remote_entrypoint(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$*" > "$SSH_COMMAND_LOG"\n'
        'exit "${SSH_EXIT_CODE:-0}"\n',
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "SSH_COMMAND_LOG": str(command_log),
        }
    )

    result = subprocess.run(
        ["bash", str(LOCAL_DEPLOY_WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert command_log.read_text().strip() == (
        "-t dimension-x cd /opt/apps/gambit && scripts/deploy-production.sh"
    )


def test_local_deploy_wrapper_propagates_remote_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "ssh", "#!/usr/bin/env bash\nexit 23\n")
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}"})

    result = subprocess.run(
        ["bash", str(LOCAL_DEPLOY_WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23


def test_local_deploy_wrapper_contains_no_deployment_implementation() -> None:
    source = LOCAL_DEPLOY_WRAPPER.read_text()

    for forbidden in ("git ", "uv ", "alembic", "sqlite3", "systemctl", "curl"):
        assert forbidden not in source
    assert source.count("ssh ") == 1
    assert "scripts/deploy-production.sh" in source


def test_update_failure_does_not_stop_service(
    deploy_checkout: tuple[Path, Path, dict[str, str]],
) -> None:
    script, command_log, env = deploy_checkout
    env["FAIL_UPDATE"] = "1"

    result = _run(script, env)

    assert result.returncode != 0
    commands = command_log.read_text()
    assert "merge --ff-only origin/main" in commands
    assert "systemctl stop" not in commands
    assert "sqlite3" not in commands


def test_migration_failure_leaves_service_stopped_and_does_not_start_it(
    deploy_checkout: tuple[Path, Path, dict[str, str]],
) -> None:
    script, command_log, env = deploy_checkout
    env["FAIL_MIGRATION"] = "1"

    result = _run(script, env)

    assert result.returncode != 0
    commands = command_log.read_text()
    assert "systemctl stop gambit.service" in commands
    assert "run alembic upgrade head" in commands
    assert "systemctl start" not in commands
    assert "remains stopped" in result.stderr
    assert "no automatic rollback or restore" in result.stderr


def test_successful_deploy_runs_fail_safe_sequence(
    deploy_checkout: tuple[Path, Path, dict[str, str]],
) -> None:
    script, command_log, env = deploy_checkout

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text().splitlines()
    update_index = next(i for i, item in enumerate(commands) if "merge --ff-only" in item)
    backup_index = next(i for i, item in enumerate(commands) if ".backup" in item)
    stop_index = next(i for i, item in enumerate(commands) if "systemctl stop" in item)
    sync_index = next(i for i, item in enumerate(commands) if item.endswith("/uv sync"))
    migrate_index = next(i for i, item in enumerate(commands) if "upgrade head" in item)
    start_index = next(i for i, item in enumerate(commands) if "systemctl start" in item)
    health_index = next(i for i, item in enumerate(commands) if "/curl " in item)
    assert update_index < backup_index < stop_index < sync_index < migrate_index < start_index
    assert start_index < health_index
    assert "Alembic revision: d4e5f6a7b8c9" in result.stdout
    assert "Service state: active" in result.stdout
    assert "Health result: ok" in result.stdout
