# Shape Studio Release Notes

This file records version-specific changes, release artifacts, checksums, verification, and upgrade notes.

Stable product behavior, platform support, installation model, and user-data locations are documented in [README.md](./README.md). Packaging and release-build procedures are documented in [packaging/README.packaging.md](./packaging/README.packaging.md).

## Version History Overview

This project has only a small number of tagged releases in git, so the early version history below combines confirmed tags, local installer artifact timestamps, and commit names. Treat the grouped descriptions as release-history reconstruction rather than a complete changelog for every build.

### 0.1.x - Installer And Desktop Packaging Foundation

Small versions:

- `0.1.0`
- `0.1.5`
- `0.1.6`
- `0.1.8`

Summary:

- Established the first Windows installer path with Electron, a PyInstaller-bundled backend, NSIS packaging, desktop startup scripts, icons, and packaging documentation.
- `0.1.5` was a version metadata release. The git tag updates only `pyproject.toml`, `desktop/package.json`, and `desktop/package-lock.json`.
- `0.1.6` appears twice in local artifacts: once under the older `Raster to SVG` product name and once under the newer `Shape Studio` product name, marking the product naming transition.
- `0.1.8` appears to be a follow-up Shape Studio desktop/installer refinement build.

Local installer artifacts:

| Artifact | Version | Timestamp |
| --- | --- | --- |
| `Raster to SVG Setup 0.1.0.exe` | `0.1.0` | 2026-07-07 06:25:30 |
| `Raster to SVG Setup 0.1.5.exe` | `0.1.5` | 2026-07-07 10:16:16 |
| `EditableTransf-Setup-V0.1.5.exe` | `0.1.5` | 2026-07-07 10:16:16 |
| `Raster to SVG Setup 0.1.6.exe` | `0.1.6` | 2026-07-07 11:47:30 |
| `Shape Studio Setup 0.1.6.exe` | `0.1.6` | 2026-07-09 14:11:17 |
| `Shape Studio Setup 0.1.8.exe` | `0.1.8` | 2026-07-10 18:35:54 |

### 0.2.x - Refinement And Product Workflow Iteration

Small versions with local installer artifacts:

- `0.2.0`
- `0.2.5`
- `0.2.6`

Related intermediate commit markers:

- `0.2.1`
- `0.2.2`
- `0.2.3`

Summary:

- The `0.2.x` line appears to focus on conversion quality, refinement behavior, policy/rule tuning, artifact handling, and desktop workflow polish.
- Git commit names include `v0.2.1-refine-opt`, `v0.2.2-refine-opt`, `v0.2.3-refine-opt`, and `v0.2.5-refine-opt`, suggesting an optimization sequence around refinement and conversion reliability.
- `0.2.6` appears to be a small follow-up build after the `0.2.5` refinement optimization release.

Local installer artifacts:

| Artifact | Version | Timestamp |
| --- | --- | --- |
| `Shape Studio Setup 0.2.0.exe` | `0.2.0` | 2026-07-12 04:10:18 |
| `Shape Studio Setup 0.2.5.exe` | `0.2.5` | 2026-07-14 13:58:09 |
| `Shape Studio Setup 0.2.6.exe` | `0.2.6` | 2026-07-15 17:40:12 |

### 0.3.x - Workspace Stability And Release Hardening

Small versions:

- `0.3.0`

Summary:

- Added local-only API access protection, bounded run queues, cooperative run cancellation, safer artifact operations, manual-adjustment execution isolation, expanded runtime settings, and synchronized version metadata.
- Rebuilt the Windows installer after aligning the API version with package and desktop metadata.

Local installer artifact:

| Artifact | Version | Timestamp |
| --- | --- | --- |
| `Shape Studio Setup 0.3.0.exe` | `0.3.0` | 2026-07-19 15:15:07 |

## 0.3.0

Release date: 2026-07-19

### Summary

Shape Studio 0.3.0 hardens the Windows desktop packaging path and improves the conversion workspace for day-to-day use. The release adds a richer project history workflow, safer run lifecycle controls, more visible quality/budget settings, local-only service protection, and synchronized version metadata for future releases.

### Release Artifact

Windows installer:

```text
Shape Studio Setup 0.3.0.exe
```

Build artifact:

```text
dist/installers/Shape Studio Setup 0.3.0.exe
```

SHA256:

```text
5D8DCC2E03D167DC8E60770D0C66F85C36FDB4CC62A6200836EA6568768D1B07
```

File size:

```text
157,978,676 bytes
```

### Highlights

- Added a fuller desktop History page with project search, status filters, pagination, and saved-run opening.
- Added run cancellation and artifact-backed resume flows so long or paused conversions can be managed from the workspace.
- Expanded manual adjustment tooling with target selection, reference-image handling, and safer background execution.
- Made the service local-only by default. Startup scripts reject non-loopback hosts, and the API rejects non-local clients.
- Added bounded execution queues for conversions and manual refinements to avoid unbounded concurrent work in one API process.
- Added artifact leases and safer run directory operations for rename, delete, resume, and manual adjustment workflows.
- Expanded user-facing quality and budget settings, including model-call budget and repair-depth controls.
- Rebuilt the Windows 0.3.0 installer after synchronizing API/package version metadata.

### User-Facing Changes

Desktop workspace:

- The desktop shell now exposes clearer workspace navigation for Start, History, Workspace, and Settings.
- Saved conversion runs can be searched, filtered by status, paged through, and reopened.
- Active runs expose cancellation when they are queued or running.
- Paused or resumable artifact-backed runs can be resumed with additional model-call budget.

Manual adjustment:

- Manual refinement now runs through a separate bounded executor from full conversions.
- The UI supports selecting targets, drawing regions, using default crops, adding reference images, and pasting/capturing reference material.
- Artifact access is guarded while manual adjustment is in progress, reducing the chance of conflicting edits.

Settings and runtime defaults:

- Runtime settings are grouped more clearly around connection/model setup, workflow defaults, quality/budget, and recognition experiments.
- `.env.example` now documents the current retry, budget, concurrency, and repair-depth controls.
- Deprecated aggregate retry variables remain documented as migration references but are no longer the preferred tuning path.

Safety and local access:

- Shape Studio is now intentionally local-only because the API has no user authentication layer.
- Keep `APP_HOST=127.0.0.1`; `0.0.0.0` and other non-loopback hosts are rejected by startup scripts.
- The FastAPI middleware also rejects non-local clients.

### Developer And Packaging Changes

- Version metadata is now synchronized across `pyproject.toml`, `src/deepagents_template/version.py`, `desktop/package.json`, and `desktop/package-lock.json`.
- The FastAPI app reports the package version instead of the old hard-coded `0.1.0`.
- `set-version` and `validate-version` scripts on both Windows and Bash now include the package version file.
- Packaging documentation now reflects the expanded version synchronization path.
- Windows release build output is versioned as `Shape Studio Setup 0.3.0.exe`.

### Upgrade Notes

For Windows users:

1. Close Shape Studio if it is running.
2. Download and run `Shape Studio Setup 0.3.0.exe`.
3. Complete the installer wizard.
4. Reopen Shape Studio from the Start Menu or desktop shortcut.

### Verification

The 0.3.0 release candidate was checked with:

```text
packaging/validate-version.ps1
packaging/validate-version.sh
python -m ruff check src packaging
python -m pytest test
git diff --check
```

Results:

```text
Version metadata OK: 0.3.0
ruff: all checks passed
pytest: 208 passed, 1 skipped
Windows installer build completed
```
