# Development Guide

This document contains the detailed local development guide for the project.

Use this document when your main goal is:

- set up a local development environment
- choose between automatic and manual startup
- understand how Conda, `.venv`, backend, web frontend, and desktop shell fit together
- fill API configuration before the first real conversion
- troubleshoot startup issues during development

For the project overview and documentation index, use [README.md](./README.md).
For the shorter developer entrypoint, use [README.developer.md](./README.developer.md).

## Frontend Strategy

- Web frontend remains the primary development and monitoring surface.
- Desktop client reuses the same frontend instead of maintaining a second UI codebase.
- SAM-based bbox refinement is wired as an optional refinement mode after region recognition, with local and remote provider interfaces reserved for future implementation.

## Backend, Frontend, and Desktop

In this project:

- `backend` means the FastAPI service started from `deepagents_template.api:app`
- `frontend` means the browser UI served by that FastAPI service
- `desktop client` means the Electron shell that opens the same frontend URL

When you run:

```powershell
python -m uvicorn deepagents_template.api:app --host 127.0.0.1 --port 8120 --reload
```

you are starting the backend.

## Requirements

Required on all platforms:

- Python 3.11+
- network access for `pip install`
- network access to your model API endpoint

Required only for desktop development:

- Node.js 20+
- network access for `npm install` unless desktop dependencies are already packaged

## Python Environment Strategy

The startup scripts now distinguish between:

1. active virtual environment such as `VIRTUAL_ENV`
2. active Conda environment such as `CONDA_PREFIX`
3. explicitly requested active Python mode
4. project-local `.venv` as fallback

That means the scripts can show more accurate startup summaries in cases such as:

- pure Conda
- pure virtualenv
- virtualenv layered on top of Conda
- `.venv` fallback created by the project

The startup summary also prints the real Python executable path that will be used for bootstrap and backend startup.

The startup scripts still prefer this practical resolution order:

1. active Conda environment
2. explicitly requested active Python mode
3. project-local `.venv` as fallback

That means:

- if you already activated a Conda environment, the scripts will use it
- if no Conda environment is active, `UseActivePython` or `USE_ACTIVE_PYTHON=true` means "use the current shell Python as-is"
- otherwise the scripts will fall back to `.venv`
- if `.venv` does not exist yet, bootstrap will create it

In shells where both a virtualenv and Conda are visible, the scripts now report that nested state explicitly instead of only labeling the environment as Conda.

## Recommended Conda Setup

The repo already includes [environment.yml](./environment.yml).

### Windows

Create the environment:

```powershell
conda env create -f environment.yml
```

Activate it:

```powershell
conda activate agent-demo
```

### macOS

Create the environment:

```bash
conda env create -f environment.yml
```

Activate it:

```bash
conda activate agent-demo
```

### Linux

Create the environment:

```bash
conda env create -f environment.yml
```

Activate it:

```bash
conda activate agent-demo
```

After activation, the startup scripts will prefer that Conda environment automatically.

## API Configuration

API-related settings live in the project-root `.env` file.

If `.env` does not exist yet:

- bootstrap creates it from [.env.example](./.env.example)

When to fill it:

- you do not need a real key just to open the frontend page
- you should fill it before the first real model-backed conversion
- the best time is right after bootstrap and before your first `/invoke` or frontend conversion run

Where to fill it:

- edit `.env` in the project root

Most users only need to care about these settings before the first real conversion:

| Setting | Required | Meaning |
| --- | --- | --- |
| `API_KEY` | Yes | Secret key used when calling your model provider |
| `BASE_URL` | Yes | OpenAI-compatible API endpoint, usually ending in `/v1` |
| `API_PROVIDER` | Usually keep default | Provider adapter; keep `openai_compatible` unless another adapter is added |
| `API_FORMAT` | Usually keep default | Request protocol; use `openai_chat_completions` for chat-compatible endpoints or `openai_responses` for Responses API endpoints |
| `AGENT_MODEL` | Yes | Coordinator model used for planning and main conversion decisions |
| `SUBAGENT_MODEL` | Yes | Worker model used for subtasks; it can be the same value as `AGENT_MODEL` |

At minimum, review and fill:

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

If `API_KEY` or `BASE_URL` is empty:

- the frontend can still open
- the backend can still start
- real conversions will fail when the model is actually called

Startup also writes the effective host and port to:

- `.runtime_startup.env`

Backend bootstrap also writes state metadata to:

- `.bootstrap_backend_state.env`

This file is generated automatically during startup and reflects the actual runtime values after port conflict resolution.
It does not replace `.env`, and it does not change the default template in `.env.example`.

`.bootstrap_backend_state.env` stores the interpreter path, whether dev dependencies were installed, and the last known `pyproject.toml` timestamp.
It is used by the default `if-needed` bootstrap logic to decide whether a full reinstall is necessary.

## Automatic Startup

