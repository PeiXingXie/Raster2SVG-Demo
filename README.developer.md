# Shape Studio Developer Guide

This document is the developer entrypoint that used to live in the root `README.md`.

Use it when you want to set up the project from source, run the backend/frontend locally, debug the Electron shell, or build installers.

For the product-facing project overview and documentation index, use [README.md](./README.md).

## Documentation Map

Read the detailed guides only when you need them.

Project documents:

- [docs.development.md](./docs.development.md): full developer manual for Conda or `.venv`, API configuration, automatic startup, manual startup, and troubleshooting
- [packaging/README.packaging.md](./packaging/README.packaging.md): installer packaging, versioned release builds, overwrite-update behavior, and package-size notes
- [docs.installer.md](./docs.installer.md): detailed installer MVP notes and installed-app behavior
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md): source-bundle deployment and migration flow for another machine
- [desktop/README.desktop.md](./desktop/README.desktop.md): Electron shell startup, runtime URL resolution, and desktop-specific troubleshooting
- [environment.yml](./environment.yml): recommended Conda environment definition
- [.env.example](./.env.example): template for API and runtime configuration

Important runtime files:

- `.env`: long-term local API and startup configuration that you edit manually
- `.runtime_startup.env`: auto-generated effective runtime host and port written by the startup scripts after port resolution
- `.bootstrap_backend_state.env`: auto-generated backend bootstrap state used by `if-needed` startup checks

## What This Project Does

- converts raster images into editable SVG
- serves a shared web frontend from FastAPI
- supports an optional Electron desktop shell that reuses the same frontend
- reserves SAM-based bbox refinement as an optional post-recognition refinement path

## Development Goal

The current developer experience is optimized for this target:

- a developer can clone the repo on a new machine
- complete minimal setup in 10 to 20 minutes
- start the web frontend first
- optionally launch the desktop shell on top of the same backend
- package a Windows installer for non-developer users

## Requirements

Required on all platforms:

- Python 3.11+
- network access for `pip install`
- network access to your model API endpoint

Required only for desktop development:

- Node.js 20+
- network access for `npm install` unless desktop dependencies are already packaged

Required only for Windows installer builds:

- Windows
- PowerShell
- an existing Python environment that can create `.venv_package`
- Node.js/npm dependencies under `desktop/`

## Fastest Development Start

If you want the shortest local development path, use the automatic startup flow and then fill `.env` before your first real model-backed conversion.

The full startup manual is in [docs.development.md](./docs.development.md).

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

macOS:

```bash
chmod +x start-dev.sh
./start-dev.sh
```

Linux:

```bash
chmod +x start-dev.sh
./start-dev.sh
```

To launch web + desktop together:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

macOS/Linux:

```bash
./start-dev.sh --desktop
```

To stop an active Windows desktop development session manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-dev.ps1
```

## Build A User Installer

For a normal local Windows installer build:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

For a versioned release installer that can overwrite an older installation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

If Python backend dependencies changed, recreate the clean packaging environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -RecreatePackageVenv -SkipNpmInstall
```

The expected Windows installer output is:

```text
dist/installers/
```

For a developer-side macOS DMG build, run this on macOS:

```bash
chmod +x packaging/*.sh
./packaging/build-release-macos.sh --version <new-version> --skip-npm-install
```

Read [packaging/README.packaging.md](./packaging/README.packaging.md) before publishing installers to users.

## Which Document To Open

Open [docs.development.md](./docs.development.md) if you need:

- Conda setup
- `.env` and API key instructions
- automatic startup versus manual startup
- port conflict interaction details
- startup failure troubleshooting

Open [packaging/README.packaging.md](./packaging/README.packaging.md) if you need:

- clean `.venv_package` packaging
- Windows installer builds
- versioned overwrite updates
- uninstall behavior
- dependency-size analysis

Open [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) if you need:

- source-bundle deployment
- migration to another machine
- target-machine bootstrap

Open [desktop/README.desktop.md](./desktop/README.desktop.md) if you need:

- Electron-only bootstrap
- frontend URL override behavior
- desktop-specific debugging

## Recommended Development Reading Order

If you are developing locally:

1. read [docs.development.md](./docs.development.md)
2. create or activate your Conda environment if needed
3. fill `.env` before the first real model-backed conversion
4. use automatic startup first, then switch to manual startup when you need finer control

If you are building user installers:

1. read [packaging/README.packaging.md](./packaging/README.packaging.md)
2. use `build-release-windows.ps1` for real user-facing releases
3. keep `desktop/package.json` `build.appId` and `build.productName` stable between versions

If you are moving the source tree to another machine:

1. read [quick-start/README.quick-start.md](./quick-start/README.quick-start.md)
2. create a source deployment bundle
3. bootstrap the backend on the target machine

If you are debugging the Electron shell:

1. read [desktop/README.desktop.md](./desktop/README.desktop.md)

## Related Docs

- [README.md](./README.md)
- [docs.development.md](./docs.development.md)
- [packaging/README.packaging.md](./packaging/README.packaging.md)
- [docs.installer.md](./docs.installer.md)
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md)
- [desktop/README.desktop.md](./desktop/README.desktop.md)
