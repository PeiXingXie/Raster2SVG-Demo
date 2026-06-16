#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
ENV_FILE="${PROJECT_ROOT}/.env"

read_dotenv_value() {
  local key="$1"
  local file="$2"

  [[ -f "${file}" ]] || return 1

  awk -F '=' -v target="${key}" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      current=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", current)
      if (current == target) {
        value=substr($0, index($0, "=") + 1)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
        print value
        exit
      }
    }
  ' "${file}"
}

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Error: virtual environment not found at ${VENV_DIR}" >&2
  echo "Run ./bootstrap.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

if [[ -z "${APP_HOST:-}" ]]; then
  APP_HOST="$(read_dotenv_value "APP_HOST" "${ENV_FILE}" || true)"
fi
if [[ -z "${APP_PORT:-}" ]]; then
  APP_PORT="$(read_dotenv_value "APP_PORT" "${ENV_FILE}" || true)"
fi

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8120}"

echo "Project root: ${PROJECT_ROOT}"
echo "Starting uvicorn on http://${APP_HOST}:${APP_PORT}"

cd "${PROJECT_ROOT}"
exec python -m uvicorn deepagents_template.api:app --host "${APP_HOST}" --port "${APP_PORT}" "$@"
