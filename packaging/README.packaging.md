# Installer Packaging README

This document is the authoritative guide for installer packaging, release builds, installed-app behavior, overwrite updates, uninstall behavior, dependency-size notes, and packaging troubleshooting.

This directory contains the installer packaging flow for building desktop release artifacts. Windows users can install the app by downloading the Windows installer from the repository's Releases page and double-clicking it. Target Windows users do not need Python, Node.js, Conda, or a terminal to start the backend service manually.

The current packaging approach is:

```text
Electron desktop shell
+ FastAPI backend bundled by PyInstaller onedir
+ electron-builder system installers
```

Important platform rule:

```text
Build the Windows installer on Windows.
Build the macOS package on macOS.
```

This matters because the project includes a PyInstaller-bundled Python backend. PyInstaller is generally not a cross-platform cross-compiler, so the Windows backend should be built on Windows and the macOS backend should be built on macOS.

## Directory Contents

```text
packaging/
- README.packaging.md
- prepare-package-venv.ps1
- build-backend.ps1
- build-desktop.ps1
- build-windows-installer.ps1
- build-release-windows.ps1
- validate-version.sh
- set-version.sh
- prepare-package-venv.sh
- build-backend-macos.sh
- build-desktop-macos.sh
- build-release-macos.sh
- set-version.ps1
- validate-version.ps1
- analyze-package-deps.ps1
- generate-icon.py
```

File roles:

- `prepare-package-venv.ps1`: creates the clean Windows packaging environment `.venv_package` with runtime dependencies and PyInstaller only.
- `build-backend.ps1`: builds the Python/FastAPI backend into `dist/backend/raster-svg-api/` on Windows.
- `build-desktop.ps1`: runs `electron-builder` to create the Windows installer.
- `build-windows-installer.ps1`: full Windows build entrypoint; validates version metadata, builds the backend, then builds the desktop installer.
- `build-release-windows.ps1`: Windows release build entrypoint; synchronizes version metadata first, then creates a versioned installer.
- `validate-version.sh`: macOS/Linux-friendly version metadata validation.
- `set-version.sh`: synchronizes version metadata from macOS/Linux shells.
- `prepare-package-venv.sh`: creates `.venv_package` for macOS packaging.
- `build-backend-macos.sh`: builds the macOS backend executable with PyInstaller.
- `build-desktop-macos.sh`: builds the macOS Electron DMG after the backend has been bundled.
- `build-release-macos.sh`: macOS release build entrypoint; synchronizes version metadata, builds the backend, then builds the DMG.
- `set-version.ps1`: updates versions in `pyproject.toml`, `src/deepagents_template/version.py`, `desktop/package.json`, and `desktop/package-lock.json`.
- `validate-version.ps1`: checks version consistency and ensures `appId` and `productName` were not accidentally changed.
- `analyze-package-deps.ps1`: reports the largest packages in `.venv_package`.
- `generate-icon.py`: generates app icon assets.

Windows has complete `.ps1` scripts. macOS now has Bash packaging scripts for developers who need to build a DMG on a Mac. There is still no supported macOS/Linux product-user installer release path yet; for ordinary macOS/Linux users, use the source-bundle backend startup flow in `quick-start/README.quick-start.md`.

The older root-level `docs.installer.md` file is now only an archived compatibility note that points here.

## Installed App Startup Model

After installation, app startup works like this:

```text
user opens Shape Studio
-> Electron finds a free local port
-> Electron starts the bundled backend raster-svg-api
-> Electron waits for /health
-> Electron opens /static/desktop.html
```

Windows backend filename:

```text
raster-svg-api.exe
```

macOS/Linux backend filename:

```text
raster-svg-api
```

`desktop/main.js` chooses the backend filename based on `process.platform`.

## Build On Windows

Windows packaging uses PowerShell scripts.

### First Build

Run from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1
```

This command automatically:

1. prepares `.venv_package`
2. builds the backend
3. installs or checks Electron packaging dependencies
4. creates the Windows installer

To recreate the clean `.venv_package`:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -RecreatePackageVenv
```

