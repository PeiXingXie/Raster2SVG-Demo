"""Concrete object bbox refinement providers."""

from __future__ import annotations

import json
from pathlib import Path

from deepagents_template.atomic_files import atomic_write_text
from deepagents_template.schemas import (
    BboxQualityIssue,
    ObjectBboxRefinementResult,
    RegionRecognitionResult,
)


class LLMRecognitionBboxRefiner:
    """Adapter that preserves the current LLM-driven bbox refinement behavior."""

    def __init__(self, bbox_worker) -> None:
        self.bbox_worker = bbox_worker

    @staticmethod
    def _recognition_objects_payload(recognition: RegionRecognitionResult) -> list[dict]:
        return [
            {
                "object_id": obj.object_id,
                "object_type": obj.object_type,
                "description": obj.description,
                "generation_focus": obj.generation_focus,
                "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
            }
            for obj in recognition.recognized_objects
        ]

    def refine_issue_object(
        self,
        *,
        crop_path: Path,
        overlay_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        issue: BboxQualityIssue,
        validation_feedback: list[dict] | None,
        output_dir: Path,
        memory_summary: dict | None = None,
        exempted_issue_ids: list[str] | None = None,
        recently_resolved_issue_ids: list[str] | None = None,
    ) -> ObjectBboxRefinementResult:
        result, raw_text = self.bbox_worker.run_recognition(
            crop_path=crop_path,
            overlay_path=overlay_path,
            region=region,
            recognized_objects=self._recognition_objects_payload(recognition),
            validation_feedback=[],
            memory_summary=memory_summary,
            exempted_issue_ids=exempted_issue_ids,
            recently_resolved_issue_ids=recently_resolved_issue_ids,
        )
        focused_issues = [item for item in result.issues if item.target_id == issue.target_id]
        chosen_issue = focused_issues[0] if focused_issues else issue
        chosen_update = next(
            (item for item in result.adjusted_object_bboxes if item.target_id == issue.target_id),
            None,
        )
        return ObjectBboxRefinementResult(
            provider="llm_recognition_bbox_adjustment",
            mode="llm",
            status="applied" if chosen_update is not None else "skipped",
            target_id=issue.target_id,
            bbox=chosen_update.bbox if chosen_update is not None else None,
            reason=result.overview or chosen_issue.reason,
            issue=chosen_issue,
            raw_text=raw_text,
            artifacts={
                "worker_result": result.model_dump(mode="json"),
                "adjustment_type": result.adjustment_type,
                "target_ids": list(result.target_ids),
            },
        )


class SamLocalRecognitionBboxRefiner:
    """Placeholder for a future local SAM-backed object bbox refiner."""

    def refine_issue_object(
        self,
        *,
        crop_path: Path,
        overlay_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        issue: BboxQualityIssue,
        validation_feedback: list[dict] | None,
        output_dir: Path,
        memory_summary: dict | None = None,
        exempted_issue_ids: list[str] | None = None,
        recently_resolved_issue_ids: list[str] | None = None,
    ) -> ObjectBboxRefinementResult:
        return ObjectBboxRefinementResult(
            provider="sam_local",
            mode="sam_local",
            status="unavailable",
            target_id=issue.target_id,
            reason="sam local provider is not implemented for this environment",
            issue=issue,
            artifacts={
                "region_id": region.get("region_id"),
                "crop_path": str(crop_path),
                "overlay_path": str(overlay_path),
            },
        )


