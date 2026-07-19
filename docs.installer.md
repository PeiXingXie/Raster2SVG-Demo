# Archived Installer Note

This file is no longer the authoritative installer or release-build guide.

Use [packaging/README.packaging.md](./packaging/README.packaging.md) for current packaging, installer build, overwrite-update, uninstall, dependency-size, and installed-app behavior documentation.

## Why This File Remains

Older project notes and source bundles may still link to `docs.installer.md`. To avoid broken links during the documentation transition, this file is kept as a short compatibility note.

## Current Ownership

| Topic | Current authoritative document |
| --- | --- |
| Build Windows installers | [packaging/README.packaging.md](./packaging/README.packaging.md) |
| Build release versions | [packaging/README.packaging.md](./packaging/README.packaging.md) |
| Installed-app startup behavior | [packaging/README.packaging.md](./packaging/README.packaging.md) |
| Overwrite updates | [packaging/README.packaging.md](./packaging/README.packaging.md) |
| Uninstall and user-data retention | [packaging/README.packaging.md](./packaging/README.packaging.md) |
| User-facing install/update basics | [README.md](./README.md) |

## Historical Context

The original version of this file described the first Windows installer MVP:

```text
Electron desktop shell
+ PyInstaller onedir FastAPI backend
+ electron-builder / NSIS installer
```

That architecture is now documented and maintained in [packaging/README.packaging.md](./packaging/README.packaging.md).
