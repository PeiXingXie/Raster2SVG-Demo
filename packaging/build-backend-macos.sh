#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BUNDLE_MODE="onedir"

usage() {
  cat <<'EOF'
Usage: packaging/build-backend-macos.sh [--python PYTHON] [--project-root PATH] [--bundle-mode onedir|onefile]

Builds the macOS backend executable with PyInstaller.
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
    --bundle-mode)
      BUNDLE_MODE="$2"
      shift 2
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

if [[ "${BUNDLE_MODE}" != "onedir" && "${BUNDLE_MODE}" != "onefile" ]]; then
  echo "--bundle-mode must be onedir or onefile." >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS because PyInstaller builds platform-native binaries." >&2
  exit 1
fi

BACKEND_DIST="${PROJECT_ROOT}/dist/backend"
PYINSTALLER_WORK="${PROJECT_ROOT}/dist/pyinstaller-work"
PYINSTALLER_SPEC="${PROJECT_ROOT}/dist/pyinstaller-spec"
ENTRY_POINT="${PROJECT_ROOT}/src/deepagents_template/desktop_server.py"
STATIC_SOURCE="${PROJECT_ROOT}/src/deepagents_template/static"

if [[ ! -f "${ENTRY_POINT}" ]]; then
  echo "Desktop server entrypoint not found: ${ENTRY_POINT}" >&2
  exit 1
fi

"${PYTHON_BIN}" -m PyInstaller --version >/dev/null

mkdir -p "${BACKEND_DIST}" "${PYINSTALLER_WORK}" "${PYINSTALLER_SPEC}"

BUNDLE_FLAG="--onedir"
if [[ "${BUNDLE_MODE}" == "onefile" ]]; then
  BUNDLE_FLAG="--onefile"
fi

PYTHONNOUSERSITE=1 "${PYTHON_BIN}" -m PyInstaller \
  --noconfirm \
  --clean \
  --name raster-svg-api \
  "${BUNDLE_FLAG}" \
  --paths "${PROJECT_ROOT}/src" \
  --add-data "${STATIC_SOURCE}:deepagents_template/static" \
  --distpath "${BACKEND_DIST}" \
  --workpath "${PYINSTALLER_WORK}" \
  --specpath "${PYINSTALLER_SPEC}" \
  "${ENTRY_POINT}"

if [[ "${BUNDLE_MODE}" == "onefile" ]]; then
  BACKEND_EXE="${BACKEND_DIST}/raster-svg-api"
else
  BACKEND_EXE="${BACKEND_DIST}/raster-svg-api/raster-svg-api"
fi

if [[ ! -f "${BACKEND_EXE}" ]]; then
  echo "Expected backend executable was not produced: ${BACKEND_EXE}" >&2
  exit 1
fi

chmod +x "${BACKEND_EXE}"
echo "Backend executable created: ${BACKEND_EXE}"
