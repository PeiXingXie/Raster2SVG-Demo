#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION=""
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage: packaging/set-version.sh --version VERSION [--project-root PATH] [--python PYTHON]

Synchronizes version metadata in:
- pyproject.toml
- src/deepagents_template/version.py
- desktop/package.json
- desktop/package-lock.json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
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

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "Version must look like 0.1.1 or 0.2.0-beta.1. Received: ${VERSION}" >&2
  exit 2
fi

"${PYTHON_BIN}" - "${PROJECT_ROOT}" "${VERSION}" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
version = sys.argv[2]

def replace_once(path: Path, pattern: str, replacement: str, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Failed to update {description}.")
    path.write_text(updated, encoding="utf-8")

package_path = root / "desktop" / "package.json"
lock_path = root / "desktop" / "package-lock.json"
pyproject_path = root / "pyproject.toml"
package_version_path = root / "src" / "deepagents_template" / "version.py"

replace_once(
    package_path,
    r'("version"\s*:\s*")[^"]+(")',
    rf'\g<1>{version}\2',
    "desktop/package.json version",
)
json.loads(package_path.read_text(encoding="utf-8"))

if lock_path.exists():
    replace_once(
        lock_path,
        r'("name"\s*:\s*"shape-studio-desktop-client",\s*\r?\n\s*"version"\s*:\s*")[^"]+(")',
        rf'\g<1>{version}\2',
        "desktop/package-lock.json top-level version",
    )
    replace_once(
        lock_path,
        r'(""\s*:\s*\{\s*\r?\n\s*"name"\s*:\s*"shape-studio-desktop-client",\s*\r?\n\s*"version"\s*:\s*")[^"]+(")',
        rf'\g<1>{version}\2',
        'desktop/package-lock.json packages[""].version',
    )
    json.loads(lock_path.read_text(encoding="utf-8"))

replace_once(
    pyproject_path,
    r'(^version\s*=\s*")[^"]+(")',
    rf'\g<1>{version}\2',
    "pyproject.toml version",
)
replace_once(
    package_version_path,
    r'(^__version__\s*=\s*")[^"]+(")',
    rf'\g<1>{version}\2',
    "src/deepagents_template/version.py version",
)
PY

"${SCRIPT_DIR}/validate-version.sh" --project-root "${PROJECT_ROOT}"
echo "Version set to ${VERSION}"
