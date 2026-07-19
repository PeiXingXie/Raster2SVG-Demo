# Shape Studio Developer Guide

This file is the developer entrypoint. It gives the shortest source startup path and points to the authoritative detailed documents.

For the product-facing overview and complete documentation index, use [README.md](./README.md).

## Developer Path

Use [docs.development.md](./docs.development.md) as the authoritative development manual. It covers Python environment selection, `.env`, automatic and manual startup, port conflict handling, desktop startup, and troubleshooting.

Fastest web development start:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

macOS/Linux:

```bash
chmod +x start-dev.sh
./start-dev.sh
```

Fastest web + desktop development start:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

macOS/Linux:

```bash
./start-dev.sh --desktop
```

The frontend is usually available at:

```text
http://127.0.0.1:8120/
```

Development API settings live in the project-root `.env`. If `.env` does not exist, startup/bootstrap scripts create it from [.env.example](./.env.example).

## Required Tools

Required on all platforms:

- Python 3.11+
- network access for `pip install`
- network access to your model API endpoint

Required only for desktop development:

- Node.js 20+
- network access for `npm install` unless desktop dependencies are already available

Required only for Windows installer builds:

- Windows
- PowerShell
- Python environment capable of creating `.venv_package`
- desktop npm dependencies under `desktop/`

## Build And Release

Use [packaging/README.packaging.md](./packaging/README.packaging.md) as the only authoritative packaging and release-build document.

Normal local Windows installer build:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build-windows-installer.ps1 -SkipNpmInstall
```

Versioned Windows release build:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-release-windows.ps1 -Version <new-version> -Python python -SkipNpmInstall
```

Do not manually edit version numbers across multiple files for releases; use the packaging scripts.

## Document Map

Open these documents by topic:

- [docs.development.md](./docs.development.md): full development environment, startup, `.env`, port handling, and troubleshooting manual
- [packaging/README.packaging.md](./packaging/README.packaging.md): installer packaging, versioned release builds, overwrite-update behavior, and package-size notes
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md): source-bundle deployment and migration to another machine
- [desktop/README.desktop.md](./desktop/README.desktop.md): Electron shell startup, runtime URL resolution, and desktop-specific troubleshooting
- [docs.settings-mapping.md](./docs.settings-mapping.md): frontend settings labels and displayed value mapping
- [architecture-summary/README.md](./architecture-summary/README.md): current architecture, workflow, runtime, state, deployment, and maintenance boundaries
- [RELEASE_NOTES.md](./RELEASE_NOTES.md): version-specific changes, artifacts, checksums, and verification

Generated/local runtime files:

- `.env`: local API and startup configuration that you edit manually
- `.runtime_startup.env`: generated effective runtime host and port after port resolution
- `.bootstrap_backend_state.env`: generated bootstrap state used by `if-needed` startup checks

## Recommended Reading Order

Developing locally:

1. Read [docs.development.md](./docs.development.md).
2. Fill `.env` before the first real model-backed conversion.
3. Use the root `start-dev` scripts first.
4. Switch to manual startup only when you need finer control.

Building user installers:

1. Read [packaging/README.packaging.md](./packaging/README.packaging.md).
2. Use `build-release-windows.ps1` for user-facing Windows releases.
3. Keep `desktop/package.json` `build.appId` and `build.productName` stable between versions.

Moving the source tree to another machine:

1. Read [quick-start/README.quick-start.md](./quick-start/README.quick-start.md).
2. Create a source deployment bundle.
3. Bootstrap the backend on the target machine.

Debugging the Electron shell:

1. Read [desktop/README.desktop.md](./desktop/README.desktop.md).