class SamRemoteRecognitionBboxRefiner:
    """Remote SAM-backed object bbox refiner.

    The current implementation provides a real integration point and gracefully reports
    unavailability when the remote endpoint is absent or errors.
    """

    def __init__(self, *, remote_url: str | None) -> None:
        self.remote_url = remote_url

    @staticmethod
    def _target_payload(recognition: RegionRecognitionResult, issue: BboxQualityIssue) -> dict | None:
        for obj in recognition.recognized_objects:
            if obj.object_id == issue.target_id:
                return {
                    "object_id": obj.object_id,
                    "object_type": obj.object_type,
                    "description": obj.description,
                    "generation_focus": list(obj.generation_focus),
                    "bbox": obj.bbox.model_dump(mode="json") if obj.bbox else None,
                }
        return None

    def refine_issue_object(
        self,
        *,
        crop_path: Path,
        overlay_path: Path,
        region: dict,
        recognition: RegionRecognitionResult,
        issue: BboxQualityIssue,
        validation_feedback: list[dict] | None,
        output_dir: Path,
        memory_summary: dict | None = None,
        exempted_issue_ids: list[str] | None = None,
        recently_resolved_issue_ids: list[str] | None = None,
    ) -> ObjectBboxRefinementResult:
        request_payload = {
            "region": region,
            "issue": issue.model_dump(mode="json"),
            "target_object": self._target_payload(recognition, issue),
            "validation_feedback": [],
            "memory_summary": memory_summary,
            "recently_resolved_issue_ids": recently_resolved_issue_ids or [],
            "exempted_issue_ids": exempted_issue_ids or [],
        }
        request_path = output_dir / "sam_remote_request.json"
        atomic_write_text(request_path, json.dumps(request_payload, ensure_ascii=False, indent=2))
        if not self.remote_url:
            return ObjectBboxRefinementResult(
                provider="sam_remote",
                mode="sam_remote",
                status="unavailable",
                target_id=issue.target_id,
                reason="sam remote url is not configured",
                issue=issue,
                artifacts={"request_path": str(request_path)},
            )

        try:
            from urllib import request as urllib_request
            from urllib.error import URLError, HTTPError

            image_bytes = crop_path.read_bytes()
            body = json.dumps(
                {
                    **request_payload,
                    "image_base64": image_bytes.hex(),
                    "image_encoding": "hex",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib_request.Request(
                self.remote_url.rstrip("/") + "/refine-object-bbox",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=30) as response:
                raw_text = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            return ObjectBboxRefinementResult(
                provider="sam_remote",
                mode="sam_remote",
                status="failed",
                target_id=issue.target_id,
                reason=f"sam remote request failed: {exc}",
                issue=issue,
                artifacts={"request_path": str(request_path)},
            )

        response_path = output_dir / "sam_remote_response_raw.json"
        atomic_write_text(response_path, raw_text)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return ObjectBboxRefinementResult(
                provider="sam_remote",
                mode="sam_remote",
                status="failed",
                target_id=issue.target_id,
                reason="sam remote response was not valid json",
                issue=issue,
                raw_text=raw_text,
                artifacts={"request_path": str(request_path), "response_path": str(response_path)},
            )

        bbox_payload = payload.get("bbox")
        confidence = payload.get("confidence")
        if not isinstance(bbox_payload, dict):
            return ObjectBboxRefinementResult(
                provider="sam_remote",
                mode="sam_remote",
                status="skipped",
                target_id=issue.target_id,
                reason=str(payload.get("reason") or "sam remote returned no bbox"),
                issue=issue,
                raw_text=raw_text,
                artifacts={"request_path": str(request_path), "response_path": str(response_path)},
            )

        return ObjectBboxRefinementResult(
            provider="sam_remote",
            mode="sam_remote",
            status="applied",
            target_id=issue.target_id,
            bbox=bbox_payload,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            reason=str(payload.get("reason") or "sam remote refined the target bbox"),
            issue=issue,
            raw_text=raw_text,
            artifacts={"request_path": str(request_path), "response_path": str(response_path)},
        )


class HybridRecognitionBboxRefiner:
    """Try a SAM-backed refiner first, then fall back to the existing LLM path."""

    def __init__(self, *, primary_refiner, fallback_refiner) -> None:
        self.primary_refiner = primary_refiner
        self.fallback_refiner = fallback_refiner

    def refine_issue_object(self, **kwargs) -> ObjectBboxRefinementResult:
        result = self.primary_refiner.refine_issue_object(**kwargs)
        if result.status in {"applied", "skipped"}:
            return result
        fallback_result = self.fallback_refiner.refine_issue_object(**kwargs)
        fallback_artifacts = dict(fallback_result.artifacts)
        fallback_artifacts["fallback_from"] = {
            "provider": result.provider,
            "mode": result.mode,
            "status": result.status,
            "reason": result.reason,
        }
        return fallback_result.model_copy(update={"artifacts": fallback_artifacts})
