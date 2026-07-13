# Shape Studio

Shape Studio is a desktop/web application prototype for converting raster images into editable SVG. This README is the main project entrypoint: use it to understand what the project does, then follow the link that matches your role.

The current project has a working Windows installer loop: product users can download the Windows installer from the repository's Releases page, install the app without a developer environment, and later update by running a newer release installer. User data is preserved by default during updates.

## Quick Navigation

| Your Role | Read This | What You Will Do |
| --- | --- | --- |
| Product user on Windows | "How Product Users Use It" below | Download the Windows installer from the repository's Releases page, install the app, configure API settings, upload images, update, or uninstall |
| Product user on macOS/Linux | [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) | Start the backend service from source deployment scripts; packaged product installers are not ready yet |
| Developer | [README.developer.md](./README.developer.md) and [docs.development.md](./docs.development.md) | Run the web/desktop development app from source and debug backend/frontend behavior |
| Release maintainer | [packaging/README.packaging.md](./packaging/README.packaging.md) and [docs.installer.md](./docs.installer.md) | Build versioned installers and release updates that overwrite older installs |
| Desktop shell debugging | [desktop/README.desktop.md](./desktop/README.desktop.md) | Debug Electron startup, URL resolution, and desktop-specific issues |
| Source-bundle deployment | [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) | Create a source deployment bundle, move it to another machine, and start the service |

## Project Overview

The project converts raster images into SVG structures that are easier to edit, reuse, and inspect.

Typical flow:

```text
upload a raster image
-> model recognizes objects, regions, and geometric relationships
-> backend creates structured conversion results
-> frontend shows preview, process information, and SVG artifacts
-> user exports or continues editing the SVG
```

Current application pieces:

- FastAPI backend
- Web frontend
- Electron desktop shell
- Windows installer distributed through the repository's Releases page

## How Product Users Use It

Windows product users do not need Python, Node.js, or a developer environment. macOS and Linux do not yet have a packaged product-user installer in the current project state; those platforms still use the backend startup flow described in [quick-start/README.quick-start.md](./quick-start/README.quick-start.md).

### Windows: First Install

Open the repository's Releases page, download the latest Windows installer, and double-click it. For a hosted Git repository, this is usually:

```text
https://github.com/<owner>/<repo>/releases
```

Download the file whose name looks like:

```text
Shape Studio Setup <version>.exe
```

You can choose an install directory during setup, or keep the default directory.

After installation, open:

```text
Shape Studio
```

from the Start Menu or desktop shortcut.

### Windows: Basic Usage

1. Open Shape Studio.
2. Fill in the minimum API settings in the app UI: API Key, Base URL, API Provider, API Format, Coordinator Model, and Worker Model.
3. Upload the image you want to convert.
4. Start conversion.
5. Review the generated result, logs, and SVG artifacts.

Minimum settings most users should care about:

| Setting | What To Put |
| --- | --- |
| API Key | Secret key for your model provider |
| Base URL | OpenAI-compatible endpoint, usually ending in `/v1` |
| API Provider | Keep `openai_compatible` unless the code adds another provider |
| API Format | Use `openai_chat_completions` for OpenAI-compatible chat APIs, or `openai_responses` when your endpoint supports the Responses API |
| Coordinator Model | Main planning/conversion model name supported by your endpoint |
| Worker Model | Worker/subtask model name supported by your endpoint; it can be the same as the coordinator model |

The installed Windows app starts its bundled backend automatically. Windows users do not need to open a terminal or manually run a service.

### Windows: Update To A New Version

If an older Windows version is already installed:

1. Close Shape Studio if it is running.
2. Download the latest Windows installer from the repository's Releases page.
3. Double-click the new installer.
4. Finish the installer wizard.
5. Reopen the app.

The new installer replaces old program files. User configuration, API settings, generated results, and logs are preserved by default.

### Windows: Uninstall

Uninstall from Windows Settings or the Start Menu:

```text
Windows Settings -> Apps -> Installed apps -> Shape Studio
```

