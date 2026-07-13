"""Overview: Central environment-backed settings and runtime option resolution."""

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_app_config_dir() -> Path:
    configured_dir = os.getenv("APP_CONFIG_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser()
    return PROJECT_ROOT


APP_CONFIG_DIR = _resolve_app_config_dir()
RUNTIME_OVERRIDE_PATH = APP_CONFIG_DIR / ".frontend_runtime_overrides.json"

load_dotenv(PROJECT_ROOT / ".env")
if APP_CONFIG_DIR != PROJECT_ROOT:
    load_dotenv(APP_CONFIG_DIR / ".env", override=True)
RUNTIME_OVERRIDE_FIELDS = {
    "api_key",
    "base_url",
    "api_provider",
    "api_format",
    "max_retries",
    "workflow_mode",
    "region_processing_mode",
    "region_concurrency",
    "bbox_issue_concurrency",
    "bbox_issue_stagnation_rounds",
    "bbox_global_stagnation_rounds",
    "agent_model",
    "subagent_model",
    "agent_name",
    "use_previous_response_id",
    "max_retry",
    "fusion_max_retry",
    "max_budget",
    "supervisor_memory_enabled",
    "supervisor_memory_persist_enabled",
    "strategy_enabled",
    "recognition_bbox_refine_mode",
    "sam_provider_mode",
    "sam_remote_url",
    "sam_enabled",
    "sam_fallback_to_llm",
}


def load_runtime_overrides() -> dict:
    """Load persisted frontend runtime overrides from disk."""

    if not RUNTIME_OVERRIDE_PATH.is_file():
        return {}
    try:
        payload = json.loads(RUNTIME_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in RUNTIME_OVERRIDE_FIELDS if key in payload}


def save_runtime_overrides(overrides: dict) -> dict:
    """Persist normalized runtime overrides and return the stored payload."""

    normalized = {key: overrides[key] for key in RUNTIME_OVERRIDE_FIELDS if key in overrides}
    RUNTIME_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = RUNTIME_OVERRIDE_PATH.with_name(f"{RUNTIME_OVERRIDE_PATH.name}.tmp")
    temp_path.write_text(
        json.dumps(normalized, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(RUNTIME_OVERRIDE_PATH)
    return normalized


class Settings(BaseSettings):
    """Application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=str(APP_CONFIG_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(
        default="",
        validation_alias=AliasChoices("API_KEY", "OPENAI_API_KEY", "POE_API_KEY"),
    )
    base_url: str | None = Field(default=None, validation_alias=AliasChoices("BASE_URL", "OPENAI_BASE_URL"))
    api_provider: str = Field(default="openai_compatible", alias="API_PROVIDER")
    api_format: str = Field(default="openai_responses", alias="API_FORMAT")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="shape-studio", alias="LANGSMITH_PROJECT")

    agent_model: str = Field(default="gpt-5.4-medium", alias="AGENT_MODEL")
    subagent_model: str = Field(default="gpt-5.4-medium", alias="SUBAGENT_MODEL")
    agent_name: str = Field(default="shape-studio-coordinator", alias="AGENT_NAME")
    use_previous_response_id: bool = Field(default=False, alias="USE_PREVIOUS_RESPONSE_ID")
    max_retries: int = Field(default=2, validation_alias=AliasChoices("MAX_RETRIES", "OPENAI_MAX_RETRIES"))

    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8120, alias="APP_PORT")
    require_approval_for_task_creation: bool = Field(
        default=False,
        alias="REQUIRE_APPROVAL_FOR_TASK_CREATION",
    )
    run_artifacts_dir: str = Field(default="artifacts/runs", alias="RUN_ARTIFACTS_DIR")
    default_user_input: str = Field(default="Convert this image into SVG format", alias="DEFAULT_USER_INPUT")
    max_retry: int = Field(default=5, ge=0, alias="MAX_RETRY")
    fusion_max_retry: int = Field(default=3, ge=0, alias="FUSION_MAX_RETRY")
    max_budget: int = Field(default=80, ge=0, alias="MAX_BUDGET")
    supervisor_memory_enabled: bool = Field(default=False, alias="SUPERVISOR_MEMORY_ENABLED")
    supervisor_memory_persist_enabled: bool = Field(default=True, alias="SUPERVISOR_MEMORY_PERSIST_ENABLED")
    strategy_enabled: bool = Field(default=True, alias="STRATEGY_ENABLED")
    recognition_bbox_refine_mode: str = Field(default="llm", alias="RECOGNITION_BBOX_REFINE_MODE")
    sam_provider_mode: str = Field(default="remote", alias="SAM_PROVIDER_MODE")
    sam_remote_url: str | None = Field(default=None, alias="SAM_REMOTE_URL")
    sam_enabled: bool = Field(default=False, alias="SAM_ENABLED")
    sam_fallback_to_llm: bool = Field(default=True, alias="SAM_FALLBACK_TO_LLM")
    default_region_processing_mode: str = Field(default="parallel", alias="REGION_PROCESSING_MODE")
    default_region_concurrency: int = Field(default=8, alias="REGION_CONCURRENCY")
    default_bbox_issue_concurrency: int = Field(default=2, alias="BBOX_ISSUE_CONCURRENCY")
    bbox_issue_stagnation_rounds: int = Field(default=3, ge=1, alias="BBOX_ISSUE_STAGNATION_ROUNDS")
    bbox_global_stagnation_rounds: int = Field(default=2, ge=1, alias="BBOX_GLOBAL_STAGNATION_ROUNDS")
    default_workflow_mode: str = Field(default="region_object", alias="WORKFLOW_MODE")

    def _runtime_override(self, key: str):
        return load_runtime_overrides().get(key)

    def resolved_api_provider(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("api_provider")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.api_provider

    def resolved_api_key(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("api_key")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.api_key

    def resolved_base_url(self, override: str | None = None) -> str | None:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("base_url")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.base_url

    def resolved_api_format(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("api_format")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.api_format.strip()

    def resolved_max_retries(self, override: int | None = None) -> int:
        if override is not None:
            return max(0, int(override))
        runtime_override = self._runtime_override("max_retries")
        if runtime_override is not None:
            return max(0, int(runtime_override))
        return self.max_retries

    def resolved_user_input(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        return self.default_user_input.strip()

    def resolved_agent_model(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("agent_model")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.agent_model

    def resolved_subagent_model(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("subagent_model")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.subagent_model

    def resolved_agent_name(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        runtime_override = self._runtime_override("agent_name")
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.agent_name

    def resolved_use_previous_response_id(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("use_previous_response_id")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.use_previous_response_id

    def resolved_region_processing_mode(self, override: str | None = None) -> str:
        runtime_override = self._runtime_override("region_processing_mode")
        value = (
            override.strip()
            if isinstance(override, str) and override.strip()
            else runtime_override.strip()
            if isinstance(runtime_override, str) and runtime_override.strip()
            else self.default_region_processing_mode
        )
        if value not in {"serial", "parallel"}:
            raise ValueError("REGION_PROCESSING_MODE must be either 'serial' or 'parallel'.")
        return value

    def resolved_region_concurrency(
        self,
        mode_override: str | None = None,
        concurrency_override: int | None = None,
    ) -> int:
        mode = self.resolved_region_processing_mode(mode_override)
        if mode == "serial":
            return 1
        runtime_override = self._runtime_override("region_concurrency")
        value = (
            concurrency_override
            if concurrency_override is not None
            else runtime_override
            if runtime_override is not None
            else self.default_region_concurrency
        )
        return max(1, min(int(value), 16))

    def resolved_workflow_mode(self, override: str | None = None) -> str:
        runtime_override = self._runtime_override("workflow_mode")
        value = (
            override.strip()
            if isinstance(override, str) and override.strip()
            else runtime_override.strip()
            if isinstance(runtime_override, str) and runtime_override.strip()
            else self.default_workflow_mode
        )
        if value not in {"initial_only", "region", "region_object"}:
            raise ValueError(
                "WORKFLOW_MODE must be one of 'initial_only', 'region', or 'region_object'."
            )
        return value

    def resolved_recognition_bbox_refine_mode(self, override: str | None = None) -> str:
        runtime_override = self._runtime_override("recognition_bbox_refine_mode")
        value = (
            override.strip()
            if isinstance(override, str) and override.strip()
            else runtime_override.strip()
            if isinstance(runtime_override, str) and runtime_override.strip()
            else self.recognition_bbox_refine_mode
        )
        if value not in {"llm", "sam", "hybrid"}:
            raise ValueError("RECOGNITION_BBOX_REFINE_MODE must be one of 'llm', 'sam', or 'hybrid'.")
        return value

    def resolved_sam_provider_mode(self, override: str | None = None) -> str:
        runtime_override = self._runtime_override("sam_provider_mode")
        value = (
            override.strip()
            if isinstance(override, str) and override.strip()
            else runtime_override.strip()
            if isinstance(runtime_override, str) and runtime_override.strip()
            else self.sam_provider_mode
        )
        if value not in {"local", "remote"}:
            raise ValueError("SAM_PROVIDER_MODE must be either 'local' or 'remote'.")
        return value

    def resolved_sam_remote_url(self, override: str | None = None) -> str | None:
        runtime_override = self._runtime_override("sam_remote_url")
        if isinstance(override, str) and override.strip():
            return override.strip()
        if isinstance(runtime_override, str) and runtime_override.strip():
            return runtime_override.strip()
        return self.sam_remote_url

    def resolved_sam_enabled(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("sam_enabled")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.sam_enabled

    def resolved_sam_fallback_to_llm(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("sam_fallback_to_llm")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.sam_fallback_to_llm

    def resolved_bbox_issue_concurrency(self, override: int | None = None) -> int:
        runtime_override = self._runtime_override("bbox_issue_concurrency")
        value = (
            override
            if override is not None
            else runtime_override
            if runtime_override is not None
            else self.default_bbox_issue_concurrency
        )
        return max(1, min(int(value), 8))

    def resolved_bbox_issue_stagnation_rounds(self, override: int | None = None) -> int:
        runtime_override = self._runtime_override("bbox_issue_stagnation_rounds")
        value = (
            override
            if override is not None
            else runtime_override
            if runtime_override is not None
            else self.bbox_issue_stagnation_rounds
        )
        return max(1, min(int(value), 8))

    def resolved_bbox_global_stagnation_rounds(self, override: int | None = None) -> int:
        runtime_override = self._runtime_override("bbox_global_stagnation_rounds")
        value = (
            override
            if override is not None
            else runtime_override
            if runtime_override is not None
            else self.bbox_global_stagnation_rounds
        )
        return max(1, min(int(value), 8))


    def resolved_max_retry(self, override: int | None = None) -> int:
        if override is not None:
            return max(0, int(override))
        runtime_override = self._runtime_override("max_retry")
        if runtime_override is not None:
            return max(0, int(runtime_override))
        return self.max_retry

    def resolved_fusion_max_retry(self, override: int | None = None) -> int:
        if override is not None:
            return max(0, int(override))
        runtime_override = self._runtime_override("fusion_max_retry")
        if runtime_override is not None:
            return max(0, int(runtime_override))
        return self.fusion_max_retry

    def resolved_max_budget(self, override: int | None = None) -> int:
        if override is not None:
            return max(0, int(override))
        runtime_override = self._runtime_override("max_budget")
        if runtime_override is not None:
            return max(0, int(runtime_override))
        return self.max_budget

    def resolved_supervisor_memory_enabled(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("supervisor_memory_enabled")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.supervisor_memory_enabled

    def resolved_supervisor_memory_persist_enabled(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("supervisor_memory_persist_enabled")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.supervisor_memory_persist_enabled

    def resolved_strategy_enabled(self, override: bool | None = None) -> bool:
        if override is not None:
            return bool(override)
        runtime_override = self._runtime_override("strategy_enabled")
        if runtime_override is not None:
            return bool(runtime_override)
        return self.strategy_enabled

    def resolved_run_artifacts_dir(self) -> Path:
        path = Path(self.run_artifacts_dir)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