To skip `npm install` when `desktop/node_modules` is already current:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Generic optimized Windows build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -Python python -RecreatePackageVenv -SkipNpmInstall
```

### Release A New Windows Version

For real releases, prefer `build-release-windows.ps1`. Do not manually edit version numbers in multiple files.

For example, to release a new version:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

If Python backend dependencies changed, recreate the clean packaging environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -RecreatePackageVenv -SkipNpmInstall
```

The release script does three things:

1. calls `set-version.ps1` to synchronize version metadata
2. calls `validate-version.ps1` to validate version and app identity
3. builds the versioned Windows installer under `dist/installers/`

Windows outputs:

```text
dist/backend/raster-svg-api/raster-svg-api.exe
dist/installers/
dist/installers/win-unpacked/
```

Current verified Windows installer size is about 156 MB.

## Build On macOS

macOS packages must be built on a Mac. Do not build the macOS package directly on Windows.

Important current status: macOS/Linux do not yet have supported product-user installers in this project. The notes below are for developer-side packaging experiments and future release work. macOS/Linux source users should start the backend and launch the Electron desktop shell using the root `start-dev` entrypoint. The browser UI is an early development/diagnostic surface and is not the preferred user experience.

`desktop/package.json` already contains the macOS DMG target:

```json
"mac": {
  "target": [
    "dmg"
  ]
}
```

Use the macOS release script for the normal developer packaging flow. The manual commands below are kept as troubleshooting references.

### Recommended macOS Release Build

Run from the project root on macOS:

```bash
chmod +x packaging/*.sh
./packaging/build-release-macos.sh --version <new-version> --skip-npm-install
```

If Python backend dependencies changed, recreate the clean packaging environment:

```bash
./packaging/build-release-macos.sh --version <new-version> --recreate-package-venv --skip-npm-install
```

If `desktop/node_modules` is missing or Electron dependencies changed, omit `--skip-npm-install`:

```bash
./packaging/build-release-macos.sh --version <new-version> --recreate-package-venv
```

The script does five things:

1. updates versions in `pyproject.toml`, `src/deepagents_template/version.py`, `desktop/package.json`, and `desktop/package-lock.json`
2. validates version metadata and stable app identity
3. prepares `.venv_package` unless `--skip-package-venv` is used
4. builds the macOS backend with PyInstaller
5. runs `electron-builder` to create the DMG

macOS outputs are written under:

```text
dist/backend/
dist/installers/
dist/installers/mac/
```

### macOS Step-by-step Scripts

Prepare only the packaging venv:

```bash
./packaging/prepare-package-venv.sh --recreate
```

Build only the macOS backend:

```bash
./packaging/build-backend-macos.sh --python ./.venv_package/bin/python
```

Build only the macOS desktop DMG:

```bash
./packaging/build-desktop-macos.sh --skip-npm-install
```

Validate version metadata:

```bash
./packaging/validate-version.sh
```

Set a version without building:

```bash
./packaging/set-version.sh --version <new-version>
```

### Manual macOS Fallback

Use this only when debugging the scripted flow.

#### 1. Prepare Python Packaging Environment

Run from the project root:

```bash
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
```

To recreate from a clean environment:

```bash
rm -rf .venv_package
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
```

#### 2. Build The macOS Backend

Run from the project root:

```bash
./.venv_package/bin/python -m PyInstaller \
  --noconfirm \
  --clean \
  --name raster-svg-api \
  --onedir \
  --paths src \
  --add-data "src/deepagents_template/static:deepagents_template/static" \
  --distpath dist/backend \
  --workpath dist/pyinstaller-work \
  --specpath dist/pyinstaller-spec \
  src/deepagents_template/desktop_server.py
```

Note the `--add-data` separator difference:

```text
Windows: src/deepagents_template/static;deepagents_template/static
macOS:   src/deepagents_template/static:deepagents_template/static
```

The macOS backend output is usually:

```text
dist/backend/raster-svg-api/raster-svg-api
```

Ensure the backend file is executable:

```bash
chmod +x dist/backend/raster-svg-api/raster-svg-api
```

