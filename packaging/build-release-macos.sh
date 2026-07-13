#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION=""
PYTHON_BIN="${PYTHON_BIN:-python3}"
SKIP_NPM_INSTALL=false
SKIP_PACKAGE_VENV=false
RECREATE_PACKAGE_VENV=false
BUNDLE_MODE="onedir"

usage() {
  cat <<'EOF'
Usage: packaging/build-release-macos.sh --version VERSION [options]

Options:
  --python PYTHON              Python used to create .venv_package. Default: python3
  --skip-npm-install           Skip npm install in desktop/
  --skip-package-venv          Use --python directly instead of preparing .venv_package
  --recreate-package-venv      Recreate .venv_package before packaging
  --bundle-mode onedir|onefile PyInstaller bundle mode. Default: onedir
  --project-root PATH          Project root override

This script must be run on macOS.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --skip-npm-install)
      SKIP_NPM_INSTALL=true
      shift
      ;;
    --skip-package-venv)
      SKIP_PACKAGE_VENV=true
      shift
      ;;
    --recreate-package-venv)
      RECREATE_PACKAGE_VENV=true
      shift
      ;;
    --bundle-mode)
      BUNDLE_MODE="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$(cd "$2" && pwd)"
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

if [[ -z "${VERSION}" ]]; then
  echo "--version is required." >&2
  usage >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

"${SCRIPT_DIR}/set-version.sh" --version "${VERSION}" --project-root "${PROJECT_ROOT}" --python "${PYTHON_BIN}"

BUILD_PYTHON="${PYTHON_BIN}"
if [[ "${SKIP_PACKAGE_VENV}" != "true" ]]; then
  PREPARE_ARGS=(--python "${PYTHON_BIN}" --project-root "${PROJECT_ROOT}")
  if [[ "${RECREATE_PACKAGE_VENV}" == "true" ]]; then
    PREPARE_ARGS+=(--recreate)
  fi
  "${SCRIPT_DIR}/prepare-package-venv.sh" "${PREPARE_ARGS[@]}"
  BUILD_PYTHON="${PROJECT_ROOT}/.venv_package/bin/python"
fi

"${SCRIPT_DIR}/build-backend-macos.sh" \
  --python "${BUILD_PYTHON}" \
  --project-root "${PROJECT_ROOT}" \
  --bundle-mode "${BUNDLE_MODE}"

DESKTOP_ARGS=(--project-root "${PROJECT_ROOT}")
if [[ "${SKIP_NPM_INSTALL}" == "true" ]]; then
  DESKTOP_ARGS+=(--skip-npm-install)
fi
"${SCRIPT_DIR}/build-desktop-macos.sh" "${DESKTOP_ARGS[@]}"

PRODUCT_NAME="$(node -e "const fs=require('fs'); const path=require('path'); const root=process.argv[1]; const p=JSON.parse(fs.readFileSync(path.join(root,'desktop','package.json'),'utf8')); console.log(p.build.productName)" "${PROJECT_ROOT}")"
EXPECTED_DMG="${PROJECT_ROOT}/dist/installers/${PRODUCT_NAME} Setup ${VERSION}.dmg"

if [[ -f "${EXPECTED_DMG}" ]]; then
  echo "Release DMG ready: ${EXPECTED_DMG}"
else
  echo "Release build completed. DMG files under dist/installers:"
  find "${PROJECT_ROOT}/dist/installers" -maxdepth 1 -type f -name "*.dmg" -print
fi
