"""Audit, merge, and finalize staged object-generation contracts."""

from __future__ import annotations

from collections import Counter
import re

from deepagents_template.schemas import (
    ObjectCandidate,
    ObjectContractPatch,
    RegionContractEnrichmentResult,
    RegionRecognitionResult,
    RegionStructureRecognitionResult,
)


CONTRACT_FIELDS = ("generation_focus", "relative_position", "extent_hint", "fidelity_hints")
GENERIC_FIDELITY_GOALS = {
    "preserve the icon",
    "keep visual fidelity",
    "match the reference",
    "remain recognizable",
}
_NUMERIC_COORDINATE_PATTERN = re.compile(r"\b(?:x|y|width|height)\s*[:=]\s*-?\d|\(\s*-?\d+\s*,\s*-?\d+")


def _normalized_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().rstrip(".!").split())


def _fidelity_issues(object_id: str, object_type: str, hints) -> list[str]:
    if object_type == "icon" and hints is None:
        return ["fidelity_hints is required for an icon"]
    if hints is None or not hints.verify_required:
        return ["verify_required must be true for an icon"] if object_type == "icon" else []

    issues: list[str] = []
    if object_type == "icon" and hints.target_elements != [object_id]:
        issues.append(f'target_elements must equal ["{object_id}"]')
    elif object_type != "icon" and not hints.target_elements:
        issues.append("target_elements must name the owned symbolic content")
    if not hints.fidelity_goals:
        issues.append("fidelity_goals must contain at least one source-visible goal")
    elif any(_normalized_text(goal) in GENERIC_FIDELITY_GOALS for goal in hints.fidelity_goals):
        issues.append("fidelity_goals must name concrete visible properties")
    return issues


def _field_issues(object_id: str, object_type: str, field: str, value) -> list[str]:
    if field == "generation_focus":
        goals = [str(item).strip() for item in (value or []) if str(item).strip()]
        if not goals:
            return ["generation_focus must contain at least one concrete goal"]
        if len(goals) > 3:
            return ["generation_focus must contain at most three goals"]
        return []
    if field in {"relative_position", "extent_hint"}:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return [f"{field} must not be empty"]
        if _NUMERIC_COORDINATE_PATTERN.search(text.lower()):
            return [f"{field} must use semantic language rather than numeric coordinates"]
        return []
    if field == "fidelity_hints":
        return _fidelity_issues(object_id, object_type, value)
    return [f"unsupported contract field: {field}"]


def initialize_contracts(structure: RegionStructureRecognitionResult) -> RegionRecognitionResult:
    """Create the final recognition shape with empty contracts from frozen structure."""

    return RegionRecognitionResult(
        region_id=structure.region_id,
        observation=structure.observation,
        recognized_objects=[
            ObjectCandidate(
                object_id=obj.object_id,
                object_type=obj.object_type,
                description=obj.description,
                included_elements=obj.included_elements,
            )
            for obj in structure.recognized_objects
        ],
    )


def merge_contract_enrichment(
    structure: RegionStructureRecognitionResult,
    enrichment: RegionContractEnrichmentResult,
) -> tuple[RegionRecognitionResult, dict[str, str]]:
    """Merge unambiguous Stage-2 drafts without allowing structure changes."""

    recognition = initialize_contracts(structure)
    known_ids = {obj.object_id for obj in structure.recognized_objects}
    counts = Counter(update.object_id for update in enrichment.object_updates)
    updates = {update.object_id: update for update in enrichment.object_updates if counts[update.object_id] == 1}
    rejected: dict[str, str] = {}
    for object_id, count in counts.items():
        if object_id not in known_ids:
            rejected[object_id] = "object_id is not present in frozen structure"
        elif count != 1:
            rejected[object_id] = "duplicate contract updates were returned"

    merged_objects = []
    for obj in recognition.recognized_objects:
        update = updates.get(obj.object_id)
        if update is None or obj.object_id in rejected:
            merged_objects.append(obj)
            continue
        merged_objects.append(
            obj.model_copy(
                update={
                    field: getattr(update, field)
                    for field in CONTRACT_FIELDS
                    if getattr(update, field) is not None
                }
            )
        )
    return recognition.model_copy(update={"recognized_objects": merged_objects}), rejected