Use automatic startup when:

- you want the fastest path
- you are setting up a new machine
- you want the script to handle bootstrap for you

Use the project-root `start-dev` script.

What it does:

- detects and prefers the active Conda environment
- otherwise falls back to `.venv`
- checks Python version
- installs the project in editable mode with dev dependencies only when needed by default
- creates `.env` from `.env.example` when missing
- starts FastAPI with reload enabled
- optionally bootstraps and launches the Electron desktop shell
- checks whether the target port is already occupied before startup
- writes the effective runtime host and port into `.runtime_startup.env`
- prints a startup summary before handing off to the backend or desktop shell
- avoids repeated startup summaries when `start-dev` hands off to the backend child process
- on Windows desktop startup, records the live session so backend shutdown can be requested gracefully when the desktop window closes, `File -> Quit` is used, `Ctrl+C` interrupts the launcher, or `stop-dev.ps1` is run

### Bootstrap Modes

Backend bootstrap now has two modes:

- `if-needed`
  This is the default for `start-dev`.
  It skips `pip` work when the interpreter, dependency set, and `pyproject.toml` state still match the last successful bootstrap.
- `always`
  This forces a fresh editable install and pip upgrade.

The `if-needed` check currently looks at:

- whether required imports are available
- whether dev dependencies are required for this startup path
- whether the Python interpreter changed
- whether `pyproject.toml` changed since the last bootstrap

The recorded state lives in `.bootstrap_backend_state.env`.

### Windows

Start web development:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

Or:

```bat
start-dev.bat
```

Start web + desktop together:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop
```

Stop the active Windows desktop development session manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-dev.ps1
```

Useful variants:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Python py
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -UseActivePython
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -ForceBootstrap
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -ListenHost 0.0.0.0 -Port 8120
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -Desktop -SkipBootstrap
```

### macOS

Make the script executable once:

```bash
chmod +x start-dev.sh
```

Start web development:

```bash
./start-dev.sh
```

Start web + desktop together:

```bash
./start-dev.sh --desktop
```

Useful variants:

```bash
PYTHON_BIN=python3 ./start-dev.sh
USE_ACTIVE_PYTHON=true ./start-dev.sh
FORCE_BOOTSTRAP=true ./start-dev.sh
APP_HOST=0.0.0.0 APP_PORT=8120 ./start-dev.sh
SKIP_BOOTSTRAP=true ./start-dev.sh
```

### Linux

Make the script executable once:

```bash
chmod +x start-dev.sh
```

Start web development:

```bash
./start-dev.sh
```

Start web + desktop together:

```bash
./start-dev.sh --desktop
```

Useful variants:

```bash
PYTHON_BIN=python3 ./start-dev.sh
USE_ACTIVE_PYTHON=true ./start-dev.sh
FORCE_BOOTSTRAP=true ./start-dev.sh
APP_HOST=0.0.0.0 APP_PORT=8120 ./start-dev.sh
SKIP_BOOTSTRAP=true ./start-dev.sh
```

## Manual Startup

Use manual startup when:

- you want to control each step
- you are debugging installation or environment issues
- you only want backend or only want desktop
- you prefer a Conda-first developer workflow

### Option A: Conda-first manual startup

#### Windows

```powershell
conda activate agent-demo
python -m pip install -e ".[dev]"
python -m uvicorn deepagents_template.api:app --host 127.0.0.1 --port 8120 --reload
```

#### macOS

```bash
conda activate agent-demo
python -m pip install -e ".[dev]"
python -m uvicorn deepagents_template.api:app --host 127.0.0.1 --port 8120 --reload
```

#### Linux

```bash
conda activate agent-demo
python -m pip install -e ".[dev]"
python -m uvicorn deepagents_template.api:app --host 127.0.0.1 --port 8120 --reload
```

### Option B: Scripted manual startup

#### Step 1: Bootstrap backend

Windows:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -InstallDevDependencies -IfNeeded
```

Windows, use the active interpreter explicitly:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -InstallDevDependencies -UseActivePython -IfNeeded
```

Windows, force a full reinstall:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -InstallDevDependencies
```

macOS:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
INSTALL_DEV_DEPENDENCIES=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

macOS, force the active interpreter:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
USE_ACTIVE_PYTHON=true INSTALL_DEV_DEPENDENCIES=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

macOS, force a full reinstall:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
INSTALL_DEV_DEPENDENCIES=true ./bootstrap.sh
```

Linux:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
INSTALL_DEV_DEPENDENCIES=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

Linux, force the active interpreter:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
USE_ACTIVE_PYTHON=true INSTALL_DEV_DEPENDENCIES=true BOOTSTRAP_IF_NEEDED=true ./bootstrap.sh
```

Linux, force a full reinstall:

```bash
cd quick-start
chmod +x bootstrap.sh start-api.sh
INSTALL_DEV_DEPENDENCIES=true ./bootstrap.sh
```

