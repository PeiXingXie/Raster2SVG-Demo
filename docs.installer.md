# Windows Installer Guide

This guide explains the Windows installer path for the project. Product users should download the latest Windows installer from the repository's Releases page.

## What Changed

The development flow still works:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

The installer flow adds a packaged desktop mode:

1. PyInstaller builds the FastAPI backend into `dist/backend/raster-svg-api/raster-svg-api.exe`.
2. Electron starts that backend automatically when the app opens.
3. `electron-builder` creates a Windows installer under `dist/installers`.

## Files Added or Changed

- `src/deepagents_template/desktop_server.py`: backend entrypoint for PyInstaller.
- `desktop/main.js`: launches the packaged backend in installed-app mode.
- `desktop/package.json`: adds `electron-builder` installer settings.
- `packaging/build-backend.ps1`: builds the backend executable.
- `packaging/build-desktop.ps1`: builds the Electron installer.
- `packaging/build-windows-installer.ps1`: runs the full Windows MVP build.
- `packaging/prepare-package-venv.ps1`: creates `.venv_package` with runtime-only dependencies.
- `packaging/generate-icon.py`: creates the shape-based app icon assets.
- `packaging/analyze-package-deps.ps1`: reports the largest packages in `.venv_package`.
- `desktop/build/installer.nsh`: adds an uninstall-time user-data cleanup prompt.

## First-Time Setup

Install Python dependencies for the project as usual.

The default Windows build creates a clean package venv automatically:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\prepare-package-venv.ps1
```

That venv lives in `.venv_package` and installs only runtime dependencies plus PyInstaller.

The desktop build also needs Node.js and npm. The packaging script runs:

```powershell
npm install
```

inside `desktop/`, which installs `electron-builder` from `desktop/package.json`.

## Build the Windows Installer

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1
```

For a real release, use the versioned release script instead. It updates all app version metadata,
validates that the app identity is stable, and then builds the installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

If backend dependencies changed, recreate the clean package venv:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -RecreatePackageVenv -SkipNpmInstall
```

If your Python command is different:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -Python py
```

To recreate the dedicated package venv from scratch:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -RecreatePackageVenv
```

If `desktop/node_modules` is already current and you want to skip `npm install`:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Generic optimized build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -Python python -RecreatePackageVenv -SkipNpmInstall
```

## Expected Outputs

Backend executable:

```text
dist/backend/raster-svg-api/raster-svg-api.exe
```

Windows installer:

```text
dist/installers/
```

Current optimized MVP output:

- backend onedir: `dist/backend/raster-svg-api/`
- backend directory size: about 60 MB
- installer size: about 156 MB

Release installers are versioned and written under:

```text
dist/installers/
```

The current MVP disables Windows executable resource editing and code signing to avoid local
symbolic-link permission problems while building `winCodeSign`. The installer and Electron window
are configured to use `desktop/assets/icon.ico`, but embedding that icon into the final `.exe`
requires turning Windows executable resource editing back on later.

The current backend build uses PyInstaller `onedir`. This gives a backend folder instead of one
large self-extracting exe. It usually starts faster and is easier to inspect inside the installed app.

## Icon

The app icon is generated from simple raster-to-vector shapes:

```powershell
.\.venv_package\Scripts\python.exe .\packaging\generate-icon.py
```

Outputs:

```text
desktop/assets/icon.png
desktop/assets/icon.ico
```

## Install and Uninstall Behavior

The Windows installer uses NSIS assistant mode, not one-click mode. During installation, users can
choose the install directory.

## Updating an Existing Install

The update path is intentionally simple: the new Windows installer downloaded from the repository's Releases page overwrites the old installed application.
Users do not need a developer environment, terminal, Python, or Node.js.

For the developer:

1. Choose the new release version.
2. Build the Windows installer with `build-release-windows.ps1`.
3. Attach the installer from `dist/installers/` to the project release.

The recommended command is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

For the user:

1. Close Shape Studio if it is open.
2. Download the latest Windows installer from the repository's Releases page.
3. Double-click the installer.
4. Keep the default install location unless they intentionally want to move the app.
5. Finish the installer and open Shape Studio normally from the Start Menu.

The user's saved settings and generated data are preserved during an update because they live under
the Electron user-data directory, not inside the installation directory.

Do not change these fields between releases unless you intentionally want Windows to treat it as a
different app:

- `desktop/package.json` -> `build.appId`
- `desktop/package.json` -> `build.productName`

The packaging scripts validate those fields before building. They also validate that these version
values stay in sync:

- `pyproject.toml` -> `[project].version`
- `desktop/package.json` -> `version`
- `desktop/package-lock.json` -> top-level `version`
- `desktop/package-lock.json` -> `packages[""].version`

You can run the validation without building:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\validate-version.ps1
```

If you only want to set a version without building:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\set-version.ps1 -Version <new-version>
```

Uninstall is provided automatically by NSIS. Users can uninstall from:

- Windows Settings -> Apps -> Installed apps
- the Start Menu uninstall shortcut created for `Shape Studio`

During interactive uninstall, the uninstaller asks whether to remove user data. If the user chooses
Yes, it removes saved API settings, generated artifacts, and backend logs from AppData. If the user
chooses No, user data is preserved.

Silent uninstall preserves user data by default. The generated uninstaller still supports
`--delete-app-data` for scripted cleanup.

## Dependency Size Analysis

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\analyze-package-deps.ps1
```

The report is written to:

```text
dist/dependency-size-report.md
```

Current largest package/module groups in `.venv_package`:

- `PIL`: about 15.28 MB
- `pip`: about 10 MB
- `openai`: about 8.86 MB
- `setuptools`: about 6.69 MB
- `pydantic_core`: about 5.36 MB
- `PyInstaller`: about 4.06 MB
- `pydantic`: about 3.49 MB

LangChain-related dependencies have been moved out of the default runtime path. The main installed
app uses the direct OpenAI SDK based multimodal pipeline, so `deepagents`, `langchain`, `langgraph`,
`langchain-openai`, `anthropic`, and `google-genai` are not installed into `.venv_package`.

Those packages remain available through the optional Python extra:

```powershell
.\.venv_package\Scripts\python.exe -m pip install -e ".[agent]"
```

Use that extra only if reviving the legacy DeepAgents/LangChain coordinator modules.

## How Installed Mode Works

In development mode, Electron keeps using the existing external backend URL.

In packaged mode, Electron:

1. finds a free local port
2. starts `resources/backend/raster-svg-api/raster-svg-api.exe`
3. passes user-data paths through environment variables
4. waits for `/health`
5. opens `/static/desktop.html`
6. shuts the backend down when the app exits

User configuration and run outputs go under Electron's user-data directory, not the project folder.
