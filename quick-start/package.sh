#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_NAME="${PROJECT_NAME:-$(basename "${PROJECT_ROOT}")}"
TIMESTAMP="${TIMESTAMP:-$(date +"%Y%m%d-%H%M%S")}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${PROJECT_ROOT}/dist/deploy-packages}"
PACKAGE_NAME="${PACKAGE_NAME:-${PROJECT_NAME}-deploy-${TIMESTAMP}}"
STAGE_DIR="${OUTPUT_ROOT}/${PACKAGE_NAME}"
ARCHIVE_PATH="${OUTPUT_ROOT}/${PACKAGE_NAME}.tar.gz"
INCLUDE_ENV="${INCLUDE_ENV:-false}"
INCLUDE_ARTIFACTS="${INCLUDE_ARTIFACTS:-false}"
INCLUDE_RUNTIME_OVERRIDES="${INCLUDE_RUNTIME_OVERRIDES:-false}"

copy_path() {
  local source_path="$1"
  local target_path="$2"

  if [[ ! -e "${source_path}" ]]; then
    echo "Skipping missing path: ${source_path}"
    return 0
  fi

  mkdir -p "$(dirname "${target_path}")"
  cp -R "${source_path}" "${target_path}"
}

copy_desktop_source() {
  copy_path "${PROJECT_ROOT}/desktop/assets/icon.png" "${STAGE_DIR}/desktop/assets/icon.png"
  copy_path "${PROJECT_ROOT}/desktop/assets/icon.ico" "${STAGE_DIR}/desktop/assets/icon.ico"
  copy_path "${PROJECT_ROOT}/desktop/bootstrap.bat" "${STAGE_DIR}/desktop/bootstrap.bat"
  copy_path "${PROJECT_ROOT}/desktop/bootstrap.ps1" "${STAGE_DIR}/desktop/bootstrap.ps1"
  copy_path "${PROJECT_ROOT}/desktop/bootstrap.sh" "${STAGE_DIR}/desktop/bootstrap.sh"
  copy_path "${PROJECT_ROOT}/desktop/main.js" "${STAGE_DIR}/desktop/main.js"
  copy_path "${PROJECT_ROOT}/desktop/package-lock.json" "${STAGE_DIR}/desktop/package-lock.json"
  copy_path "${PROJECT_ROOT}/desktop/package.json" "${STAGE_DIR}/desktop/package.json"
  copy_path "${PROJECT_ROOT}/desktop/preload.js" "${STAGE_DIR}/desktop/preload.js"
  copy_path "${PROJECT_ROOT}/desktop/README.desktop.md" "${STAGE_DIR}/desktop/README.desktop.md"
  copy_path "${PROJECT_ROOT}/desktop/start-desktop.bat" "${STAGE_DIR}/desktop/start-desktop.bat"
  copy_path "${PROJECT_ROOT}/desktop/start-desktop.ps1" "${STAGE_DIR}/desktop/start-desktop.ps1"
  copy_path "${PROJECT_ROOT}/desktop/start-desktop.sh" "${STAGE_DIR}/desktop/start-desktop.sh"
}

remove_packaging_caches() {
  find "${STAGE_DIR}" -type d \
    \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.mypy_cache' \) \
    -prune -exec rm -rf {} +
  find "${STAGE_DIR}" -type f \
    \( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyd' -o -name '*.log' \) \
    -delete
}

if [[ -e "${STAGE_DIR}" || -e "${ARCHIVE_PATH}" ]]; then
  echo "Error: target package already exists." >&2
  echo "Stage dir: ${STAGE_DIR}" >&2
  echo "Archive:   ${ARCHIVE_PATH}" >&2
  echo "Tip: rerun later or override TIMESTAMP/PACKAGE_NAME." >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}"
mkdir -p "${STAGE_DIR}"

echo "Project root: ${PROJECT_ROOT}"
echo "Output root:  ${OUTPUT_ROOT}"
echo "Package name: ${PACKAGE_NAME}"

