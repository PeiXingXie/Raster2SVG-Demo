# Shape Studio

Shape Studio is a desktop/web application for converting raster images into editable SVG assets.

This file is the single project entrypoint. Use it to understand what the project does, which user path is currently supported, and which detailed document is authoritative for each topic.

## Current Product Path

The supported product-user path is Windows:

```text
Windows installer -> Electron desktop app -> bundled local FastAPI backend -> editable SVG output
```

Windows users install Shape Studio from the repository's Releases page by downloading:

```text
Shape Studio Setup <version>.exe
```

The installed app starts its bundled backend automatically. Product users do not need Python, Node.js, Conda, or a terminal.

macOS and Linux do not yet have supported product-user installers. Use the source deployment path in [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) for those platforms.

## What The App Does

Typical conversion flow:

```text
upload a raster image
-> model recognizes layout, regions, objects, and geometric relationships
-> backend creates structured conversion artifacts
-> desktop UI shows progress, previews, reports, and SVG files
-> user exports or manually refines the SVG result
```

Current application pieces:

- FastAPI backend
- Shared static frontend modules
- Electron desktop shell
- Windows installer built with PyInstaller and electron-builder

## Quick Navigation

| Your Role | Read This | Purpose |
| --- | --- | --- |
| Product user on Windows | This README | Install, update, uninstall, and find user-data/log locations. |
| Product user on macOS/Linux | [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) | Run from a source deployment bundle until product installers exist. |
| Developer | [README.developer.md](./README.developer.md) | Start from source and find the detailed development manual. |
| Release maintainer | [packaging/README.packaging.md](./packaging/README.packaging.md) | Build versioned installers and publish update artifacts. |
| Desktop shell maintainer | [desktop/README.desktop.md](./desktop/README.desktop.md) | Debug Electron startup and frontend URL resolution. |
| Architecture maintainer | [architecture-summary/README.md](./architecture-summary/README.md) | Understand current architecture, boundaries, and legacy areas. |

## Windows User Basics

### Install

1. Open the repository's Releases page.
2. Download `Shape Studio Setup <version>.exe`.
3. Run the installer.
4. Open `Shape Studio` from the Start Menu or desktop shortcut.

### Configure And Run

In the app settings, fill the model connection fields before running real conversions:

- API Key
- Base URL
- API Provider
- API Format
- Coordinator Model
- Worker Model

Detailed configuration behavior is documented in [docs.development.md](./docs.development.md). Frontend label/value mappings are documented in [docs.settings-mapping.md](./docs.settings-mapping.md).

### Update

1. Close Shape Studio.
2. Download the newer Windows installer.
3. Run it over the existing installation.
4. Reopen Shape Studio.

Program files are replaced. User settings, generated artifacts, and logs are preserved by default.

### Uninstall

Uninstall from Windows Settings or the Start Menu uninstall shortcut. During interactive uninstall, the uninstaller asks whether to remove user data.

Windows user data is usually stored under:

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

## Platform Status

| Platform | Product-user status |
| --- | --- |
| Windows | Supported installer/update/uninstall loop. |
| macOS | Developer-side packaging scripts exist, but public installer distribution still needs signing, notarization, architecture testing, and clean-machine validation. |
| Linux | Source/backend startup path only; no supported product installer yet. |

## Documentation Index

Authoritative documents:

- [README.developer.md](./README.developer.md): developer entrypoint and reading order
- [docs.development.md](./docs.development.md): development environment, startup modes, configuration, and troubleshooting
- [packaging/README.packaging.md](./packaging/README.packaging.md): installer packaging, release builds, overwrite updates, dependency-size notes, and installed-app behavior
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md): source-bundle migration, deployment, and target-machine bootstrap
- [desktop/README.desktop.md](./desktop/README.desktop.md): Electron shell startup, runtime URL resolution, and desktop-specific troubleshooting
- [docs.settings-mapping.md](./docs.settings-mapping.md): frontend settings label/value mapping
- [architecture-summary/README.md](./architecture-summary/README.md): Chinese architecture summary and maintenance boundaries
- [RELEASE_NOTES.md](./RELEASE_NOTES.md): version-specific changes, artifacts, checksums, and verification

Historical or transitional notes:

- [docs.installer.md](./docs.installer.md): archived installer note that points to the current packaging authority

Directory roles:

- `quick-start/`: source-bundle deployment and migration scripts
- `packaging/`: installer and release build scripts
- `desktop/`: Electron shell scripts, package metadata, and desktop assets
- `architecture-summary/`: current architecture, workflow, runtime, state, deployment, and maintenance notes
