#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="${SCRIPT_DIR}"
PROJECT_ROOT="$(cd "${DESKTOP_ROOT}/.." && pwd)"
RUNTIME_ENV_FILE="${PROJECT_ROOT}/.runtime_startup.env"
ENV_FILE="${PROJECT_ROOT}/.env"
FRONTEND_URL=""
SKIP_BOOTSTRAP="false"
BACKEND_WAIT_TIMEOUT_SECONDS="${BACKEND_WAIT_TIMEOUT_SECONDS:-20}"

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

wait_backend_health() {
  local base_url="$1"
  local health_url="${base_url%/}/health"
  local waited=0

  while (( waited < BACKEND_WAIT_TIMEOUT_SECONDS )); do
    if command -v curl >/dev/null 2>&1; then
      if curl --fail --silent "${health_url}" >/dev/null 2>&1; then
        echo "Backend health check passed: ${base_url}"
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q -O /dev/null "${health_url}" >/dev/null 2>&1; then
        echo "Backend health check passed: ${base_url}"
        return 0
      fi
    else
      echo "Warning: curl and wget are both unavailable, so backend health cannot be checked automatically." >&2
      return 0
    fi

    if (( waited == 0 )); then
      echo "Waiting for backend health at ${health_url} ..."
    fi

    sleep 1
    waited=$((waited + 1))
  done

  echo "Warning: backend health check failed for ${base_url} after ${BACKEND_WAIT_TIMEOUT_SECONDS}s. Start the FastAPI service first and verify ${health_url} in a browser." >&2
  return 1
}

resolve_service_url() {
  local raw_url="$1"
  if [[ "${raw_url}" =~ ^(https?://[^/]+) ]]; then
    printf '%s/\n' "${BASH_REMATCH[1]}"
  else
    printf '%s\n' "${raw_url}"
  fi
}

for arg in "$@"; do
  case "${arg}" in
    --skip-bootstrap)
      SKIP_BOOTSTRAP="true"
      ;;
    http://*|https://*)
      FRONTEND_URL="${arg}"
      ;;
    *)
      echo "Error: unsupported argument '${arg}'" >&2
      echo "Supported arguments: --skip-bootstrap [frontend-url]" >&2
      exit 1
      ;;
  esac
done

FRONTEND_URL="${FRONTEND_URL:-${RASTER_SVG_FRONTEND_URL:-}}"
if [[ -z "${FRONTEND_URL}" ]]; then
  CONFIG_SOURCE="built-in default"
  APP_HOST=""
  APP_PORT=""
  for candidate_file in "${RUNTIME_ENV_FILE}" "${ENV_FILE}"; do
    [[ -f "${candidate_file}" ]] || continue
    APP_HOST="$(read_dotenv_value "APP_HOST" "${candidate_file}" || true)"
    APP_PORT="$(read_dotenv_value "APP_PORT" "${candidate_file}" || true)"
    CONFIG_SOURCE="${candidate_file}"
    if [[ -n "${APP_HOST}" || -n "${APP_PORT}" ]]; then
      break
    fi
  done
  APP_HOST="${APP_HOST:-127.0.0.1}"
  APP_PORT="${APP_PORT:-8120}"
  FRONTEND_URL="http://${APP_HOST}:${APP_PORT}/"
  echo "Frontend URL source: ${CONFIG_SOURCE}"
fi

if [[ "${SKIP_BOOTSTRAP}" != "true" ]]; then
  "${DESKTOP_ROOT}/bootstrap.sh"
fi

ELECTRON_CMD="${DESKTOP_ROOT}/node_modules/.bin/electron"
if [[ ! -x "${ELECTRON_CMD}" ]]; then
  echo "Error: Electron launch command not found at ${ELECTRON_CMD}" >&2
  exit 1
fi

SERVICE_URL="$(resolve_service_url "${FRONTEND_URL}")"
wait_backend_health "${SERVICE_URL}" || true

pushd "${DESKTOP_ROOT}" >/dev/null
export RASTER_SVG_FRONTEND_URL="${FRONTEND_URL}"
echo "Launching desktop shell against ${FRONTEND_URL}"
"${ELECTRON_CMD}" .
popd >/dev/null
