#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: packaging/validate-version.sh [--project-root PATH]

Validates that package versions and stable app identity fields are in sync.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

node - "${PROJECT_ROOT}" <<'NODE'
const fs = require("fs");
const path = require("path");

const root = process.argv[2];
const packagePath = path.join(root, "desktop", "package.json");
const lockPath = path.join(root, "desktop", "package-lock.json");
const pyprojectPath = path.join(root, "pyproject.toml");

const desktopPackage = JSON.parse(fs.readFileSync(packagePath, "utf8"));
const desktopVersion = String(desktopPackage.version || "");
const pyprojectText = fs.readFileSync(pyprojectPath, "utf8");
const pyprojectMatch = pyprojectText.match(/^version\s*=\s*"([^"]+)"/m);

if (!pyprojectMatch) {
  throw new Error("Could not find [project] version in pyproject.toml.");
}

const pyprojectVersion = pyprojectMatch[1];
if (desktopVersion !== pyprojectVersion) {
  throw new Error(`Version mismatch: desktop/package.json=${desktopVersion} pyproject.toml=${pyprojectVersion}`);
}

if (fs.existsSync(lockPath)) {
  const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
  if (String(lock.version || "") !== desktopVersion) {
    throw new Error(`Version mismatch: desktop/package-lock.json=${lock.version} desktop/package.json=${desktopVersion}`);
  }
  if (lock.packages && lock.packages[""] && String(lock.packages[""].version || "") !== desktopVersion) {
    throw new Error(`Version mismatch: desktop/package-lock.json packages[""].version=${lock.packages[""].version} desktop/package.json=${desktopVersion}`);
  }
}

if (desktopPackage.build?.appId !== "com.local.shapestudio") {
  throw new Error(`Unexpected appId '${desktopPackage.build?.appId}'. Keep appId stable for overwrite updates.`);
}

if (desktopPackage.build?.productName !== "Shape Studio") {
  throw new Error(`Unexpected productName '${desktopPackage.build?.productName}'. Keep productName stable for overwrite updates.`);
}

console.log(`Version metadata OK: ${desktopVersion}`);
console.log(`Stable appId: ${desktopPackage.build.appId}`);
console.log(`Stable productName: ${desktopPackage.build.productName}`);
NODE
