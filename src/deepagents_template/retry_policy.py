"""Central retry-limit resolution and typed workflow retry accounting."""

from __future__ import annotations

from enum import StrEnum
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RetryLimits(BaseModel):
    """Resolved total-attempt and repair-round limits for one frozen run."""

    model_config = ConfigDict(frozen=True)

    transport_max_attempts: int = Field(ge=1)
    response_validation_max_attempts: int = Field(ge=1)
    bbox_initial_localization_max_attempts: int = Field(ge=1)
    bbox_refinement_max_rounds: int = Field(ge=0)
    region_repair_max_attempts: int = Field(ge=0)
    object_repair_max_attempts: int = Field(ge=0)
    fidelity_verification_max_attempts: int = Field(ge=1)
    fidelity_verification_uses_independent_budget: bool
    fusion_repair_max_attempts: int = Field(ge=0)
    run_model_call_budget: int = Field(ge=0)
    bbox_global_stagnation_max_rounds: int = Field(ge=1)

    def model_retry_limit(self) -> int:
        """Translate total transport attempts to the SDK's extra-retry convention."""

        return max(self.transport_max_attempts - 1, 0)

    def model_dump_for_snapshot(self) -> dict[str, int | bool]:
        return dict(self.model_dump(mode="json"))


class RetryKind(StrEnum):
    BBOX_REFINEMENT = "bbox_refinement"
    REGION_REPAIR = "region_repair"
    OBJECT_REPAIR = "object_repair"
    FIDELITY_VERIFICATION = "fidelity_verification"


class RetryKey(BaseModel):
    """Structured workflow-retry identity with legacy-string compatibility."""

    model_config = ConfigDict(frozen=True)

    kind: RetryKind
    region_id: str
    object_id: str | None = None

    def legacy_name(self) -> str:
        if self.kind == RetryKind.BBOX_REFINEMENT:
            return f"bbox:recognition:{self.region_id}:round"
        if self.kind == RetryKind.REGION_REPAIR:
            return f"region:{self.region_id}:repair"
        if self.kind == RetryKind.OBJECT_REPAIR:
            return f"object:{self.region_id}:{self.object_id or ''}:repair"
        return f"fidelity:{self.region_id}:verification"


class RetryTracker:
    """Thread-safe per-task attempt tracker backed by legacy persisted task names."""

    def __init__(self, limits: RetryLimits) -> None:
        self.limits = limits
        self._lock = Lock()
        self._counts: dict[str, int] = {}
        self._exhausted: set[str] = set()

    def limit_for(self, task_name: str) -> int:
        if task_name.startswith("bbox:"):
            return self.limits.bbox_refinement_max_rounds
        if task_name.startswith("object:"):
            return self.limits.object_repair_max_attempts
        if task_name.startswith("fidelity:"):
            return max(self.limits.fidelity_verification_max_attempts - 1, 0)
        return self.limits.region_repair_max_attempts

    def begin(self, task_name: str) -> bool:
        limit = self.limit_for(task_name)
        with self._lock:
            used = self._counts.get(task_name, 0)
            if used >= limit:
                self._exhausted.add(task_name)
                return False
            self._counts[task_name] = used + 1
            return True

    def state(self, task_name: str) -> dict[str, int | str | bool]:
        with self._lock:
            used = self._counts.get(task_name, 0)
            limit = self.limit_for(task_name)
            return {
                "task": task_name,
                "limit": limit,
                "used": used,
                "exhausted": used >= limit or task_name in self._exhausted,
            }

    def exhausted(self, task_name: str) -> bool:
        return bool(self.state(task_name)["exhausted"])

    def counts_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def exhausted_snapshot(self) -> set[str]:
        with self._lock:
            return set(self._exhausted)

    def restore(self, *, counts: dict[str, int], exhausted: list[str] | set[str]) -> None:
        with self._lock:
            self._counts = dict(counts)
            self._exhausted = set(exhausted)

    def known_task_names(self) -> set[str]:
        with self._lock:
            return set(self._counts) | self._exhausted

    def mark_exhausted(self, task_name: str) -> None:
        with self._lock:
            self._exhausted.add(task_name)


def resolve_retry_limits(settings: Any, request: Any) -> RetryLimits:
    """Resolve new total-attempt parameters with legacy request/config fallbacks."""

    return RetryLimits(
        transport_max_attempts=settings.resolved_transport_max_attempts(
            getattr(request, "transport_max_attempts", None),
            getattr(request, "max_retries", None),
        ),
        response_validation_max_attempts=settings.resolved_response_validation_max_attempts(
            getattr(request, "response_validation_max_attempts", None)
        ),
        bbox_initial_localization_max_attempts=settings.resolved_bbox_initial_localization_max_attempts(
            getattr(request, "bbox_initial_localization_max_attempts", None)
        ),
        bbox_refinement_max_rounds=settings.resolved_bbox_refinement_max_rounds(
            getattr(request, "bbox_refinement_max_rounds", None),
            getattr(request, "max_retry", None),
        ),
        region_repair_max_attempts=settings.resolved_region_repair_max_attempts(
            getattr(request, "region_repair_max_attempts", None),
            getattr(request, "max_retry", None),
        ),
        object_repair_max_attempts=settings.resolved_object_repair_max_attempts(
            getattr(request, "object_repair_max_attempts", None),
            getattr(request, "max_retry", None),
        ),
        fidelity_verification_max_attempts=settings.resolved_fidelity_verification_max_attempts(
            getattr(request, "fidelity_verification_max_attempts", None)
        ),
        fidelity_verification_uses_independent_budget=settings.resolved_fidelity_verification_independent_budget(
            getattr(request, "fidelity_verification_independent_budget", None)
        ),
        fusion_repair_max_attempts=settings.resolved_fusion_repair_max_attempts(
            getattr(request, "fusion_repair_max_attempts", None),
            getattr(request, "fusion_max_retry", None),
        ),
        run_model_call_budget=settings.resolved_run_model_call_budget(
            getattr(request, "run_model_call_budget", None),
            getattr(request, "max_budget", None),
        ),
        bbox_global_stagnation_max_rounds=settings.resolved_bbox_global_stagnation_max_rounds(
            getattr(request, "bbox_global_stagnation_max_rounds", None),
            getattr(request, "bbox_global_stagnation_rounds", None),
        ),
    )
