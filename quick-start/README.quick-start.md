# Source Deployment Quick Start

This directory is the cross-platform source-bundle migration and deployment entrypoint for the project.

## Use This README When

Use this document when your main goal is:

- move the project to another machine
- create a deployable source bundle
- bootstrap the backend on a target machine
- start the FastAPI service together with the shared frontend

For overall project navigation, start with the root [README.md](../README.md).
For local development, use [README.developer.md](../README.developer.md).

## What This README Covers

`quick-start/` is intentionally focused on source-bundle deployment and migration.

It does not try to be the primary development guide.
It also does not build product-user desktop installers; installer builds live under `packaging/`.

It covers:

- Windows
- macOS
- Linux

It does not produce a fully offline bundle.

The target machine still needs:

- Python 3.11+
- network access for `pip install`
- network access to your model API endpoint

Desktop shell support is included, but the backend remains the primary requirement.
For day-to-day development, prefer the root startup scripts and the detailed guide in [docs.development.md](../docs.development.md).

## What This Directory Contains

- `bootstrap.ps1` / `bootstrap.sh`: backend bootstrap
- `start-api.ps1` / `start-api.sh`: backend startup
- `package.ps1` / `package.sh`: deployment package creation
- `bootstrap.bat`, `start-api.bat`, `package.bat`: Windows wrappers

Related desktop scripts live in:

- [desktop/bootstrap.ps1](../desktop/bootstrap.ps1)
- [desktop/bootstrap.sh](../desktop/bootstrap.sh)
- [desktop/start-desktop.ps1](../desktop/start-desktop.ps1)
- [desktop/start-desktop.sh](../desktop/start-desktop.sh)

## Deployment Flow

Recommended deployment flow:

1. create a source deployment bundle on the source machine
2. move the package to the target machine
3. extract it
4. bootstrap the backend
5. fill `.env`
6. start the API
7. optionally start the desktop shell

## Step 1: Create a Source Deployment Package

### Windows

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

### macOS

From the project root:

```bash
cd quick-start
chmod +x package.sh
./package.sh
```

### Linux

From the project root:

```bash
cd quick-start
chmod +x package.sh
./package.sh
```

Packaging output is created under:

```text
dist/deploy-packages/
```

By default the package includes:

- `src/`
- selected `desktop/` source files and configuration
- `quick-start/`
- `pyproject.toml`
- `README.md`
- `README.developer.md`
- `docs.development.md`
- `docs.installer.md`
- `.env.example`
- `environment.yml`
- `start-dev.ps1`
- `start-dev.bat`
- `start-dev.sh`
- `start-service.ps1`
- `start-service.bat`

By default it does not include:

- `.env`
- `artifacts/`
- `.frontend_runtime_overrides.json`
- `desktop/node_modules/`
- local Python virtual environments such as `.venv`, `.venv_test`, and `.venv_package`

The source bundle intentionally excludes generated dependencies. If the target machine needs the Electron desktop shell, run `npm install` under `desktop/` on that machine to recreate `desktop/node_modules/`.

### Optional Packaging Flags

Include real `.env`:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeEnv
```

macOS/Linux:

```bash
INCLUDE_ENV=true ./package.sh
```

Include run artifacts:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeArtifacts
```

macOS/Linux:

```bash
INCLUDE_ARTIFACTS=true ./package.sh
```

Include frontend runtime overrides:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1 -IncludeRuntimeOverrides
```

macOS/Linux:

```bash
INCLUDE_RUNTIME_OVERRIDES=true ./package.sh
```

If you need the desktop shell details after deployment, continue with [desktop/README.desktop.md](../desktop/README.desktop.md).

## Step 2: Move and Extract the Package

Move the archive using your preferred method:

- shared folder
- USB drive
- `scp`
- internal file server
- cloud storage

### Windows

```powershell
Expand-Archive .\Demo-deploy-20260612-120000.zip -DestinationPath .
```

### macOS

```bash
tar -xzf Demo-deploy-20260612-120000.tar.gz
```

### Linux

```bash
tar -xzf Demo-deploy-20260612-120000.tar.gz
```

## Step 3: Bootstrap the Backend on the Target Machine

Bootstrap does these things:

- prefers an active Conda environment when one is already activated
- recognizes active virtualenv environments and nested virtualenv-on-Conda cases
- otherwise creates and uses `.venv`
- upgrades `pip`
- installs the project in editable mode
- creates `.env` from `.env.example` when missing
- leaves `.env.example` unchanged and writes effective runtime values later to `.runtime_startup.env`
- records backend bootstrap state in `.bootstrap_backend_state.env`

The default bootstrap recommendation for development-style startup is now `if-needed` rather than always reinstalling.
That same default is also used by the root `start-dev` scripts.

### Windows

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -IfNeeded
```

If you want to use the current activated Python explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -UseActivePython -IfNeeded
```

If your Python launcher is `py`:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Python py -IfNeeded
```

If you want to force a full reinstall:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

### macOS

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

If you want to force the current interpreter:

```bash
USE_ACTIVE_PYTHON=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

If you want to force a full reinstall:

```bash
./bootstrap.sh
```

### Linux

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

If you want to force the current interpreter:

```bash
USE_ACTIVE_PYTHON=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

If you want to force a full reinstall:

```bash
./bootstrap.sh
```