def audit_object_contracts(recognition: RegionRecognitionResult) -> list[dict]:
    """Return per-object, per-field Stage-2/3 contract defects."""

    issues: list[dict] = []
    for obj in recognition.recognized_objects:
        invalid_fields: list[str] = []
        validation_issues: list[str] = []
        for field in CONTRACT_FIELDS:
            field_issues = _field_issues(obj.object_id, obj.object_type, field, getattr(obj, field))
            if field_issues:
                invalid_fields.append(field)
                validation_issues.extend(field_issues)
        if invalid_fields:
            accepted_contract = {
                field: getattr(obj, field)
                for field in CONTRACT_FIELDS
                if field not in invalid_fields
            }
            issues.append(
                {
                    "object_id": obj.object_id,
                    "fixed_structure": {
                        "object_type": obj.object_type,
                        "description": obj.description,
                        "included_elements": obj.included_elements,
                    },
                    "accepted_contract": {
                        key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
                        for key, value in accepted_contract.items()
                    },
                    "invalid_fields": invalid_fields,
                    "validation_issues": validation_issues,
                }
            )
    return issues


def merge_contract_patches(
    recognition: RegionRecognitionResult,
    *,
    audit_issues: list[dict],
    patches: list[ObjectContractPatch],
) -> tuple[RegionRecognitionResult, dict[str, list[str]], dict[str, str]]:
    """Apply valid Stage-3 fields independently and preserve accepted fields."""

    requested_fields = {item["object_id"]: set(item["invalid_fields"]) for item in audit_issues}
    counts = Counter(patch.object_id for patch in patches)
    patches_by_id = {patch.object_id: patch for patch in patches if counts[patch.object_id] == 1}
    rejected: dict[str, str] = {}
    applied: dict[str, list[str]] = {}

    for object_id, count in counts.items():
        if object_id not in requested_fields:
            rejected[object_id] = "patch was not requested"
        elif count != 1:
            rejected[object_id] = "duplicate patches were returned"

    updated_objects = []
    for obj in recognition.recognized_objects:
        patch = patches_by_id.get(obj.object_id)
        if patch is None or obj.object_id in rejected:
            updated_objects.append(obj)
            continue
        update_payload = {}
        for field in CONTRACT_FIELDS:
            value = getattr(patch, field)
            if value is None:
                continue
            if field not in requested_fields[obj.object_id]:
                rejected[f"{obj.object_id}.{field}"] = "field was already accepted and not requested"
                continue
            field_issues = _field_issues(obj.object_id, obj.object_type, field, value)
            if field_issues:
                rejected[f"{obj.object_id}.{field}"] = "; ".join(field_issues)
                continue
            update_payload[field] = value
            applied.setdefault(obj.object_id, []).append(field)
        updated_objects.append(obj.model_copy(update=update_payload))
    return recognition.model_copy(update={"recognized_objects": updated_objects}), applied, rejected


def degrade_unresolved_contracts(
    recognition: RegionRecognitionResult,
    audit_issues: list[dict],
) -> tuple[RegionRecognitionResult, dict[str, dict]]:
    """Clear invalid optional structures and retain objects for downstream work."""

    unresolved = {item["object_id"]: item for item in audit_issues}
    status: dict[str, dict] = {}
    updated_objects = []
    for obj in recognition.recognized_objects:
        issue = unresolved.get(obj.object_id)
        if issue is None:
            updated_objects.append(obj)
            continue
        invalid_fields = list(issue["invalid_fields"])
        update = {"fidelity_hints": None} if "fidelity_hints" in invalid_fields else {}
        updated_objects.append(obj.model_copy(update=update))
        status[obj.object_id] = {
            "status": "degraded",
            "unavailable_fields": invalid_fields,
            "validation_issues": issue["validation_issues"],
        }
    return recognition.model_copy(update={"recognized_objects": updated_objects}), status
