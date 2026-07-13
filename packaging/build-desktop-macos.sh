#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKIP_NPM_INSTALL=false

usage() {
  cat <<'EOF'
Usage: packaging/build-desktop-macos.sh [--project-root PATH] [--skip-npm-install]

Builds the macOS Electron DMG after the backend has been bundled.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    --skip-npm-install)
      SKIP_NPM_INSTALL=true
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

BACKEND_CANDIDATES=(
  "${PROJECT_ROOT}/dist/backend/raster-svg-api/raster-svg-api"
  "${PROJECT_ROOT}/dist/backend/raster-svg-api"
)

BACKEND_EXE=""
for candidate in "${BACKEND_CANDIDATES[@]}"; do
  if [[ -f "${candidate}" ]]; then
    BACKEND_EXE="${candidate}"
    break
  fi
done

if [[ -z "${BACKEND_EXE}" ]]; then
  echo "Packaged backend not found. Build it first." >&2
  printf 'Checked: %s\n' "${BACKEND_CANDIDATES[@]}" >&2
  exit 1
fi

chmod +x "${BACKEND_EXE}"
echo "Packaged backend: ${BACKEND_EXE}"

pushd "${PROJECT_ROOT}/desktop" >/dev/null
if [[ "${SKIP_NPM_INSTALL}" != "true" ]]; then
  npm install
fi
npm run dist -- --mac dmg
popd >/dev/null

echo "Installer output directory: ${PROJECT_ROOT}/dist/installers"
