#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
QUICK_START_DIR="${PROJECT_ROOT}/quick-start"
DESKTOP_DIR="${PROJECT_ROOT}/desktop"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
ENV_FILE="${PROJECT_ROOT}/.env"
RUNTIME_ENV_FILE="${PROJECT_ROOT}/.runtime_startup.env"
ENABLE_DESKTOP="${ENABLE_DESKTOP:-false}"
SKIP_BOOTSTRAP="${SKIP_BOOTSTRAP:-false}"
SKIP_DESKTOP_BOOTSTRAP="${SKIP_DESKTOP_BOOTSTRAP:-false}"
USE_ACTIVE_PYTHON="${USE_ACTIVE_PYTHON:-false}"
FORCE_BOOTSTRAP="${FORCE_BOOTSTRAP:-false}"

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

get_int_setting_value() {
  local key="$1"
  local file="$2"
  local default_value="$3"
  local value="${!key:-}"

  if [[ -n "${value}" ]]; then
    if [[ "${value}" =~ ^[1-9][0-9]*$ ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
    echo "Warning: ${key} value '${value}' from the current shell environment is invalid. Using ${default_value}." >&2
  fi

  value="$(read_dotenv_value "${key}" "${file}" || true)"
  if [[ -n "${value}" ]]; then
    if [[ "${value}" =~ ^[1-9][0-9]*$ ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
    echo "Warning: ${key} value '${value}' from ${file} is invalid. Using ${default_value}." >&2
  fi

  printf '%s\n' "${default_value}"
}

get_port_setting_value() {
  local key="$1"
  local file="$2"
  local default_value="$3"
  local value="${!key:-}"

  if [[ -n "${value}" ]]; then
    if [[ "${value}" =~ ^[0-9]+$ ]] && (( value >= 1 && value <= 65535 )); then
      printf '%s\n' "${value}"
      return 0
    fi
    echo "Warning: ${key} value '${value}' from the current shell environment is invalid. Expected 1-65535. Using ${default_value}." >&2
  fi

  value="$(read_dotenv_value "${key}" "${file}" || true)"
  if [[ -n "${value}" ]]; then
    if [[ "${value}" =~ ^[0-9]+$ ]] && (( value >= 1 && value <= 65535 )); then
      printf '%s\n' "${value}"
      return 0
    fi
    echo "Warning: ${key} value '${value}' from ${file} is invalid. Expected 1-65535. Using ${default_value}." >&2
  fi

  printf '%s\n' "${default_value}"
}

test_virtualenv_active() {
  [[ -n "${VIRTUAL_ENV:-}" ]]
}

test_conda_environment_active() {
  [[ -n "${CONDA_PREFIX:-}" ]]
}

get_python_executable_path() {
  local python_exe="$1"
  "${python_exe}" -c 'import sys; print(sys.executable)'
}

get_listening_pids() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true
    return 0
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "( sport = :${port} )" 2>/dev/null | awk '
      NR > 1 {
        line=$0
        pid_pos = index(line, "pid=")
        if (pid_pos > 0) {
          rest = substr(line, pid_pos + 4)
          split(rest, pid_parts, ",")
          print pid_parts[1]
        }
      }
    ' | sort -u
    return 0
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -ltnp 2>/dev/null | awk -v target=":${port}" '
      index($4, target) {
        split($7, parts, "/")
        if (parts[1] ~ /^[0-9]+$/) {
          print parts[1]
        }
      }
    ' | sort -u
    return 0
  fi

  echo "Error: cannot check port usage because lsof, ss, and netstat are all unavailable." >&2
  exit 1
}

describe_pid() {
  local pid="$1"
  local name="<unknown>"
  if command -v ps >/dev/null 2>&1; then
    name="$(ps -p "${pid}" -o comm= 2>/dev/null | awk '{$1=$1; print}')"
    name="${name:-<unknown>}"
  fi
  printf '  PID=%s Name=%s\n' "${pid}" "${name}"
}

find_free_port() {
  local preferred_port="$1"
  local candidate
  local candidate_pids

  for ((candidate = preferred_port + 1; candidate <= 65535; candidate++)); do
    candidate_pids="$(get_listening_pids "${candidate}")"
    if [[ -z "${candidate_pids}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  for ((candidate = 1024; candidate < preferred_port; candidate++)); do
    candidate_pids="$(get_listening_pids "${candidate}")"
    if [[ -z "${candidate_pids}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  echo "Error: unable to find a free TCP port automatically." >&2
  exit 1
}

resolve_listen_port_interactive() {
  local requested_port="$1"
  local current_port="${requested_port}"
  local pids_output
  local remaining_pids_output
  local pid

  while true; do
    pids_output="$(get_listening_pids "${current_port}")"
    if [[ -z "${pids_output}" ]]; then
      echo "Port check: ${current_port} is available." >&2
      printf '%s\n' "${current_port}"
      return 0
    fi

    echo "Warning: port ${current_port} is already in use." >&2
    echo "Current listeners on port ${current_port}:" >&2
    for pid in ${pids_output}; do
      [[ -n "${pid}" ]] || continue
      describe_pid "${pid}" >&2
    done
    echo "Input guide:" >&2
    echo "  yes / Yes / Y : stop the listed process(es) and keep using port ${current_port}" >&2
    echo "  no / NO / N   : choose another port or exit" >&2
    echo "  no input for ${PORT_PROMPT_TIMEOUT_SECONDS} seconds : automatically switch to a free port" >&2

    if ! IFS= read -r -t "${PORT_PROMPT_TIMEOUT_SECONDS}" -p "Do you want to release port ${current_port} and keep using it? (yes/Yes/Y/no/NO/N) " release_answer; then
      echo >&2
      echo "Warning: no input received within ${PORT_PROMPT_TIMEOUT_SECONDS} seconds." >&2
      auto_port="$(find_free_port "${current_port}")"
      echo "Port selection: automatically switching to free port ${auto_port}." >&2
      printf '%s\n' "${auto_port}"
      return 0
    fi

    if [[ "${release_answer}" =~ ^([Yy]|[Yy][Ee][Ss])$ ]]; then
      echo "Attempting to release port ${current_port}..." >&2
      for pid in ${pids_output}; do
        [[ -n "${pid}" ]] || continue
        if kill -TERM "${pid}" 2>/dev/null; then
          echo "Stopped PID ${pid}." >&2
        else
          echo "Error: failed to stop PID ${pid} on port ${current_port}. Choose another port or rerun with permission to stop that process." >&2
          exit 1
        fi
      done
      sleep 1
      remaining_pids_output="$(get_listening_pids "${current_port}")"
      if [[ -z "${remaining_pids_output}" ]]; then
        echo "Port check: ${current_port} is now free and will be used." >&2
        printf '%s\n' "${current_port}"
        return 0
      fi
      echo "Warning: port ${current_port} is still in use after attempting to stop the listener." >&2
    elif [[ "${release_answer}" =~ ^([Nn]|[Nn][Oo])$ ]]; then
      echo "Input guide:" >&2
      echo "  <port number> : try another port" >&2
      echo "  no / NO / N   : cancel startup" >&2
      echo "  no input for ${PORT_PROMPT_TIMEOUT_SECONDS} seconds : automatically switch to a free port" >&2
      if ! IFS= read -r -t "${PORT_PROMPT_TIMEOUT_SECONDS}" -p "Enter another port number to use, or no/NO/N to exit: " next_answer; then
        echo >&2
        echo "Warning: no input received within ${PORT_PROMPT_TIMEOUT_SECONDS} seconds." >&2
        auto_port="$(find_free_port "${current_port}")"
        echo "Port selection: automatically switching to free port ${auto_port}." >&2
        printf '%s\n' "${auto_port}"
        return 0
      fi
      if [[ "${next_answer}" =~ ^([Nn]|[Nn][Oo])$ ]]; then
        echo "Startup cancelled because port ${current_port} is occupied." >&2
        exit 1
      fi
      if [[ ! "${next_answer}" =~ ^[0-9]+$ ]] || (( next_answer < 1 || next_answer > 65535 )); then
        echo "Warning: invalid port value '${next_answer}'. Enter a number between 1 and 65535, or no to exit." >&2
        continue
      fi
      echo "Port selection: will retry with port ${next_answer}." >&2
      current_port="${next_answer}"
    else
      echo "Warning: unrecognized input '${release_answer}'. Please answer yes/Yes/Y or no/NO/N." >&2
    fi
  done
}

write_runtime_startup_config() {
  local host="$1"
  local port="$2"
  local timeout_seconds="$3"

  cat >"${RUNTIME_ENV_FILE}" <<EOF
# Generated by start-dev.sh
APP_HOST=${host}
APP_PORT=${port}
PORT_PROMPT_TIMEOUT_SECONDS=${timeout_seconds}
EOF
}

get_environment_summary() {
  local interpreter_path="$1"

  if [[ -n "${VIRTUAL_ENV:-}" && -n "${CONDA_PREFIX:-}" ]]; then
    printf 'Virtualenv (%s) on top of Conda (%s)\n' "${VIRTUAL_ENV}" "${CONDA_PREFIX}"
    return 0
  fi
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    printf 'Virtualenv (%s)\n' "${VIRTUAL_ENV}"
    return 0
  fi
  if [[ -n "${CONDA_PREFIX:-}" ]]; then
    printf 'Conda (%s)\n' "${CONDA_PREFIX}"
    return 0
  fi
  if [[ "${USE_ACTIVATED_PYTHON}" == "true" ]]; then
    printf 'Active Python (%s)\n' "${interpreter_path}"
    return 0
  fi
  printf '.venv fallback (%s)\n' "${VENV_DIR}"
}

show_startup_summary() {
  local mode="$1"
  local backend_url="$2"
  local interpreter_path="$3"
  local bootstrap_mode="$4"

  echo
  echo "Startup summary"
  echo "  Mode: ${mode}"
  echo "  Environment: $(get_environment_summary "${interpreter_path}")"
  echo "  Python executable: ${interpreter_path}"
  echo "  Backend URL: ${backend_url}"
  echo "  Runtime config: ${RUNTIME_ENV_FILE}"
  echo "  Bootstrap mode: ${bootstrap_mode}"
  echo "  Port prompt timeout: ${PORT_PROMPT_TIMEOUT_SECONDS}s"
  echo "  Desktop enabled: ${ENABLE_DESKTOP}"
  echo
}

for arg in "$@"; do
  case "${arg}" in
    --desktop)
      ENABLE_DESKTOP="true"
      ;;
    --skip-bootstrap)
      SKIP_BOOTSTRAP="true"
      ;;
    --skip-desktop-bootstrap)
      SKIP_DESKTOP_BOOTSTRAP="true"
      ;;
    --force-bootstrap)
      FORCE_BOOTSTRAP="true"
      ;;
    *)
      echo "Error: unsupported argument '${arg}'" >&2
      echo "Supported arguments: --desktop --skip-bootstrap --skip-desktop-bootstrap --force-bootstrap" >&2
      exit 1
      ;;
  esac
done

PORT_PROMPT_TIMEOUT_SECONDS="$(get_int_setting_value "PORT_PROMPT_TIMEOUT_SECONDS" "${ENV_FILE}" 15)"
APP_HOST="${APP_HOST:-$(read_dotenv_value "APP_HOST" "${ENV_FILE}" || true)}"
APP_PORT="$(get_port_setting_value "APP_PORT" "${ENV_FILE}" 8120)"
APP_HOST="${APP_HOST:-127.0.0.1}"
case "${APP_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *)
    echo "Error: Shape Studio is local-only. APP_HOST must be 127.0.0.1, localhost, or ::1." >&2
    exit 1
    ;;
esac
APP_HOST="127.0.0.1"

USE_ACTIVATED_PYTHON="false"
if [[ "${USE_ACTIVE_PYTHON}" == "true" ]] || test_virtualenv_active || test_conda_environment_active; then
  USE_ACTIVATED_PYTHON="true"
fi

BOOTSTRAP_PYTHON="${PYTHON_BIN}"
if [[ "${USE_ACTIVATED_PYTHON}" == "true" ]]; then
  BOOTSTRAP_PYTHON="$(get_python_executable_path "${PYTHON_BIN}")"
  RESOLVED_PYTHON="${BOOTSTRAP_PYTHON}"
else
  RESOLVED_PYTHON="${VENV_DIR}/bin/python"
fi

BOOTSTRAP_MODE="if-needed"
if [[ "${SKIP_BOOTSTRAP}" == "true" ]]; then
  BOOTSTRAP_MODE="skipped"
elif [[ "${FORCE_BOOTSTRAP}" == "true" ]]; then
  BOOTSTRAP_MODE="always"
fi

echo "Project root: ${PROJECT_ROOT}"
APP_PORT="$(resolve_listen_port_interactive "${APP_PORT}")"
FRONTEND_URL="http://${APP_HOST}:${APP_PORT}/"
echo "Development URL: ${FRONTEND_URL}"
if [[ "${ENABLE_DESKTOP}" == "true" ]]; then
  STARTUP_MODE="web + desktop"
else
  STARTUP_MODE="web only"
fi
show_startup_summary "${STARTUP_MODE}" "${FRONTEND_URL%/}" "${RESOLVED_PYTHON}" "${BOOTSTRAP_MODE}"

if [[ "${SKIP_BOOTSTRAP}" != "true" ]]; then
  echo "Running backend bootstrap..."
  BOOTSTRAP_IF_NEEDED="true"
  if [[ "${FORCE_BOOTSTRAP}" == "true" ]]; then
    BOOTSTRAP_IF_NEEDED="false"
  fi
  INSTALL_DEV_DEPENDENCIES=true \
  USE_ACTIVE_PYTHON="${USE_ACTIVE_PYTHON}" \
  PYTHON_BIN="${BOOTSTRAP_PYTHON}" \
  VENV_DIR="${VENV_DIR}" \
  BOOTSTRAP_IF_NEEDED="${BOOTSTRAP_IF_NEEDED}" \
  "${QUICK_START_DIR}/bootstrap.sh"
fi

if [[ "${USE_ACTIVATED_PYTHON}" == "false" ]]; then
  if [[ ! -x "${RESOLVED_PYTHON}" ]]; then
    echo "Error: virtualenv Python not found at ${RESOLVED_PYTHON}. Run bootstrap first, or activate an environment and rerun with USE_ACTIVE_PYTHON=true." >&2
    exit 1
  fi
  RESOLVED_PYTHON="$(get_python_executable_path "${RESOLVED_PYTHON}")"
fi

write_runtime_startup_config "${APP_HOST}" "${APP_PORT}" "${PORT_PROMPT_TIMEOUT_SECONDS}"

if [[ "${ENABLE_DESKTOP}" == "true" ]]; then
  if [[ "${SKIP_DESKTOP_BOOTSTRAP}" != "true" ]]; then
    echo "Running desktop bootstrap..."
    "${DESKTOP_DIR}/bootstrap.sh"
  fi

  echo "Starting API in background..."
  APP_HOST="${APP_HOST}" \
  APP_PORT="${APP_PORT}" \
  PORT_PROMPT_TIMEOUT_SECONDS="${PORT_PROMPT_TIMEOUT_SECONDS}" \
  SKIP_PORT_RESOLUTION_PROMPT=true \
  STARTUP_CHILD_MODE=true \
  PYTHON_BIN="${RESOLVED_PYTHON}" \
  "${QUICK_START_DIR}/start-api.sh" --reload &
  API_PID=$!
  trap 'kill "${API_PID}" >/dev/null 2>&1 || true' EXIT
  echo "API process started with PID ${API_PID}"

  export RASTER_SVG_FRONTEND_URL="${FRONTEND_URL}"
  "${DESKTOP_DIR}/start-desktop.sh" --skip-bootstrap
else
  export APP_HOST
  export APP_PORT
  export PORT_PROMPT_TIMEOUT_SECONDS
  export SKIP_PORT_RESOLUTION_PROMPT=true
  export STARTUP_CHILD_MODE=true
  export PYTHON_BIN="${RESOLVED_PYTHON}"
  exec "${QUICK_START_DIR}/start-api.sh" --reload
fi
