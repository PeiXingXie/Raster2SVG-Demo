#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RECREATE=false

usage() {
  cat <<'EOF'
Usage: packaging/prepare-package-venv.sh [--python PYTHON] [--project-root PATH] [--recreate]

Creates .venv_package with runtime dependencies and PyInstaller for macOS packaging.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    --recreate)
      RECREATE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PACKAGE_VENV="${PROJECT_ROOT}/.venv_package"

if [[ "${RECREATE}" == "true" && -d "${PACKAGE_VENV}" ]]; then
  rm -rf "${PACKAGE_VENV}"
fi

if [[ ! -d "${PACKAGE_VENV}" ]]; then
  "${PYTHON_BIN}" -m venv "${PACKAGE_VENV}"
fi

PACKAGE_PYTHON="${PACKAGE_VENV}/bin/python"
"${PACKAGE_PYTHON}" -m pip install --upgrade pip
"${PACKAGE_PYTHON}" -m pip install -e "${PROJECT_ROOT}"
"${PACKAGE_PYTHON}" -m pip install pyinstaller

echo "Package venv ready: ${PACKAGE_VENV}"