copy_path "${PROJECT_ROOT}/src" "${STAGE_DIR}/src"
copy_desktop_source
copy_path "${PROJECT_ROOT}/quick-start" "${STAGE_DIR}/quick-start"
copy_path "${PROJECT_ROOT}/architecture-summary" "${STAGE_DIR}/architecture-summary"
copy_path "${PROJECT_ROOT}/packaging/README.packaging.md" "${STAGE_DIR}/packaging/README.packaging.md"
copy_path "${PROJECT_ROOT}/pyproject.toml" "${STAGE_DIR}/pyproject.toml"
copy_path "${PROJECT_ROOT}/README.md" "${STAGE_DIR}/README.md"
copy_path "${PROJECT_ROOT}/README.developer.md" "${STAGE_DIR}/README.developer.md"
copy_path "${PROJECT_ROOT}/RELEASE_NOTES.md" "${STAGE_DIR}/RELEASE_NOTES.md"
copy_path "${PROJECT_ROOT}/docs.development.md" "${STAGE_DIR}/docs.development.md"
copy_path "${PROJECT_ROOT}/docs.installer.md" "${STAGE_DIR}/docs.installer.md"
copy_path "${PROJECT_ROOT}/docs.settings-mapping.md" "${STAGE_DIR}/docs.settings-mapping.md"
copy_path "${PROJECT_ROOT}/.env.example" "${STAGE_DIR}/.env.example"
copy_path "${PROJECT_ROOT}/environment.yml" "${STAGE_DIR}/environment.yml"
copy_path "${PROJECT_ROOT}/start-dev.ps1" "${STAGE_DIR}/start-dev.ps1"
copy_path "${PROJECT_ROOT}/start-dev.bat" "${STAGE_DIR}/start-dev.bat"
copy_path "${PROJECT_ROOT}/start-dev.sh" "${STAGE_DIR}/start-dev.sh"
copy_path "${PROJECT_ROOT}/start-service.ps1" "${STAGE_DIR}/start-service.ps1"
copy_path "${PROJECT_ROOT}/start-service.bat" "${STAGE_DIR}/start-service.bat"
copy_path "${PROJECT_ROOT}/stop-dev.ps1" "${STAGE_DIR}/stop-dev.ps1"

if [[ "${INCLUDE_ENV}" == "true" && -f "${PROJECT_ROOT}/.env" ]]; then
  copy_path "${PROJECT_ROOT}/.env" "${STAGE_DIR}/.env"
  echo "Included .env"
else
  echo "Skipped .env"
fi

if [[ "${INCLUDE_ARTIFACTS}" == "true" && -d "${PROJECT_ROOT}/artifacts" ]]; then
  copy_path "${PROJECT_ROOT}/artifacts" "${STAGE_DIR}/artifacts"
  echo "Included artifacts/"
else
  echo "Skipped artifacts/"
fi

if [[ "${INCLUDE_RUNTIME_OVERRIDES}" == "true" && -f "${PROJECT_ROOT}/.frontend_runtime_overrides.json" ]]; then
  copy_path "${PROJECT_ROOT}/.frontend_runtime_overrides.json" "${STAGE_DIR}/.frontend_runtime_overrides.json"
  echo "Included .frontend_runtime_overrides.json"
else
  echo "Skipped .frontend_runtime_overrides.json"
fi

cat > "${STAGE_DIR}/DEPLOY_PACKAGE_INFO.txt" <<EOF
Package: ${PACKAGE_NAME}
Created At: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Project Root: ${PROJECT_ROOT}
Included .env: ${INCLUDE_ENV}
Included artifacts: ${INCLUDE_ARTIFACTS}
Included runtime overrides: ${INCLUDE_RUNTIME_OVERRIDES}

Quick start:
  Windows:
    powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
    cd quick-start
    powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
    powershell -ExecutionPolicy Bypass -File .\start-api.ps1
    powershell -ExecutionPolicy Bypass -File ..\desktop\start-desktop.ps1
  Linux/macOS:
    ./start-dev.sh
    cd quick-start
    chmod +x bootstrap.sh start-api.sh
    ./bootstrap.sh
    ./start-api.sh
    ../desktop/start-desktop.sh
EOF

remove_packaging_caches

tar -czf "${ARCHIVE_PATH}" -C "${OUTPUT_ROOT}" "${PACKAGE_NAME}"

echo "Deployment package created."
echo "Stage directory: ${STAGE_DIR}"
echo "Archive file:    ${ARCHIVE_PATH}"
