# Quick Start for Windows, Linux, and macOS

`quick-start/` provides a cross-platform migration and deployment entrypoint for this project.
It is designed for a simple workflow:

1. package the project on the source machine
2. copy the package to the target machine
3. bootstrap the environment
4. start the API service

This directory now supports:

- Windows
- Linux
- macOS

## What This Quick Start Covers

It is intended for:

- migrating the project source to another machine
- deploying the FastAPI service together with the built-in frontend
- starting the service with the project `.env` configuration

It does not produce a fully offline bundle.
The target machine still needs:

- Python 3.11 or newer
- network access for `pip install`

If you need a complete historical migration, you can also include:

- `.env`
- `artifacts/`
- `.frontend_runtime_overrides.json`

## Files in This Directory

- `bootstrap.sh`: Linux/macOS bootstrap
- `start-api.sh`: Linux/macOS service startup
- `package.sh`: Linux/macOS packaging
- `bootstrap.ps1`: Windows bootstrap
- `start-api.ps1`: Windows service startup
- `package.ps1`: Windows packaging
- `bootstrap.bat`: Windows bootstrap wrapper
- `start-api.bat`: Windows startup wrapper
- `package.bat`: Windows packaging wrapper

## Project Requirements

Before deployment, make sure the target machine has:

- Python 3.11+
- access to your model API endpoint

Recommended required environment settings:

- `API_KEY`
- `BASE_URL`
- `API_PROVIDER`
- `API_FORMAT`

Optional service settings:

- `APP_HOST`
- `APP_PORT`
- `RUN_ARTIFACTS_DIR`

## Quick Path

If you want the shortest path:

1. package on the source machine
2. copy the generated archive to the target machine
3. extract it
4. run bootstrap
5. edit `.env`
6. start the service

The detailed instructions below cover each operating system.

## Step 1: Package the Project on the Source Machine

### On Windows

From the project root:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\package.ps1
```

Or:

```bat
cd quick-start
package.bat
```

### On Linux or macOS

From the project root:

```bash
cd quick-start
chmod +x package.sh
./package.sh
```

### Packaging Output

The package is created under:

```text
dist/deploy-packages/
```

Default outputs:

- Windows packaging:
  - `dist/deploy-packages/<project>-deploy-<timestamp>/`
  - `dist/deploy-packages/<project>-deploy-<timestamp>.zip`
- Linux/macOS packaging:
  - `dist/deploy-packages/<project>-deploy-<timestamp>/`
  - `dist/deploy-packages/<project>-deploy-<timestamp>.tar.gz`

### Default Package Contents

The package includes:

- `src/`
- `quick-start/`
- `pyproject.toml`
- `README.md`
- `.env.example`
- `environment.yml`
- `start-service.ps1`
- `start-service.bat`

By default it does not include:

- `.env`
- `artifacts/`
- `.frontend_runtime_overrides.json`

### Include Real Runtime Configuration

If you want to migrate the actual `.env` file too:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeEnv
```

Linux/macOS:

```bash
INCLUDE_ENV=true ./package.sh
```

### Include Historical Run Artifacts

If you want to preserve existing run outputs and resume data:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeArtifacts
```

Linux/macOS:

```bash
INCLUDE_ARTIFACTS=true ./package.sh
```

### Include Frontend Runtime Overrides

If your frontend has saved runtime overrides and you want to keep them:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeRuntimeOverrides
```

Linux/macOS:

```bash
INCLUDE_RUNTIME_OVERRIDES=true ./package.sh
```

### Customize Package Name or Timestamp

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -PackageName my-demo-deploy -Timestamp 20260612-120000
```

Linux/macOS:

```bash
PACKAGE_NAME=my-demo-deploy TIMESTAMP=20260612-120000 ./package.sh
```

## Step 2: Move the Package to the Target Machine

Copy the generated archive to the destination machine using your preferred method:

- shared folder
- USB drive
- `scp`
- internal file server
- cloud storage

Then extract it.

### Extract on Windows

You can use Explorer or PowerShell:

```powershell
Expand-Archive .\Demo-deploy-20260612-120000.zip -DestinationPath .
```

### Extract on Linux or macOS

```bash
tar -xzf Demo-deploy-20260612-120000.tar.gz
```

After extraction, enter the project directory.

## Step 3: Bootstrap the Environment on the Target Machine

Bootstrap will:

- create `.venv` if needed
- upgrade `pip`
- install the project in editable mode
- create `.env` from `.env.example` if `.env` is missing

### On Windows

From the extracted project root:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Or:

```bat
cd quick-start
bootstrap.bat
```

If your Python command is not `python`:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Python py
```