## Step 4: Fill `.env`

After bootstrap, review the project-root `.env`.

You do not need a real API key just to start the frontend page, but you do need real API settings before the first actual model-backed conversion.

At minimum, fill or verify:

```env
API_KEY=your-real-api-key
BASE_URL=https://your-openai-compatible-endpoint.example/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_chat_completions
AGENT_MODEL=your-coordinator-model
SUBAGENT_MODEL=your-worker-model
APP_HOST=127.0.0.1
APP_PORT=8120
```

For LAN access, a common choice is:

```env
APP_HOST=0.0.0.0
APP_PORT=8120
```

Optional startup interaction setting:

```env
PORT_PROMPT_TIMEOUT_SECONDS=15
```

Minimum configuration guide:

| Setting | What To Put |
| --- | --- |
| `API_KEY` | Secret key for the model provider |
| `BASE_URL` | OpenAI-compatible endpoint, usually ending in `/v1` |
| `API_PROVIDER` | Keep `openai_compatible` unless this project adds another provider adapter |
| `API_FORMAT` | `openai_chat_completions` for chat-compatible APIs, or `openai_responses` for Responses API support |
| `AGENT_MODEL` | Main/coordinator model name supported by your endpoint |
| `SUBAGENT_MODEL` | Worker model name supported by your endpoint; often the same as `AGENT_MODEL` |

## Step 5: Start the Backend Service

### Windows

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\start-api.ps1
```

Or:

```bat
cd quick-start
start-api.bat
```

Override host and port:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-api.ps1 -ListenHost 0.0.0.0 -Port 8120
```

Enable reload:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-api.ps1 --reload
```

### macOS

```bash
cd quick-start
./start-api.sh
```

Override host and port:

```bash
APP_HOST=0.0.0.0 APP_PORT=8120 ./start-api.sh
```

Enable reload:

```bash
./start-api.sh --reload
```

### Linux

```bash
cd quick-start
./start-api.sh
```

Override host and port:

```bash
APP_HOST=0.0.0.0 APP_PORT=8120 ./start-api.sh
```

Enable reload:

```bash
./start-api.sh --reload
```

The service is usually available at:

- `http://127.0.0.1:8120/`
- `http://<server-ip>:8120/` when listening on `0.0.0.0`

Useful endpoints:

- `/`
- `/health`

### Port conflict handling during startup

Before the backend starts, the startup scripts check whether the requested port is already in use.

If the port is occupied, the script:

- shows the occupied port
- shows the listener PID and process name when available
- tells you exactly what input is expected

Accepted inputs:

- `yes`, `Yes`, or `Y`: stop the listed process and keep using the same port
- `no`, `NO`, or `N`: choose another port or cancel startup
- `<port number>`: retry startup with another port after you choose not to release the original port

If there is no interaction for `PORT_PROMPT_TIMEOUT_SECONDS` seconds:

- the script automatically selects a free port
- the backend continues startup on that port

After the final host and port are confirmed, the script writes:

- `.runtime_startup.env`
- `.bootstrap_backend_state.env` during bootstrap

This runtime file stores the effective `APP_HOST`, `APP_PORT`, and `PORT_PROMPT_TIMEOUT_SECONDS`.
It helps the desktop shell and later startup steps stay aligned with the actual running port, without overwriting your long-term `.env` or `.env.example`.

The bootstrap state file stores the interpreter path, whether dev dependencies were installed, and the last known `pyproject.toml` timestamp.
It is used by `if-needed` bootstrap checks to skip unnecessary `pip` work on later runs.

## Step 6: Optionally Start the Desktop Shell

After the backend is healthy, you can start the packaged Electron shell.

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\start-desktop.ps1
```

macOS:

```bash
chmod +x ./desktop/start-desktop.sh
./desktop/start-desktop.sh
```

Linux:

```bash
chmod +x ./desktop/start-desktop.sh
./desktop/start-desktop.sh
```

If needed, override the frontend URL with `RASTER_SVG_FRONTEND_URL`.

If no explicit frontend URL is provided, the desktop startup scripts now prefer:

1. `RASTER_SVG_FRONTEND_URL`
2. `.runtime_startup.env`
3. `.env`
4. `http://127.0.0.1:8120/`

For desktop-specific behavior and runtime resolution, continue with [desktop/README.desktop.md](../desktop/README.desktop.md).

## Deployment-oriented Troubleshooting

### Python is missing or too old

Check:

- Python 3.11+
- `-Python py` on Windows when needed
- `USE_ACTIVE_PYTHON=true` when you want to reuse an activated environment

### Bootstrap succeeds but real conversions fail

Check:

- `API_KEY`
- `BASE_URL`
- `API_PROVIDER`
- `API_FORMAT`
- outbound network access to the model API

### Backend starts but desktop cannot connect

Check:

- backend is running
- `/health` is reachable
- `APP_HOST`
- `APP_PORT`
- `RASTER_SVG_FRONTEND_URL`

### Migrated frontend does not show old history or saved settings

Check whether you also copied:

- `artifacts/`
- `.frontend_runtime_overrides.json`

## Related Docs

- [README.md](../README.md)
- [README.developer.md](../README.developer.md)
- [docs.development.md](../docs.development.md)
- [desktop/README.desktop.md](../desktop/README.desktop.md)
