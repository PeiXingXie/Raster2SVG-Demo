#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_ROOT="${SCRIPT_DIR}"
PROJECT_ROOT="$(cd "${DESKTOP_ROOT}/.." && pwd)"
NODE_EXE="${NODE_EXE:-}"
NPM_CMD="${NPM_CMD:-}"
VENDOR_NODE_EXE="${DESKTOP_ROOT}/runtime/node/bin/node"
VENDOR_NPM_CMD="${DESKTOP_ROOT}/runtime/node/bin/npm"

resolve_existing_path() {
  for candidate in "$@"; do
    if [[ -n "${candidate}" && -e "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

resolved_node=""
if resolved_node="$(resolve_existing_path "${NODE_EXE}" "${DESKTOP_NODE_EXE:-}" "${VENDOR_NODE_EXE}")"; then
  :
elif command -v node >/dev/null 2>&1; then
  resolved_node="$(command -v node)"
fi

resolved_npm=""
if resolved_npm="$(resolve_existing_path "${NPM_CMD}" "${DESKTOP_NPM_CMD:-}" "${VENDOR_NPM_CMD}")"; then
  :
elif command -v npm >/dev/null 2>&1; then
  resolved_npm="$(command -v npm)"
fi

echo "Desktop root: ${DESKTOP_ROOT}"
echo "Project root: ${PROJECT_ROOT}"
echo "Node runtime: ${resolved_node:-<not found>}"
echo "npm command: ${resolved_npm:-<not found>}"

if [[ ! -f "${DESKTOP_ROOT}/package.json" ]]; then
  echo "Error: desktop/package.json is missing." >&2
  exit 1
fi

if [[ -d "${DESKTOP_ROOT}/node_modules/electron" ]]; then
  echo "Electron dependency already present."
  exit 0
fi

if [[ -z "${resolved_node}" ]]; then
  echo "Error: Node.js runtime not found. Package one under desktop/runtime/node or pass NODE_EXE." >&2
  exit 1
fi

if [[ -z "${resolved_npm}" ]]; then
  echo "Error: npm not found. Package desktop/node_modules ahead of time or provide a runtime with npm." >&2
  exit 1
fi

pushd "${DESKTOP_ROOT}" >/dev/null
NODE_VERSION="$("${resolved_node}" -p 'process.versions.node')"
echo "Detected Node.js: v${NODE_VERSION}"
if ! "${resolved_node}" -e 'const [major] = process.versions.node.split(".").map(Number); process.exit(major >= 20 ? 0 : 1);'; then
  echo "Error: Node.js 20 or newer is required for the desktop shell. Detected version: v${NODE_VERSION}" >&2
  popd >/dev/null
  exit 1
fi
"${resolved_npm}" install --no-fund --no-audit
popd >/dev/null

echo "Desktop bootstrap completed."
