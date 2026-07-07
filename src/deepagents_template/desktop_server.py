"""Desktop-packaged FastAPI server entrypoint."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def _ensure_packaged_runtime_dirs() -> None:
    app_config_dir = os.getenv("APP_CONFIG_DIR", "").strip()
    if app_config_dir:
        Path(app_config_dir).mkdir(parents=True, exist_ok=True)

    artifacts_dir = os.getenv("RUN_ARTIFACTS_DIR", "").strip()
    if artifacts_dir:
        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)


def main() -> None:
    _ensure_packaged_runtime_dirs()
    host = os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("APP_PORT", "8120").strip() or "8120")
    from deepagents_template.api import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