#### Step 2: Fill API settings in `.env`

Edit `.env` in the project root and fill:

```env
API_KEY=your-real-api-key
BASE_URL=https://your-openai-compatible-endpoint.example/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_chat_completions
AGENT_MODEL=your-coordinator-model
SUBAGENT_MODEL=your-worker-model
```

#### Step 3: Start backend only

Windows:

```powershell
cd quick-start
powershell -ExecutionPolicy Bypass -File .\start-api.ps1 --reload
```

macOS:

```bash
cd quick-start
chmod +x start-api.sh
./start-api.sh --reload
```

Linux:

```bash
cd quick-start
chmod +x start-api.sh
./start-api.sh --reload
```

#### Port conflict handling during startup

Both automatic startup and scripted backend startup now check whether the requested port is already occupied before `uvicorn` starts.

If the port is free:

- startup continues immediately

If the port is occupied:

- the script prints the occupied port
- the script prints the listener PID and process name when available
- the script explains exactly what inputs are accepted

You can then choose one of two actions:

- enter `yes`, `Yes`, or `Y` to stop the listed process and keep using the same port
- enter `no`, `NO`, or `N` to either provide another port number or cancel startup

If you choose another port:

- the script retries the port check with the new value
- startup continues only after a free port is confirmed

If there is no interaction for the timeout window:

- the script prints a timeout message
- the script automatically chooses a free port
- startup continues on that new port

The timeout is controlled by:

```env
PORT_PROMPT_TIMEOUT_SECONDS=15
```

The default is 15 seconds.

In startup paths that spawn a background backend process, the interactive resolution only happens once in the foreground. The background child process then uses the already confirmed port and fails fast if that port becomes occupied again before startup completes.

When the script switches to another port, it also updates `.runtime_startup.env` so later desktop startup and follow-up tooling can use the same effective port without changing your long-term `.env`.

#### Step 4: Start desktop shell

Windows:

```powershell
cd desktop
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File .\start-desktop.ps1
```

macOS:

```bash
cd desktop
chmod +x bootstrap.sh start-desktop.sh
./bootstrap.sh
./start-desktop.sh
```

macOS, override the frontend URL:

```bash
cd desktop
RASTER_SVG_FRONTEND_URL="http://127.0.0.1:8120/" ./start-desktop.sh
```

Linux:

```bash
cd desktop
chmod +x bootstrap.sh start-desktop.sh
./bootstrap.sh
./start-desktop.sh
```

Linux, override the frontend URL:

```bash
cd desktop
RASTER_SVG_FRONTEND_URL="http://127.0.0.1:8120/" ./start-desktop.sh
```

## Failure Feedback

The startup scripts now provide clearer guidance for common failure modes:

- Python version too old
- missing Python executable
- missing active Conda environment and missing `.venv`
- failed editable install
- missing `.env`
- empty `API_KEY`
- empty `BASE_URL`
- failed backend health check before desktop launch

Typical behavior:

- startup can continue when only API credentials are missing
- startup stops when the Python or Node environment is unusable
- desktop startup warns when backend health is unreachable and tells you to check `/health`

The startup summary now explicitly prints:

- startup mode
- backend URL
- environment mode such as Conda, virtualenv, nested virtualenv-on-Conda, or `.venv`
- Python executable path
- bootstrap mode such as `if-needed` or `always`
- runtime config file path
- port prompt timeout

## Default Access URLs

After backend startup, the shared frontend is usually available at:

- `http://127.0.0.1:8120/`
- `http://<server-ip>:8120/` when listening on `0.0.0.0`

Useful endpoints:

- `/`
- `/health`
- `/config/defaults`

## SAM-related Configuration

Relevant environment variables:

```env
RECOGNITION_BBOX_REFINE_MODE=llm
SAM_PROVIDER_MODE=remote
SAM_REMOTE_URL=
SAM_ENABLED=false
SAM_FALLBACK_TO_LLM=true
```

Current intent:

- `RECOGNITION_BBOX_REFINE_MODE=llm`: use the existing LLM-based bbox adjustment path
- `RECOGNITION_BBOX_REFINE_MODE=sam`: route to SAM refinement provider
- `RECOGNITION_BBOX_REFINE_MODE=hybrid`: allow mixed routing logic
- `SAM_PROVIDER_MODE=local`: reserved for local deployment
- `SAM_PROVIDER_MODE=remote`: reserved for remote service calls
- `SAM_ENABLED=false`: keep SAM path disabled by default for developer startup
- `SAM_FALLBACK_TO_LLM=true`: fall back to LLM refinement when SAM is unavailable

## Related Docs

- [README.md](./README.md)
- [README.developer.md](./README.developer.md)
- [quick-start/README.quick-start.md](./quick-start/README.quick-start.md)
- [desktop/README.desktop.md](./desktop/README.desktop.md)