#### 3. Build The macOS DMG

Install Electron packaging dependencies:

```bash
cd desktop
npm install
```

If `desktop/node_modules` already exists and Electron/Node dependencies have not changed, you can skip `npm install`.

Build the DMG:

```bash
npm run dist -- --mac dmg
```

macOS outputs are usually under:

```text
dist/installers/
dist/installers/mac/
```

### 4. Current macOS User Path

Do not treat the experimental `.dmg` as the current supported user path. For now, macOS users should start the backend and launch the Electron desktop shell through the root development entrypoint. Use the browser UI only for development diagnostics or when Electron cannot be started:

```text
http://127.0.0.1:8120/
```

See `quick-start/README.quick-start.md` for source-bundle backend startup.

### 5. macOS Work Needed Before Public Release

Unsigned DMGs are acceptable for internal testing. Before distributing to external users, add:

- `desktop/assets/icon.icns`
- Apple Developer ID code signing
- notarization
- DMG signing
- Apple Silicon / Intel architecture strategy: `arm64`, `x64`, or `universal`
- verification of the generated DMG on clean Intel and Apple Silicon Macs

## Overwrite Update Behavior

Windows currently uses the simplest reliable update path: the new installer downloaded from the repository's Releases page overwrites the old installation.

Developer steps:

1. choose the new release version
2. build the new Windows installer
3. attach the installer to the project release

User steps:

1. close Shape Studio if it is running
2. download the latest Windows installer from the repository's Releases page
3. double-click the new installer
4. finish the installer wizard
5. reopen the app from the Start Menu or desktop shortcut

During overwrite install, the application directory is replaced by the new version. User configuration, API settings, run outputs, and logs are preserved by default.

macOS/Linux do not currently have a supported product-user installer/update path. A productionized desktop update path can later use electron-updater or Sparkle-style auto updates.

Do not change these fields during ordinary version upgrades:

- `desktop/package.json` -> `build.appId`
- `desktop/package.json` -> `build.productName`

These fields determine whether the OS treats the new build as the same app. Current values should remain:

```text
appId: com.local.shapestudio
productName: Shape Studio
```

`validate-version.ps1` checks these fields before Windows builds, preventing accidental identity changes.

To set a version without building:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\set-version.ps1 -Version <new-version>
```

To validate version metadata only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\validate-version.ps1
```

## User Data Locations

Installed apps do not write configuration and run outputs back into the project directory.

Windows usually stores user data under:

```text
%APPDATA%\Shape Studio\
```

macOS usually stores user data under:

```text
~/Library/Application Support/Shape Studio/
```

Contents include:

```text
.frontend_runtime_overrides.json
artifacts/runs/
logs/backend.log
```

If the app fails to open, first check:

```text
logs/backend.log
```

inside the matching user-data directory.

## Uninstall Behavior

Windows uninstall is provided automatically by NSIS:

- Windows Settings -> Apps -> Installed apps
- the Start Menu uninstall shortcut created for `Shape Studio`

During interactive uninstall, the uninstaller asks whether to remove user data. If users choose to remove it, saved settings, generated results, and logs are deleted from AppData. If users choose to keep it, only program files are removed.

macOS/Linux currently use the backend/browser path. If you create an experimental macOS app bundle during development, cleanup is manual. To remove user data on macOS, delete:

```text
~/Library/Application Support/Shape Studio/
```

## Why The Installer Is Large

The installer contains three main parts:

```text
Electron/Chromium runtime
+ Python interpreter and backend dependencies
+ project frontend static assets
```

Electron includes Chromium and Node.js, so even an empty Electron app is relatively large.

The backend currently uses PyInstaller `onedir`, which outputs a backend directory instead of a single self-extracting executable. This is usually better for desktop apps:

- faster startup
- easier missing-dependency debugging
- acceptable installer size after compression

## Dependency Size Analysis