During interactive uninstall, the uninstaller asks whether to remove user data. Keeping user data removes only program files. Removing user data also deletes saved settings, generated results, and logs.

### Windows: User Data Location

On Windows, user data is usually stored under:

```text
%APPDATA%\Shape Studio\
```

Common contents:

```text
.frontend_runtime_overrides.json
artifacts/runs/
logs/backend.log
```

If the app fails to open, check:

```text
%APPDATA%\Shape Studio\logs\backend.log
```

### macOS/Linux: Current User Path

macOS and Linux users currently need to run the backend service from the project/deployment scripts instead of installing a packaged desktop app from the repository's Releases page.

Use:

- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) for deployment-style backend startup
- [README.developer.md](./README.developer.md) for source-based development startup

After the backend starts, open the web UI in a browser, usually:

```text
http://127.0.0.1:8120/
```

## How Developers Use It

Developers can run the web app or desktop development app from source. See:

- [README.developer.md](./README.developer.md)
- [docs.development.md](./docs.development.md)

Quickly start the web development app:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

macOS/Linux:

```bash
chmod +x start-dev.sh
./start-dev.sh
```

The frontend is usually available at:

```text
http://127.0.0.1:8120/
```

Quickly start the desktop development app:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

macOS/Linux:

```bash
./start-dev.sh --desktop
```

Development API settings live in the project-root `.env`. If `.env` does not exist, the startup scripts create it from `.env.example`.

At minimum, review:

```env
API_KEY=your-real-api-key
BASE_URL=https://your-openai-compatible-endpoint.example/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_chat_completions
AGENT_MODEL=your-coordinator-model
SUBAGENT_MODEL=your-worker-model
```

Without real API settings, the frontend can still open, but actual model-backed conversion will fail.

## Build Installers

Windows installers are generated by scripts under `packaging/`. See:

- [packaging/README.packaging.md](./packaging/README.packaging.md)
- [docs.installer.md](./docs.installer.md)

Build an installer for the current version:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Build a release installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

If Python backend dependencies changed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -RecreatePackageVenv -SkipNpmInstall
```

Output:

```text
dist/installers/
```

## Platform Status

Windows:

- Minimal installer loop is complete
- Custom install directory is supported
- Uninstall is supported
- Uninstall can optionally remove user data
- New installers can overwrite older installations

macOS/Linux:

- Development startup scripts exist
- Electron config already includes `dmg`, `AppImage`, and `deb` targets
- Product-user installers are not ready yet; users should start the backend service and use the browser UI
- Production desktop installers still need to be built, signed, tested, and released on their target OS

## Documentation Index

All project-owned README files except this main README use semantic suffixes:

- [README.developer.md](./README.developer.md): developer entrypoint
- [packaging/README.packaging.md](./packaging/README.packaging.md): installer packaging, release builds, overwrite updates, and dependency-size notes
- [desktop/README.desktop.md](./desktop/README.desktop.md): Electron desktop shell notes
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md): source-bundle migration, deployment, and target-machine bootstrap

Other detailed documents:

- [docs.development.md](./docs.development.md): detailed development environment, startup modes, and troubleshooting
- [docs.installer.md](./docs.installer.md): installer implementation and installed-mode behavior

Directory naming:

- `quick-start/`: source-bundle deployment and migration scripts
- `packaging/`: installer/release build scripts
- `desktop/`: Electron shell scripts and desktop assets

## Recommended Reading Paths

Product users:

1. Read "How Product Users Use It" in this README.
2. On Windows, download the latest installer from the repository's Releases page.
3. On macOS/Linux, follow the backend startup path in [quick-start/README.quick-start.md](./quick-start/README.quick-start.md).
4. Open the app or browser UI and fill API settings.

Developers:

1. Read [README.developer.md](./README.developer.md).
2. Then read [docs.development.md](./docs.development.md).
3. Start the development environment with the `start-dev` scripts.

Release maintainers:

1. Read [packaging/README.packaging.md](./packaging/README.packaging.md).
2. Build a versioned installer with `build-release-windows.ps1`.
3. Release the new installer so users can overwrite-update their existing install.