### On Linux or macOS

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
./bootstrap.sh
```

If your Python command is not `python3`:

```bash
PYTHON_BIN=python ./bootstrap.sh
```

## Step 4: Configure `.env`

If `.env` was not included in the package, bootstrap creates one from `.env.example`.

At minimum, verify these values:

```env
API_KEY=your-real-api-key
BASE_URL=https://api.poe.com/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_responses
APP_HOST=127.0.0.1
APP_PORT=8120
```

For cross-machine access inside a LAN, a common choice is:

```env
APP_HOST=0.0.0.0
APP_PORT=8120
```

## Step 5: Start the Service

### On Windows

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\start-api.ps1
```

Or:

```bat
cd quick-start
start-api.bat
```

Override host and port temporarily:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-api.ps1 -Host 0.0.0.0 -Port 8120
```

Pass extra `uvicorn` arguments:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-api.ps1 --reload
```

### On Linux or macOS

```bash
cd quick-start
./start-api.sh
```

Override host and port temporarily:

```bash
APP_HOST=0.0.0.0 APP_PORT=8120 ./start-api.sh
```

Pass extra `uvicorn` arguments:

```bash
./start-api.sh --reload
```

## Step 6: Access and Use the Service

After startup, the service is typically available at:

- `http://127.0.0.1:8120/` for local access
- `http://<server-ip>:8120/` for LAN access when listening on `0.0.0.0`

Useful endpoints:

- frontend: `/`
- health check: `/health`

Typical usage flow:

1. open the frontend in a browser
2. upload or reference an input image
3. configure request settings
4. start a conversion
5. inspect artifacts and final SVG outputs

## Migration Recommendations

### Recommended Minimal Migration

Good for deploying a fresh instance:

- source code package
- `quick-start/`
- `.env.example`

Then create or edit `.env` on the target machine.

### Recommended Full Migration

Good for preserving working state:

- source code package
- `.env`
- `artifacts/`
- `.frontend_runtime_overrides.json`

This preserves:

- API configuration
- prior run outputs
- resumable run data
- frontend-saved runtime overrides

## Notes About Cross-Platform Behavior

- Windows uses `.ps1` and `.bat` launchers.
- Linux/macOS use `.sh` scripts.
- The actual service entrypoint is the same on all platforms:
  - `python -m uvicorn deepagents_template.api:app`
- The frontend is included in `src/deepagents_template/static`, so the API and UI are deployed together.

## Important Operational Notes

- This deployment flow installs dependencies from the internet. It is not an offline bundle.
- The project may generate artifacts under `artifacts/runs` unless you change `RUN_ARTIFACTS_DIR`.
- Some SVG preview rendering paths attempt to use Node-based image rendering when available. The core service can still run even if that preview capability is unavailable, but some rendered PNG previews may be missing.

## Troubleshooting

### Python command not found

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Python py
```

Linux/macOS:

```bash
PYTHON_BIN=python ./bootstrap.sh
```

### `.env` is missing after migration

Run bootstrap first. It will create `.env` from `.env.example` when possible.

### Service starts but model calls fail

Check:

- `API_KEY`
- `BASE_URL`
- `API_PROVIDER`
- `API_FORMAT`
- outbound network access to the model API

### Frontend opens but old runs are missing

Those historical runs live under `artifacts/`.
If you need them, package or copy `artifacts/` from the source machine.

### Frontend settings do not match the old machine

Those overrides may be stored in `.frontend_runtime_overrides.json`.
Copy that file as well if you want to preserve the same frontend runtime settings.

## For Development Instead of Deployment

`quick-start/` focuses on deployment and startup.
If you also need tests or linting, use the project root and install dev dependencies:

```powershell
python -m pip install -e ".[dev]"
```

or:

```bash
python -m pip install -e ".[dev]"
```