On Windows, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\analyze-package-deps.ps1
```

The report is written to:

```text
dist/dependency-size-report.md
```

`.venv_package` no longer installs LangChain-related dependencies by default. The installed app uses the direct OpenAI SDK based multimodal pipeline, so these packages are optional:

```text
deepagents
langchain
langgraph
langchain-openai
anthropic
google-genai
```

Install them only if you revive the legacy agent / LangChain coordinator modules:

```powershell
.\.venv_package\Scripts\python.exe -m pip install -e ".[agent]"
```

macOS equivalent:

```bash
./.venv_package/bin/python -m pip install -e ".[agent]"
```

## Icon

The app icon is generated from a shapes concept: raster pixel blocks gradually transition into shapes/vector path nodes.

Current Windows assets:

```text
desktop/assets/icon.ico
desktop/assets/icon.png
```

Windows builds keep executable resource editing enabled so the installed `Shape Studio.exe`, Start Menu entry, desktop shortcut, and taskbar can use the custom icon. If `winCodeSign` extraction reports that symbolic links cannot be created, enable Windows Developer Mode or run the build from an administrator terminal with symbolic-link permission. Do not disable `signAndEditExecutable` as a workaround, because that leaves the main executable with the default Electron icon.

For macOS public release, add:

```text
desktop/assets/icon.icns
```

Regenerate current icon assets:

```powershell
.\.venv_package\Scripts\python.exe .\packaging\generate-icon.py
```

macOS equivalent:

```bash
./.venv_package/bin/python ./packaging/generate-icon.py
```

## Common Issues

### 1. PowerShell blocks npm

If running `npm` directly on Windows reports an execution policy error, the scripts already use `npm.cmd` to avoid it.

### 2. electron-builder download fails

On first build, electron-builder downloads Electron and NSIS/DMG-related components. If the network is unstable, rerun the command.

If extraction of `winCodeSign` fails with `Cannot create symbolic link` or `A required privilege is not held by the client`, enable Windows Developer Mode and rerun the build, or use an administrator terminal. This permission is required for the cached tool archive even when the application itself is not code-signed.

### 3. PyInstaller reports a permission error while scanning user Python directories

Prefer building with the clean `.venv_package`; do not use a global Python environment.

If you see an error like:

```text
PermissionError: [WinError 5] ... AppData\Roaming\Python\Python312\site-packages
```

PyInstaller dependency scanning hit a system permission boundary. Rerun the release command in a normal local PowerShell session, or allow elevated execution and rebuild.

### 4. macOS app cannot start the backend

First check:

```text
dist/backend/raster-svg-api/raster-svg-api
```

Confirm it is executable:

```bash
chmod +x dist/backend/raster-svg-api/raster-svg-api
```

Also confirm that `dist/installers/mac/Shape Studio.app/Contents/Resources/backend/` contains the backend directory.

### 5. Installer is not code signed

The current MVP is suitable for internal testing. Before public release, add:

- Windows code signing certificate
- macOS signing and notarization
- update source
- release notes and checksum verification

## Recommended Daily Commands

Windows: rebuild current version locally:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Windows: release a new version:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

Windows: release a new version after dependency changes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -RecreatePackageVenv -SkipNpmInstall
```

macOS minimum packaging loop:

```bash
python3 -m venv .venv_package
./.venv_package/bin/python -m pip install --upgrade pip
./.venv_package/bin/python -m pip install -e .
./.venv_package/bin/python -m pip install pyinstaller
./.venv_package/bin/python -m PyInstaller --noconfirm --clean --name raster-svg-api --onedir --paths src --add-data "src/deepagents_template/static:deepagents_template/static" --distpath dist/backend --workpath dist/pyinstaller-work --specpath dist/pyinstaller-spec src/deepagents_template/desktop_server.py
chmod +x dist/backend/raster-svg-api/raster-svg-api
cd desktop
npm install
npm run dist -- --mac dmg
```

Related documents:

- [../README.md](../README.md): product-facing install/update basics
- [../README.developer.md](../README.developer.md): developer entrypoint
- [../RELEASE_NOTES.md](../RELEASE_NOTES.md): version-specific artifacts, checksums, and verification
- [../architecture-summary/05-deployment-and-release.md](../architecture-summary/05-deployment-and-release.md): deployment and release architecture
