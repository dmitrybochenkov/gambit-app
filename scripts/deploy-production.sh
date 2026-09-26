#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly BACKEND_DIR="$REPO_ROOT/backend"
readonly SERVICE_NAME="${GAMBIT_SERVICE_NAME:-gambit.service}"
readonly DB_PATH="${GAMBIT_DB_PATH:-$REPO_ROOT/data/gambit.db}"
readonly BACKUP_DIR="${GAMBIT_BACKUP_DIR:-$REPO_ROOT/data/backups}"
readonly HEALTH_URL="${GAMBIT_HEALTH_URL:-http://127.0.0.1:8100/health}"
readonly REMOTE_NAME="${GAMBIT_DEPLOY_REMOTE:-origin}"
readonly DEPLOY_BRANCH="${GAMBIT_DEPLOY_BRANCH:-main}"
readonly HEALTH_ATTEMPTS="${GAMBIT_HEALTH_ATTEMPTS:-12}"
readonly HEALTH_DELAY_SECONDS="${GAMBIT_HEALTH_DELAY_SECONDS:-2}"

stage="preflight"
service_stopped=false
service_start_attempted=false
backup_path=""

log_stage() {
    printf '\n[%s]\n' "$1"
}

diagnose_service() {
    sudo systemctl status "$SERVICE_NAME" --no-pager || true
    sudo journalctl -u "$SERVICE_NAME" -n 50 --no-pager -o cat || true
}

on_error() {
    local exit_code=$?
    trap - ERR
    printf '\nDeployment failed during [%s].\n' "$stage" >&2
    if [[ -n "$backup_path" ]]; then
        printf 'Database backup: %s\n' "$backup_path" >&2
    fi
    if [[ "$service_stopped" == true && "$service_start_attempted" == false ]]; then
        printf '%s remains stopped; no automatic rollback or restore was attempted.\n' \
            "$SERVICE_NAME" >&2
    fi
    if [[ "$service_start_attempted" == true ]]; then
        diagnose_service
    fi
    exit "$exit_code"
}

trap on_error ERR

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'Required command is unavailable: %s\n' "$1" >&2
        return 1
    }
}

log_stage "$stage"
for command_name in git uv sqlite3 curl sudo systemctl journalctl; do
    require_command "$command_name"
done

actual_root="$(git -C "$REPO_ROOT" rev-parse --show-toplevel)"
if [[ "$actual_root" != "$REPO_ROOT" ]]; then
    printf 'Script is not inside the expected repository root: %s\n' "$REPO_ROOT" >&2
    false
fi
if [[ ! -f "$BACKEND_DIR/alembic.ini" || ! -f "$BACKEND_DIR/pyproject.toml" ]]; then
    printf 'Backend deployment files are missing under %s\n' "$BACKEND_DIR" >&2
    false
fi
if [[ ! -f "$DB_PATH" ]]; then
    printf 'Production database does not exist: %s\n' "$DB_PATH" >&2
    false
fi

git -C "$REPO_ROOT" diff --quiet
git -C "$REPO_ROOT" diff --cached --quiet
current_branch="$(git -C "$REPO_ROOT" branch --show-current)"
if [[ "$current_branch" != "$DEPLOY_BRANCH" ]]; then
    printf 'Expected branch %s, found %s.\n' "$DEPLOY_BRANCH" "$current_branch" >&2
    false
fi

stage="update"
log_stage "$stage"
git -C "$REPO_ROOT" fetch "$REMOTE_NAME" "$DEPLOY_BRANCH"
git -C "$REPO_ROOT" merge --ff-only "$REMOTE_NAME/$DEPLOY_BRANCH"
deployed_commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"

stage="backup"
log_stage "$stage"
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%d-%H%M%S)"
backup_path="$BACKUP_DIR/gambit-before-deploy-${timestamp}-${deployed_commit:0:12}.db"
if [[ -e "$backup_path" ]]; then
    printf 'Refusing to overwrite existing backup: %s\n' "$backup_path" >&2
    false
fi
sqlite3 "$DB_PATH" ".backup \"$backup_path\""
if [[ ! -s "$backup_path" ]]; then
    printf 'SQLite backup is missing or empty: %s\n' "$backup_path" >&2
    false
fi
backup_integrity="$(sqlite3 "$backup_path" "PRAGMA integrity_check;")"
if [[ "$backup_integrity" != "ok" ]]; then
    printf 'SQLite backup integrity check failed: %s\n' "$backup_integrity" >&2
    false
fi

stage="stop"
log_stage "$stage"
sudo systemctl stop "$SERVICE_NAME"
service_stopped=true

stage="dependencies"
log_stage "$stage"
(cd "$BACKEND_DIR" && uv sync)

stage="migrate"
log_stage "$stage"
expected_head_output="$(cd "$BACKEND_DIR" && uv run alembic heads)"
expected_head="${expected_head_output%% *}"
if [[ -z "$expected_head" || "$expected_head_output" == *$'\n'* ]]; then
    printf 'Expected exactly one Alembic head, got: %s\n' "$expected_head_output" >&2
    false
fi
(cd "$BACKEND_DIR" && uv run alembic upgrade head)
current_revision_output="$(cd "$BACKEND_DIR" && uv run alembic current)"
current_revision="${current_revision_output%% *}"
if [[ "$current_revision" != "$expected_head" ]]; then
    printf 'Alembic revision mismatch: current=%s expected=%s\n' \
        "$current_revision" "$expected_head" >&2
    false
fi

stage="start"
log_stage "$stage"
service_start_attempted=true
sudo systemctl start "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME"
service_stopped=false

stage="health"
log_stage "$stage"
health_ok=false
for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --max-time 5 "$HEALTH_URL" >/dev/null; then
        health_ok=true
        break
    fi
    if ((attempt < HEALTH_ATTEMPTS)); then
        sleep "$HEALTH_DELAY_SECONDS"
    fi
done
if [[ "$health_ok" != true ]]; then
    printf 'Health check failed after %s attempts: %s\n' \
        "$HEALTH_ATTEMPTS" "$HEALTH_URL" >&2
    false
fi

post_start_revision_output="$(cd "$BACKEND_DIR" && uv run alembic current)"
post_start_revision="${post_start_revision_output%% *}"
if [[ "$post_start_revision" != "$expected_head" ]]; then
    printf 'Post-start Alembic revision mismatch: current=%s expected=%s\n' \
        "$post_start_revision" "$expected_head" >&2
    false
fi

stage="done"
log_stage "$stage"
printf 'Deployed git commit: %s\n' "$deployed_commit"
printf 'Alembic revision: %s\n' "$post_start_revision"
printf 'Service state: active\n'
printf 'Health result: ok (%s)\n' "$HEALTH_URL"
printf 'Database backup: %s\n' "$backup_path"
