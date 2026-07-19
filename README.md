# Shape Studio

Shape Studio is a desktop application for converting raster images into editable SVG assets. The Electron desktop frontend is the preferred user experience. The browser frontend is retained for early development and diagnostics and may contain compatibility differences from the desktop shell.

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

macOS and Linux do not yet have supported product-user installers. Use the source deployment path in [quick-start/README.quick-start.md](./quick-start/README.quick-start.md), then launch the Electron desktop frontend.

## Run From Git (Desktop Development Path)

For anyone downloading the repository and running it locally, the normal entrypoint is the root `start-dev` script. It bootstraps the backend, starts the local FastAPI service, and launches the Electron desktop shell.

Prerequisites:

- Python 3.11+
- Node.js 20+ and npm
- Network access for the first dependency installation and for the configured model API

Windows:

```powershell
git clone <repository-url>
cd <repository-directory>
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

macOS/Linux:

```bash
git clone <repository-url>
cd <repository-directory>
chmod +x start-dev.sh
./start-dev.sh --desktop
```

On first run, the script creates or reuses the project Python environment, creates `.env` from `.env.example` when needed, and bootstraps Electron dependencies under `desktop/`. Follow this order:

1. Run the `start-dev` command above and wait for the desktop window to open after the backend health check succeeds.
2. Complete [Configure Before First Conversion](#configure-before-first-conversion) in the desktop Settings panel.
3. Start a real conversion from the desktop window.

The project-root `.env` is an advanced or fallback configuration path: you can edit it after stopping the app and then restart `start-dev` when you need to configure the backend outside the desktop UI. Use the desktop window for normal work; the printed browser URL is a development and diagnostic fallback, and the early browser frontend may not be fully compatible with the desktop experience.

The root `start-dev.ps1` / `start-dev.sh` scripts are the normal source-running entrypoints. Use the lower-level `bootstrap`, `start-api`, and `desktop/bootstrap` scripts only when following the detailed development instructions, troubleshooting startup, or deploying a source bundle to another machine. See [README.developer.md](./README.developer.md) and [docs.development.md](./docs.development.md) for environment selection and manual controls.

## Configure Before First Conversion

In the desktop Settings panel, check only these items before the first real conversion:

| Field | What to do |
| --- | --- |
| API Key | Enter your real API key. |
| Base URL | Enter your provider endpoint, usually ending in `/v1`. |
| Coordinator Model | Enter a model supported by your endpoint. |
| Worker Model | Enter a worker/subtask model supported by your endpoint; it can be the same as Coordinator Model. |
| Request Format | Keep the default unless your provider requires a different format. |
| API Protocol | Keep the default `openai_compatible`. |

All advanced workflow, budget, retry, concurrency, SAM, and memory settings can stay unchanged for the first run.

Detailed configuration behavior is documented in [docs.development.md](./docs.development.md). Frontend label/value mappings are documented in [docs.settings-mapping.md](./docs.settings-mapping.md).

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

## In Development / Planned Work

The start page currently allows users to customize the instruction sent with a conversion request. This input is experimental: the current backend workflow is optimized for the raster-to-editable-SVG task and does not guarantee that every added requirement, wording, constraint, or domain-specific instruction can be satisfied.

Treat custom instructions as guidance rather than a strict contract. The generated result may omit, reinterpret, or be unable to implement part of a request, even when the instruction is accepted by the UI. Improving instruction handling, requirement validation, and end-to-end fulfillment is ongoing work.

The browser frontend is also an earlier development surface. For normal use, prefer the Electron desktop frontend and report behavior differences there before relying on the browser version.

## Manual Refine

After the main conversion flow finishes and a usable output is available, open **Refine** in the desktop frontend to make targeted follow-up changes without rerunning the entire conversion.

The manual refinement flow is:

1. Select the object or editable region to change.
2. Describe the requested change in the refinement instruction.
3. Optionally add one or more reference images when the intended appearance needs visual guidance.
4. Apply the refinement and compare the new result with the existing output.

Manual Refine is intended for a broad range of follow-up work, including improving fidelity, removing an element, replacing an element, adding content, or changing an element's visual style. It can be applied repeatedly to the current result, with each refinement focused on the selected target.

The instruction and reference image guide the refinement; they are not a strict guarantee. Results depend on the selected target, the clarity of the instruction and reference, and the configured model. For best results, describe one focused change at a time and review the output before applying another refinement.

## Quick Navigation

| Your Role | Read This | Purpose |
| --- | --- | --- |
| Product user on Windows | This README | Install, update, uninstall, and find user-data/log locations. |
| Source user on macOS/Linux | [Run From Git (Desktop Development Path)](#run-from-git-desktop-development-path) | Clone the repository and run the Electron desktop path. |
| Source/development user | [README.developer.md](./README.developer.md) | Choose a Python environment and find the detailed development manual. |
| Source-bundle user | [quick-start/README.quick-start.md](./quick-start/README.quick-start.md) | Migrate a prepared source bundle or bootstrap a target machine manually. |
| Release maintainer | [packaging/README.packaging.md](./packaging/README.packaging.md) | Build versioned installers and publish update artifacts. |
| Desktop shell maintainer | [desktop/README.desktop.md](./desktop/README.desktop.md) | Debug Electron startup and frontend URL resolution. |
| Architecture maintainer | [architecture-summary/README.md](./architecture-summary/README.md) | Understand current architecture, boundaries, and legacy areas. |

## Windows User Basics

### Install

1. Open the repository's Releases page.
2. Download the latest `Shape Studio Setup <version>.exe`.
3. Run the installer.
4. Open `Shape Studio` from the Start Menu or desktop shortcut.

Older installer builds may contain fixed bugs, so always use the newest release when you install from a package.

### Configure And Run

Complete [Configure Before First Conversion](#configure-before-first-conversion) in the desktop Settings panel, then start a real conversion from the desktop window.

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
