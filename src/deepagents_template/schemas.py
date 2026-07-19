"""Overview: Pydantic schemas for requests, regions, reviews, runs, and UI state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from deepagents_template.taxonomy import ObjectIssueFamily


OBJECT_TYPE_ALIASES = {
    "annotation": "text",
    "annotations": "text",
    "background": "background",
    "backgrounds": "background",
    "backdrop": "background",
    "panel_background": "background",
    "fill": "background",
    "caption": "text",
    "label": "text",
    "labels": "text",
    "legend": "text",
    "legend_label": "text",
    "merge_label": "text",
    "problem_statement": "text",
    "statement": "text",
    "rounded_box": "container",
    "rounded_boxes": "container",
    "box": "container",
    "boxes": "container",
    "error_mark": "icon",
    "check_mark": "icon",
    "warning_mark": "icon",
    "icons": "icon",
    "marks": "icon",
    "diagram": "diagram",
    "shape": "container",
    "shapes": "container",
    "node": "container",
    "nodes": "container",
    "flowchart_node": "container",
    "flowchart_nodes": "container",
    "connector": "connector",
    "connectors": "connector",
    "arrow": "connector",
    "arrows": "connector",
    "arrowhead": "connector",
    "arrowheads": "connector",
    "line": "connector",
    "lines": "connector",
    "divider": "connector",
    "dividers": "connector",
    "text_box": "text",
    "chart": "diagram",
    "graph": "diagram",
    "plot": "diagram",
    "axis": "diagram",
    "axes": "diagram",
    "data_mark": "diagram",
    "data_marks": "diagram",
    "barcode": "fig",
    "bar_code": "fig",
    "qrcode": "fig",
    "qr_code": "fig",
    "qr": "fig",
    "natural_image": "fig",
    "photo": "fig",
    "figure": "fig",
    "image": "fig",
    "picture": "fig",
}

OBJECT_TYPES = {"background", "icon", "text", "container", "connector", "diagram", "fig"}
BBOX_ISSUE_CODES = (
    "target_not_contained",
    "target_clipped",
    "excessive_padding",
    "off_center",
    "invalid_bbox",
)
BBOX_ISSUE_EDGES = ("left", "top", "right", "bottom")
CHECKLIST_SCOPE_ALIASES = {
    "common": "common",
    "global": "common",
    "region": "region",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_enum_token(value: str, aliases: dict[str, str]) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return aliases.get(normalized, normalized)


def _normalize_presence_flag(value: object) -> Literal["Y", "N"]:
    if value is None:
        return "N"
    text = str(value).strip().upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "Y"
    return "N"


def _normalize_object_type(value: str) -> str | None:
    normalized = _normalize_enum_token(value, OBJECT_TYPE_ALIASES)
    if normalized in OBJECT_TYPES:
        return normalized
    if any(token in normalized for token in ("background", "backdrop", "panel", "halo", "shadow", "fill")):
        return "background"
    if any(token in normalized for token in ("text", "label", "caption", "annotation", "statement", "legend")):
        return "text"
    if any(token in normalized for token in ("icon", "mark", "badge", "symbol")):
        return "icon"
    if any(token in normalized for token in ("arrow", "connector", "line", "edge", "divider")):
        return "connector"
    if any(token in normalized for token in ("node", "box", "shape", "flow", "process", "decision")):
        return "container"
    if any(token in normalized for token in ("chart", "plot", "axis", "graph", "diagram")):
        return "diagram"
    if any(token in normalized for token in ("fig", "figure", "image", "picture", "photo", "barcode", "qr")):
        return "fig"
    return None


def _normalize_bbox_issue_edges(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [
            item.strip()
            for item in value.replace("/", ",").replace("|", ",").replace(";", ",").split(",")
        ]
    elif isinstance(value, list):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = [str(value).strip()]
    expanded: list[str] = []
    for item in raw_items:
        token = item.lower().replace("-", "_").replace(" ", "_")
        if token in BBOX_ISSUE_EDGES:
            expanded.append(token)
    ordered: list[str] = []
    for edge in BBOX_ISSUE_EDGES:
        if edge in expanded and edge not in ordered:
            ordered.append(edge)
    return ordered


def _normalize_bbox_issue_code(value: object, *, criterion: str = "", reason: str = "") -> str:
    text = " ".join(
        part
        for part in [
            str(value or ""),
            criterion,
            reason,
        ]
        if part
    ).strip().lower()
    token = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
    )
    token = "_".join(part for part in token.split("_") if part)
    if token in BBOX_ISSUE_CODES:
        return token

    haystack = text.replace("-", "_")
    if any(word in haystack for word in ("invalid", "malformed", "missing_bbox", "bbox_missing", "no_bbox")):
        return "invalid_bbox"
    if any(word in haystack for word in ("off_center", "offcenter", "miscenter", "not_centered", "biased")):
        return "off_center"
    if any(
        word in haystack
        for word in (
            "padding",
            "overreach",
            "over_reach",
            "oversized",
            "too_large",
            "too big",
            "includes_unrelated",
            "unrelated content",
            "spills",
            "spill",
        )
    ):
        return "excessive_padding"
    if any(
        word in haystack
        for word in (
            "not_contained",
            "undercovered",
            "under_covered",
            "outside",
            "missing_content",
            "omitted",
            "falls outside",
            "leaves",
        )
    ):
        return "target_not_contained"
    if any(
        word in haystack
        for word in (
            "clip",
            "clipped",
            "cut",
            "truncat",
            "intersect",
            "touch",
            "pressed",
            "too_tight",
            "tight",
            "edge",
        )
    ):
        return "target_clipped"
    return "target_clipped"


class ChecklistItem(BaseModel):
    """A single acceptance criterion for raster-to-SVG conversion."""

    item_id: str = Field(description="Stable checklist identifier, for example C1.")
    scope: Literal["common", "region"] = Field(
        description="Checklist scope. Common applies across regions within a stage, region targets one region.",
    )
    criterion: str = Field(description="Concrete acceptance rule that can be checked later.")
    region_id: str | None = Field(default=None, description="Target region_id for region-scoped checks.")

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data: object) -> object:
        if isinstance(data, dict):
            scope = data.get("scope", data.get("level"))
            if isinstance(scope, str):
                data["scope"] = _normalize_enum_token(scope, CHECKLIST_SCOPE_ALIASES)
            data["criterion"] = " ".join(str(data.get("criterion", "")).strip().split())
            legacy_level = data.get("level")
            if legacy_level in {"object", "final"}:
                data["level"] = "common"
            if not data.get("check_type"):
                text = " ".join(str(data.get(key, "")) for key in ("title", "criterion")).lower()
                awareness_tokens = (
                    "exist",
                    "complete",
                    "completeness",
                    "coverage",
                    "include",
                    "present",
                    "represented",
                    "reasonable",
                    "划分",
                    "完整",
                    "存在",
                    "覆盖",
                )
                data["check_type"] = (
                    "awareness" if any(token in text for token in awareness_tokens) else "quality"
                )
            title = data.pop("title", None)
            criterion = data.get("criterion")
            if title and criterion and str(title) not in str(criterion):
                data["criterion"] = f"{title}: {criterion}"
            elif title and not criterion:
                data["criterion"] = str(title)
            data.pop("applies_to", None)
            data.pop("required", None)
        return data

    @model_validator(mode="after")
    def validate_scope_targets(self):
        if self.scope == "common":
            self.region_id = None
        return self


class RegionBoundingBox(BaseModel):
    """Pixel-space bounding box for a layout region."""

    x: int
    y: int
    width: int
    height: int


class RegionPlan(BaseModel):
    """A planner-produced region definition."""

    region_id: str
    bbox: RegionBoundingBox
    description: str
    priority: int = Field(default=2, ge=1, le=5)
    status: Literal["planned", "in_progress", "passed", "partially_passed", "budget_exhausted"] = Field(
        default="planned",
    )


class ObjectFidelityHints(BaseModel):
    """Optional object-local visual fidelity goals derived during recognition."""

    verify_required: bool = Field(default=False)
    target_elements: list[str] = Field(default_factory=list)
    fidelity_goals: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_hint_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "fidelity_goals" not in data and "must_preserve" in data:
            data["fidelity_goals"] = data.get("must_preserve")
        for field_name in ("target_elements", "fidelity_goals"):
            values = data.get(field_name)
            if isinstance(values, str):
                data[field_name] = [values]
            elif not isinstance(values, list):
                data[field_name] = []
        return data

    @field_validator("target_elements", "fidelity_goals", mode="after")
    @classmethod
    def normalize_fidelity_lists(cls, values: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                " ".join(str(value).strip().split())
                for value in values
                if str(value).strip()
            )
        )[:5]


class RecognizedObjectStructure(BaseModel):
    """Frozen object identity and semantic ownership from structure recognition."""

    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: Literal["background", "icon", "text", "container", "connector", "diagram", "fig"]
    description: str
    included_elements: list[str] = Field(default_factory=list)

    @field_validator("object_id", "description", mode="before")
    @classmethod
    def normalize_required_structure_text(cls, value: object, info: ValidationInfo) -> str:
        text = " ".join(str(value or "").strip().split())
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @field_validator("object_type", mode="before")
    @classmethod
    def normalize_object_type(cls, value: str) -> str:
        if isinstance(value, str):
            return _normalize_object_type(value) or "fig"
        return value

    @field_validator("included_elements", mode="before")
    @classmethod
    def normalize_included_elements(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        return value if isinstance(value, list) else []


class RegionStructureRecognitionResult(BaseModel):
    """Stage-1 output containing only object structure and ownership."""

    model_config = ConfigDict(extra="forbid")

    region_id: str
    observation: str
    recognized_objects: list[RecognizedObjectStructure] = Field(default_factory=list)

    @field_validator("region_id", mode="before")
    @classmethod
    def normalize_required_region_id(cls, value: object, info: ValidationInfo) -> str:
        text = " ".join(str(value or "").strip().split())
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @model_validator(mode="after")
    def validate_recognition_contract(self, info: ValidationInfo) -> "RegionStructureRecognitionResult":
        object_ids = [obj.object_id for obj in self.recognized_objects]
        duplicate_ids = sorted({object_id for object_id in object_ids if object_ids.count(object_id) > 1})
        if duplicate_ids:
            raise ValueError(f"recognized object_id values must be unique: {', '.join(duplicate_ids)}")

        context = info.context if isinstance(info.context, dict) else {}
        expected_region_id = str(context.get("expected_region_id") or "").strip()
        if expected_region_id and self.region_id != expected_region_id:
            raise ValueError(
                f'region_id must equal expected region_id "{expected_region_id}", got "{self.region_id}"'
            )
        if context.get("require_recognized_objects") and not self.recognized_objects:
            raise ValueError("recognized_objects must not be empty for this visible region")
        return self


class ObjectContractDraft(BaseModel):
    """Stage-2 generation contract draft for one frozen object."""

    model_config = ConfigDict(extra="forbid")

    object_id: str
    generation_focus: list[str]
    relative_position: str
    extent_hint: str
    fidelity_hints: ObjectFidelityHints | None = None

    @field_validator("generation_focus", mode="before")
    @classmethod
    def normalize_generation_focus(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value if isinstance(value, list) else []

    @field_validator("relative_position", "extent_hint", mode="before")
    @classmethod
    def normalize_contract_text(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class RegionContractEnrichmentResult(BaseModel):
    """Stage-2 draft contracts for the frozen Stage-1 object set."""

    model_config = ConfigDict(extra="forbid")

    region_id: str
    object_updates: list[ObjectContractDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_frozen_object_contract(self, info: ValidationInfo) -> "RegionContractEnrichmentResult":
        update_ids = [update.object_id for update in self.object_updates]
        duplicate_ids = sorted({object_id for object_id in update_ids if update_ids.count(object_id) > 1})
        if duplicate_ids:
            raise ValueError(f"object_updates object_id values must be unique: {', '.join(duplicate_ids)}")

        context = info.context if isinstance(info.context, dict) else {}
        expected_region_id = str(context.get("expected_region_id") or "").strip()
        if expected_region_id and self.region_id != expected_region_id:
            raise ValueError(
                f'region_id must equal expected region_id "{expected_region_id}", got "{self.region_id}"'
            )

        expected_object_ids = [
            str(object_id).strip()
            for object_id in (context.get("expected_object_ids") or [])
            if str(object_id).strip()
        ]
        if expected_object_ids:
            expected_set = set(expected_object_ids)
            received_set = set(update_ids)
            missing_ids = [object_id for object_id in expected_object_ids if object_id not in received_set]
            unexpected_ids = sorted(received_set - expected_set)
            if missing_ids or unexpected_ids:
                details = []
                if missing_ids:
                    details.append(f"missing object_updates for: {', '.join(missing_ids)}")
                if unexpected_ids:
                    details.append(f"unexpected object_updates for: {', '.join(unexpected_ids)}")
                raise ValueError("; ".join(details))
        return self


class ObjectContractPatch(BaseModel):
    """Stage-3 patch containing only contract fields requested for repair."""

    model_config = ConfigDict(extra="forbid")

    object_id: str
    generation_focus: list[str] | None = None
    relative_position: str | None = None
    extent_hint: str | None = None
    fidelity_hints: ObjectFidelityHints | None = None

    @field_validator("generation_focus", mode="before")
    @classmethod
    def normalize_generation_focus(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [value]
        return value if isinstance(value, list) else []

    @field_validator("relative_position", "extent_hint", mode="before")
    @classmethod
    def normalize_contract_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return " ".join(str(value).strip().split())


class TargetedContractCompletionResult(BaseModel):
    """Stage-3 field-level contract patches for audited objects."""

    model_config = ConfigDict(extra="forbid")

    region_id: str
    object_updates: list[ObjectContractPatch] = Field(default_factory=list)


class ObjectCandidate(BaseModel):
    """A simplified object candidate recognized within one region."""

    object_id: str
    object_type: Literal["background", "icon", "text", "container", "connector", "diagram", "fig"]
    description: str
    included_elements: list[str] = Field(
        default_factory=list,
        description="Concrete visible sub-elements semantically owned by this object.",
    )
    generation_focus: list[str] = Field(default_factory=list, description="Short structured preservation goals for generation.")
    fidelity_hints: ObjectFidelityHints | None = Field(
        default=None,
        description="Optional object fidelity goals for distinctive details that should not be generically replaced.",
    )
    relative_position: str = Field(default="", description="Crop-local semantic position hint for later bbox localization.")
    extent_hint: str = Field(default="", description="Short hint describing what the later bbox should include or avoid.")
    bbox: RegionBoundingBox | None = Field(
        default=None,
        description=(
            "Optional object bounding box. Recognition/bbox workers use crop-local coordinates; "
            "after bbox finalization, downstream SVG generation and review use global source-image coordinates."
        ),
    )
    bbox_space: Literal["region_local", "global"] = Field(default="region_local")

    @field_validator("object_type", mode="before")
    @classmethod
    def normalize_object_type(cls, value: str) -> str:
        if isinstance(value, str):
            return _normalize_object_type(value) or "fig"
        return value

    @model_validator(mode="before")
    @classmethod
    def merge_legacy_object_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            parts = []
            for key in ("text_content", "style_hint", "connection_hint"):
                value = data.pop(key, None)
                if value:
                    parts.append(f"{key}: {value}")
            data.pop("region_id", None)
            generation_focus = data.get("generation_focus")
            if isinstance(generation_focus, str):
                data["generation_focus"] = [generation_focus]
            elif not isinstance(generation_focus, list):
                data["generation_focus"] = []
            included_elements = data.get("included_elements")
            if isinstance(included_elements, str):
                data["included_elements"] = [included_elements]
            elif not isinstance(included_elements, list):
                data["included_elements"] = []
            if not data.get("generation_focus"):
                if parts:
                    data["generation_focus"] = parts
        return data

    @field_validator("relative_position", "extent_hint", mode="before")
    @classmethod
    def normalize_optional_hint(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())

    @model_validator(mode="after")
    def validate_fidelity_hint_contract(self) -> "ObjectCandidate":
        hints = self.fidelity_hints
        if hints is None or not hints.verify_required:
            return self
        if not hints.target_elements:
            raise ValueError(
                f'Object "{self.object_id}" has verify_required=true but target_elements is empty.'
            )
        if not hints.fidelity_goals:
            raise ValueError(
                f'Object "{self.object_id}" has verify_required=true but fidelity_goals is empty.'
            )
        if self.object_type == "icon" and hints.target_elements != [self.object_id]:
            raise ValueError(
                f'Icon object "{self.object_id}" must use target_elements=["{self.object_id}"].'
            )
        return self


class RegionTask(BaseModel):
    """An executable unit assigned to a ReAct worker."""

    region_id: str
    region_description: str
    svg_group_template: str
    checklist_focus: list[str] = Field(default_factory=list)
    output_requirements: list[str] = Field(default_factory=list)


class RequirementPlan(BaseModel):
    """Structured output returned by the planning specialist."""

    summary: str
    conversion_goals: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    checklist_items: list[str] = Field(default_factory=list)
    region_strategy: list[str] = Field(default_factory=list)


class LayoutDetectionResult(BaseModel):
    """Structured layout detection output from the multimodal model."""

    canvas_width: int
    canvas_height: int
    overview: str
    complexity_assessment: dict = Field(default_factory=dict)
    regions: list[RegionPlan] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_summary(cls, data: object) -> object:
        if isinstance(data, dict) and "overview" not in data and "summary" in data:
            data["overview"] = data["summary"]
        return data


class RegionCheckItem(BaseModel):
    """A machine-readable region check result."""

    issue_family: ObjectIssueFamily
    criterion: str
    reason: str
    severity: Literal["low", "medium", "high"] = Field(default="medium")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_item_id(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            if "criterion" not in data and "item_id" in data:
                data["criterion"] = data["item_id"]
        return data


class RegionReviewIssue(BaseModel):
    """A problem-only issue emitted by region review."""

    issue_family: Literal[
        "layout_relation",
        "containment_boundary",
        "coverage_completeness",
        "visual_consistency",
        "editability_structure",
    ] = Field(default="visual_consistency")
    criterion: str
    reason: str
    severity: Literal["low", "medium", "high"] = Field(default="medium")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_item_id(cls, data: object) -> object:
        if isinstance(data, dict) and "criterion" not in data and "item_id" in data:
            data["criterion"] = data["item_id"]
        return data


class RegionGenerationResult(BaseModel):
    """Structured region generation output from the multimodal model."""

    region_id: str = ""
    observation: str
    recognized_objects: list[ObjectCandidate] = Field(default_factory=list)
    svg_elements: str


class RegionRecognitionResult(BaseModel):
    """Structured region recognition output before SVG generation."""

    region_id: str = ""
    observation: str
    recognized_objects: list[ObjectCandidate] = Field(default_factory=list)


class IssueRef(BaseModel):
    """Minimal issue reference shared across supervisor deltas and traces."""

    issue_id: str
    label: str


class PriorIssueRef(BaseModel):
    """Historical issue observation that the policy model must re-check."""

    issue_id: str
    scope: Literal["layout", "region", "object", "fusion"] = Field(default="region")
    target_id: str | None = Field(default=None)
    object_id: str | None = Field(default=None)
    criterion: str | None = Field(default=None)
    previous_reason: str = Field(default="")
    previous_iteration: str | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        issue_id = str(data.get("issue_id") or "").strip()
        if not issue_id:
            return data
        if not data.get("previous_reason"):
            data["previous_reason"] = str(data.get("label") or data.get("reason") or "").strip()
        if not data.get("criterion"):
            parts = [part for part in issue_id.split(":") if part]
            if parts:
                data["criterion"] = parts[-1]
        if not data.get("scope"):
            prefix = issue_id.split(":", 1)[0].strip().lower()
            if prefix in {"layout", "region", "object", "fusion"}:
                data["scope"] = prefix
        if data.get("object_id") is None and str(data.get("scope") or "") == "object":
            parts = [part for part in issue_id.split(":") if part]
            if len(parts) >= 3:
                data["object_id"] = parts[-2]
        return data


class PriorIssueAssessment(BaseModel):
    """Model judgment of whether a prior issue still holds in the current render."""

    issue_id: str
    status: Literal["resolved", "persists", "transformed", "uncertain"] = Field(default="uncertain")
    current_reason: str = Field(default="")
    replacement_issue_refs: list[IssueRef] = Field(default_factory=list)

    @field_validator("current_reason", mode="before")
    @classmethod
    def normalize_current_reason(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class DecisionDelta(BaseModel):
    """Lightweight decision delta passed into policy prompts."""

    last_route: str | None = Field(default=None)
    last_strategy: str | None = Field(default=None)
    recent_repair_attempt: str | None = Field(default=None)
    prior_issues_to_verify: list[PriorIssueRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_issue_delta(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("prior_issues_to_verify"):
            return data
        legacy_issues = data.get("issues") or {}
        still_open = legacy_issues.get("still_open") or []
        prior_issues: list[dict[str, object]] = []
        for item in still_open:
            if isinstance(item, dict):
                prior_issues.append(
                    {
                        "issue_id": item.get("issue_id"),
                        "previous_reason": item.get("label") or item.get("reason") or "",
                    }
                )
        if prior_issues:
            data["prior_issues_to_verify"] = prior_issues
        return data


class BboxQualityIssue(BaseModel):
    """A high-level bbox quality issue focused on position or size."""

    target_id: str
    issue_code: str = Field(default="")
    canonical_issue_id: str = Field(default="")
    edges: list[Literal["left", "top", "right", "bottom"]] = Field(default_factory=list)
    criterion: str
    reason: str
    severity: Literal["low", "medium", "high"] = Field(default="medium")

    @field_validator("issue_code", mode="before")
    @classmethod
    def normalize_issue_code(cls, value: object) -> str:
        return _normalize_bbox_issue_code(value)

    @field_validator("edges", mode="before")
    @classmethod
    def normalize_edges(cls, value: object) -> list[str]:
        return _normalize_bbox_issue_edges(value)

    @field_validator("criterion", "reason", mode="before")
    @classmethod
    def normalize_short_text(cls, value: object) -> str:
        if value is None:
            return ""
        text = " ".join(str(value).strip().split())
        return text

    @model_validator(mode="before")
    @classmethod
    def populate_issue_identity(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if not normalized.get("target_id") and normalized.get("object_id"):
            normalized["target_id"] = normalized.get("object_id")
        if not normalized.get("issue_code") and normalized.get("issue_family"):
            normalized["issue_code"] = normalized.get("issue_family")
        target_id = str(normalized.get("target_id") or "").strip()
        criterion = str(normalized.get("criterion") or "").strip().lower()
        reason = str(normalized.get("reason") or "").strip().lower()
        issue_code = _normalize_bbox_issue_code(
            normalized.get("issue_code"),
            criterion=criterion,
            reason=reason,
        )
        edges = _normalize_bbox_issue_edges(normalized.get("edges"))
        normalized["issue_code"] = issue_code
        normalized["edges"] = edges
        if target_id and issue_code:
            suffix = f":{','.join(edges)}" if edges else ""
            normalized["canonical_issue_id"] = f"{target_id}:{issue_code}{suffix}"
        else:
            normalized["canonical_issue_id"] = ""
        return normalized

    @model_validator(mode="after")
    def normalize_identity_after_field_validators(self):
        self.issue_code = _normalize_bbox_issue_code(
            self.issue_code,
            criterion=self.criterion,
            reason=self.reason,
        )
        self.edges = _normalize_bbox_issue_edges(self.edges)
        suffix = f":{','.join(self.edges)}" if self.edges else ""
        self.canonical_issue_id = f"{self.target_id}:{self.issue_code}{suffix}" if self.target_id else ""
        return self


class BboxTargetBoxUpdate(BaseModel):
    """Minimal bbox-only update payload for one existing target."""

    target_id: str
    bbox: RegionBoundingBox


class ObjectInitialBbox(BaseModel):
    """Initial single generous bbox produced after semantic recognition."""

    object_id: str
    bbox: RegionBoundingBox
    coverage_confidence: Literal["low", "medium", "high"] = Field(default="medium")
    overlap_risk: Literal["low", "medium", "high"] = Field(default="medium")
    rationale: str = Field(default="")

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class ObjectInitialBboxResult(BaseModel):
    """Batch initial bbox output for all objects in one region."""

    region_id: str
    object_bboxes: list[ObjectInitialBbox] = Field(default_factory=list)


class ObjectBboxCandidate(BaseModel):
    """One model-proposed bbox candidate for a target issue."""

    candidate_id: Literal["compact", "balanced", "roomy"]
    bbox: RegionBoundingBox
    intent: str = Field(default="")

    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class ObjectBboxCandidateSet(BaseModel):
    """Compact/balanced/roomy candidates for one bbox issue."""

    object_id: str
    issue_code: str = Field(default="")
    edges: list[Literal["left", "top", "right", "bottom"]] = Field(default_factory=list)
    candidates: list[ObjectBboxCandidate] = Field(default_factory=list)

    @field_validator("issue_code", mode="before")
    @classmethod
    def normalize_issue_code(cls, value: object) -> str:
        return _normalize_bbox_issue_code(value)

    @field_validator("edges", mode="before")
    @classmethod
    def normalize_edges(cls, value: object) -> list[str]:
        return _normalize_bbox_issue_edges(value)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if not normalized.get("object_id") and normalized.get("target_id"):
            normalized["object_id"] = normalized.get("target_id")
        if not normalized.get("issue_code") and normalized.get("issue_family"):
            normalized["issue_code"] = normalized.get("issue_family")
        return normalized

    @model_validator(mode="after")
    def keep_one_candidate_per_id(self):
        seen: set[str] = set()
        deduped: list[ObjectBboxCandidate] = []
        for candidate in self.candidates:
            if candidate.candidate_id in seen:
                continue
            seen.add(candidate.candidate_id)
            deduped.append(candidate)
        self.candidates = deduped
        return self


class ObjectBboxCandidateGenerationResult(BaseModel):
    """Batch candidate generation output for selected bbox issues."""

    region_id: str
    candidate_sets: list[ObjectBboxCandidateSet] = Field(default_factory=list)


class ObjectBboxResidualIssue(BaseModel):
    """Residual bbox issue after selecting the best candidate."""

    issue_code: str = Field(default="")
    edges: list[Literal["left", "top", "right", "bottom"]] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = Field(default="medium")
    reason: str = Field(default="")

    @field_validator("issue_code", mode="before")
    @classmethod
    def normalize_issue_code(cls, value: object) -> str:
        return _normalize_bbox_issue_code(value)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if not normalized.get("issue_code") and normalized.get("issue_family"):
            normalized["issue_code"] = normalized.get("issue_family")
        return normalized

    @field_validator("edges", mode="before")
    @classmethod
    def normalize_edges(cls, value: object) -> list[str]:
        return _normalize_bbox_issue_edges(value)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class ObjectBboxCandidateSelectionResult(BaseModel):
    """Object-level policy choice among bbox candidates."""

    object_id: str
    selected_candidate_id: Literal["compact", "balanced", "roomy"]
    selected_bbox: RegionBoundingBox
    issue_resolved: bool = Field(default=False)
    residual_issue: ObjectBboxResidualIssue | None = Field(default=None)
    selection_rationale: str = Field(default="")

    @field_validator("selection_rationale", mode="before")
    @classmethod
    def normalize_selection_rationale(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class BboxAdjustmentResult(BaseModel):
    """Unified bbox worker output used by both layout and recognition review loops."""

    scope: Literal["layout", "recognition"]
    region_id: str = ""
    overview: str = ""
    issues: list[BboxQualityIssue] = Field(default_factory=list)
    adjustment_type: str = Field(default="none")
    target_ids: list[str] = Field(default_factory=list, max_length=6)
    adjusted_regions: list[RegionPlan] = Field(default_factory=list)
    adjusted_object_bboxes: list[BboxTargetBoxUpdate] = Field(default_factory=list, max_length=12)
    strategy_enabled: bool = Field(default=False)
    strategy_label: str | None = Field(default=None)
    strategy_rationale: str | None = Field(default=None)
    strategy_confidence: Literal["low", "medium", "high"] | None = Field(default=None)
    changes_applied: list[str] = Field(default_factory=list, max_length=4)
    needs_adjustment: bool = Field(default=False)

    @model_validator(mode="before")
    @classmethod
    def normalize_common_schema_drift(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        scope = str(normalized.get("scope") or "").strip()
        adjustment_type = str(normalized.get("adjustment_type") or "").strip()
        allowed_adjustment_types = (
            {
                "none",
                "tighten_overreach",
                "expand_for_missing_content",
                "recenter_within_local_context",
                "merge_background_bands",
                "split_independent_bands",
                "split_independent_panels",
                "repartition_overcoarse_layout",
                "mixed",
            }
            if scope == "layout"
            else {
                "none",
                "tighten_overreach",
                "expand_for_missing_content",
                "recenter_within_local_context",
                "merge_background_bands",
                "mixed",
            }
        )
        adjustment_aliases = {
            "split_region": "mixed",
            "expand_for_border_clearance": "expand_for_missing_content",
            "reposition_and_expand": "mixed",
            "expand_and_recenter": "mixed",
        }
        if adjustment_type:
            normalized["adjustment_type"] = adjustment_aliases.get(
                adjustment_type,
                adjustment_type if adjustment_type in allowed_adjustment_types else "mixed",
            )
        elif not normalized.get("needs_adjustment"):
            normalized["adjustment_type"] = "none"

        if isinstance(normalized.get("target_ids"), list):
            normalized["target_ids"] = normalized["target_ids"][:6]
        if isinstance(normalized.get("adjusted_object_bboxes"), list):
            normalized["adjusted_object_bboxes"] = normalized["adjusted_object_bboxes"][:12]
        if isinstance(normalized.get("changes_applied"), list):
            normalized["changes_applied"] = normalized["changes_applied"][:4]
        return normalized

    @field_validator("overview", mode="before")
    @classmethod
    def normalize_overview(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())

    @field_validator("changes_applied", mode="before")
    @classmethod
    def normalize_changes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [" ".join(str(item).strip().split()) for item in value if str(item).strip()]

    @field_validator("target_ids", mode="before")
    @classmethod
    def normalize_target_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def validate_scope_payload(self):
        if self.scope == "layout":
            self.adjusted_object_bboxes = []
        if self.scope == "recognition":
            self.adjusted_regions = []
            if self.adjustment_type not in {
                "none",
                "tighten_overreach",
                "expand_for_missing_content",
                "recenter_within_local_context",
                "merge_background_bands",
                "mixed",
            }:
                self.adjustment_type = "mixed"
        if self.scope == "layout" and self.adjustment_type not in {
            "none",
            "tighten_overreach",
            "expand_for_missing_content",
            "recenter_within_local_context",
            "merge_background_bands",
            "split_independent_bands",
            "split_independent_panels",
            "repartition_overcoarse_layout",
            "mixed",
        }:
            self.adjustment_type = "mixed"
        return self


class BboxIssueThreadSummary(BaseModel):
    """Lifecycle summary for one independently refined bbox issue."""

    canonical_issue_id: str
    target_id: str
    issue_code: str = Field(default="")
    severity: Literal["low", "medium", "high"] = Field(default="medium")
    status: Literal["resolved", "acceptable", "progressive", "failed", "skipped"] = Field(default="failed")
    stop_reason: str = Field(default="")
    iterations: int = Field(default=0, ge=0)
    committed: bool = Field(default=False)
    stagnation_count: int = Field(default=0, ge=0)


class BboxGlobalRoundSummary(BaseModel):
    """Summary for one recognition bbox global scan round."""

    round_index: int = Field(default=0, ge=0)
    proposed_issue_ids: list[str] = Field(default_factory=list)
    resolved_issue_ids: list[str] = Field(default_factory=list)
    exempted_issue_ids: list[str] = Field(default_factory=list)
    committed_issue_ids: list[str] = Field(default_factory=list)
    stop_reason: str = Field(default="")
    stagnated: bool = Field(default=False)


class BboxCandidateReview(BaseModel):
    """Policy-stage review of one bbox candidate state."""

    overview: str = ""
    issues: list[BboxQualityIssue] = Field(default_factory=list)
    needs_adjustment: bool = Field(default=False)

    @field_validator("overview", mode="before")
    @classmethod
    def normalize_overview(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class BboxTerminationAssessment(BaseModel):
    """Model-produced termination tendency after candidate review."""

    acceptance_tendency: Literal["accept", "reject"] = Field(default="reject")
    acceptance_rationale: str = ""
    stop_tendency: Literal["continue", "stop"] = Field(default="continue")
    stop_rationale: str = ""

    @field_validator("acceptance_rationale", "stop_rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class BboxCombinedPolicyModelResult(BaseModel):
    """Unified bbox candidate-review plus termination tendencies from one policy-model call."""

    scope: Literal["layout", "recognition"]
    region_id: str = ""
    candidate_review: BboxCandidateReview = Field(default_factory=BboxCandidateReview)
    termination: BboxTerminationAssessment = Field(default_factory=BboxTerminationAssessment)


class BboxPolicyDecision(BaseModel):
    """Final bbox policy decision after model output and hard-rule reconciliation."""

    review: BboxCandidateReview = Field(default_factory=BboxCandidateReview)
    accept_current_result: bool = Field(default=False)
    continue_refinement: bool = Field(default=True)
    final_reason: str = Field(default="")
    applied_rules: list[str] = Field(default_factory=list)


class RegionSvgGenerationResult(BaseModel):
    """Structured region-level SVG generation or update output."""

    region_id: str = ""
    svg_elements: str
    generation_notes: list[str] = Field(default_factory=list)


class ObjectSvgGenerationResult(BaseModel):
    """Structured object-level SVG generation or update output."""

    object_id: str
    svg_elements: str
    generation_notes: list[str] = Field(default_factory=list)


class ObjectReviewResult(BaseModel):
    """Structured review output for a single recognized object."""

    object_id: str
    failed_items: list[RegionCheckItem] = Field(default_factory=list)


class RegionObjectIssue(BaseModel):
    """Region review issue scoped to a recognized object."""

    object_id: str
    issue_family: ObjectIssueFamily
    criterion: str
    reason: str
    severity: Literal["low", "medium", "high"] = Field(default="medium")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_item_id(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            if "criterion" not in data and "item_id" in data:
                data["criterion"] = data["item_id"]
        return data


class SymbolFidelityChecks(BaseModel):
    """Material symbol-fidelity acceptance checks."""

    model_config = ConfigDict(extra="forbid")

    form: Literal["Y", "N"]
    composition: Literal["Y", "N"]
    style: Literal["Y", "N"]
    integrity: Literal["Y", "N"]


class RegionFidelityVerification(BaseModel):
    """Axis-based fidelity judgment for an object that must be checked."""

    object_id: str
    checks: SymbolFidelityChecks
    reason: str = ""

    @field_validator("object_id", "reason", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split())


class RegionReviewResult(BaseModel):
    """Structured region review output from the multimodal model."""

    region_id: str
    passed_items: list[str] = Field(default_factory=list)
    fidelity_verifications: list[RegionFidelityVerification] = Field(
        default_factory=list,
        description=(
            "Structured four-axis judgments only for object IDs listed in "
            "required_fidelity_checks."
        ),
    )
    global_repairs: list[RegionReviewIssue] = Field(
        default_factory=list,
        description="Problem-only whole-region issues that require the region SVG generation branch.",
    )
    object_issues: list[RegionObjectIssue] = Field(
        default_factory=list,
        description="Problem-only object-scoped quality issues for the object SVG generation branch.",
    )


class RegionRepairResult(BaseModel):
    """Structured region repair output from the multimodal model."""

    region_id: str
    repaired_svg_elements: str
    repairs_applied: list[str] = Field(default_factory=list)
    remaining_limitations: list[str] = Field(default_factory=list)


class FinalReviewIssue(BaseModel):
    """A fusion-quality issue found in the merged SVG."""

    criterion: str = Field(description="Short snake_case label identifying the issue.")
    severity: Literal["low", "medium", "high"]
    description: str
    related_regions: list[str] = Field(default_factory=list)
    related_objects: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if not str(data.get("criterion") or "").strip():
            if data.get("category"):
                data["criterion"] = data["category"]
            elif data.get("issue"):
                data["criterion"] = str(data["issue"]).strip().lower().replace(" ", "_")[:48] or "fusion_issue"
        if not str(data.get("description") or "").strip() and data.get("issue"):
            data["description"] = data["issue"]
        if data.get("rationale") and str(data.get("description") or "").strip():
            rationale = str(data["rationale"]).strip()
            description = str(data.get("description") or "").strip()
            if rationale and rationale not in description:
                data["description"] = f"{description} {rationale}".strip()
        elif not str(data.get("description") or "").strip() and data.get("rationale"):
            data["description"] = data["rationale"]
        if not str(data.get("severity") or "").strip():
            data["severity"] = "medium"
        return data


class FinalReviewResult(BaseModel):
    """Structured final fusion-quality review output from the multimodal model."""

    class SpatialRelationIssues(BaseModel):
        """Spatial-relation issues in the merged SVG."""

        layout_fidelity_issues: list[FinalReviewIssue] = Field(default_factory=list)
        dimension_fidelity_issues: list[FinalReviewIssue] = Field(default_factory=list)

    class LogicalRelationIssues(BaseModel):
        """Logical-relation issues in the merged SVG."""

        redundancy_issues: list[FinalReviewIssue] = Field(default_factory=list)
        boundary_issues: list[FinalReviewIssue] = Field(default_factory=list)

    class VisualQualityIssues(BaseModel):
        """Visual-quality issues in the merged SVG."""

        consistency_issues: list[FinalReviewIssue] = Field(default_factory=list)
        visual_reasonableness_issues: list[FinalReviewIssue] = Field(default_factory=list)

    spatial_relation_issues: SpatialRelationIssues = Field(default_factory=SpatialRelationIssues)
    logical_relation_issues: LogicalRelationIssues = Field(default_factory=LogicalRelationIssues)
    visual_quality_issues: VisualQualityIssues = Field(default_factory=VisualQualityIssues)
    known_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_known_limitations(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = data.get("known_limitations")
        if not isinstance(raw, list):
            return data
        normalized: list[str] = []
        for item in raw:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized.append(text)
                continue
            if isinstance(item, dict):
                text = str(item.get("issue") or item.get("description") or "").strip()
                rationale = str(item.get("rationale") or "").strip()
                if rationale and rationale not in text:
                    text = f"{text} {rationale}".strip()
                if text:
                    normalized.append(text)
        data["known_limitations"] = normalized
        return data


class IntegratedSvgRepairResult(BaseModel):
    """Structured integrated-SVG repair output after merge-time coordination issues."""

    repaired_svg: str
    repairs_applied: list[str] = Field(default_factory=list)
    remaining_limitations: list[str] = Field(default_factory=list)


class RegionElementPresence(BaseModel):
    """Stage-1 element presence scan for one layout region."""

    region_id: str
    icon: Literal["Y", "N"] = "N"
    text: Literal["Y", "N"] = "N"
    background: Literal["Y", "N"] = "N"
    container: Literal["Y", "N"] = "N"
    connector: Literal["Y", "N"] = "N"
    diagram: Literal["Y", "N"] = "N"
    fig: Literal["Y", "N"] = "N"

    @model_validator(mode="before")
    @classmethod
    def normalize_presence_flags(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in ("icon", "text", "background", "container", "connector", "diagram", "fig"):
                if key in data:
                    data[key] = _normalize_presence_flag(data[key])
        return data


class ChecklistStageSection(BaseModel):
    """Checklist items for one pipeline stage."""

    common: list[ChecklistItem] = Field(default_factory=list)
    regions: dict[str, list[ChecklistItem]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_section_items(self):
        normalized_common: list[ChecklistItem] = []
        for item in self.common:
            normalized_common.append(item.model_copy(update={"scope": "common", "region_id": None}))
        normalized_regions: dict[str, list[ChecklistItem]] = {}
        for region_id, items in self.regions.items():
            normalized_regions[region_id] = [
                item.model_copy(update={"scope": "region", "region_id": region_id})
                for item in items
            ]
        self.common = normalized_common
        self.regions = normalized_regions
        return self


class ChecklistStages(BaseModel):
    """All stage-organized checklist sections."""

    recognition: ChecklistStageSection = Field(default_factory=ChecklistStageSection)
    generation_refine: ChecklistStageSection = Field(default_factory=ChecklistStageSection)
    fusion: ChecklistStageSection = Field(default_factory=ChecklistStageSection)

    @model_validator(mode="after")
    def validate_fusion_section(self):
        if self.fusion.regions:
            raise ValueError("fusion checklist must not include region-scoped entries.")
        self.fusion.common = [
            item.model_copy(update={"scope": "common", "region_id": None})
            for item in self.fusion.common
        ]
        return self


class ChecklistPlanResult(BaseModel):
    """Structured acceptance checklist generated from the user request and source image."""

    element_presence: list[RegionElementPresence] = Field(default_factory=list)
    checklists: ChecklistStages = Field(default_factory=ChecklistStages)


class RegionExecutionNote(BaseModel):
    """Structured output returned by a region-focused worker."""

    region_id: str
    observation: str
    recognized_objects: list[str] = Field(default_factory=list)
    svg_strategy: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TerminationAssessment(BaseModel):
    """Model-side assessment of whether the current result is acceptable and whether to stop."""

    acceptance_tendency: Literal["accept", "reject"] = Field(default="reject")
    acceptance_rationale: str = Field(default="")
    stop_tendency: Literal["continue", "stop"] = Field(default="continue")
    stop_rationale: str = Field(default="")


class RegionRepairPlan(BaseModel):
    """Model-side region repair plan emitted together with review."""

    route: Literal["region_repair", "object_repair"] = Field(default="region_repair")
    route_rationale: str = Field(default="")
    target_objects: list[str] = Field(default_factory=list)
    strategy_enabled: bool = Field(default=False)
    strategy_label: str | None = Field(default=None)
    strategy_rationale: str | None = Field(default=None)
    strategy_confidence: Literal["low", "medium", "high"] | None = Field(default=None)


class ObjectRepairPlan(BaseModel):
    """Model-side object repair plan emitted together with object review."""

    route: Literal["object_repair"] = Field(default="object_repair")
    route_rationale: str = Field(default="")
    strategy_enabled: bool = Field(default=False)
    strategy_label: str | None = Field(default=None)
    strategy_rationale: str | None = Field(default=None)
    strategy_confidence: Literal["low", "medium", "high"] | None = Field(default=None)


class FusionRepairPlan(BaseModel):
    """Model-side fusion repair plan emitted together with final review."""

    route: Literal["fusion_repair"] = Field(default="fusion_repair")
    route_rationale: str = Field(default="")
    strategy_enabled: bool = Field(default=False)
    strategy_label: str | None = Field(default=None)
    strategy_rationale: str | None = Field(default=None)
    strategy_confidence: Literal["low", "medium", "high"] | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def force_fixed_route(cls, data: object) -> object:
        if isinstance(data, dict):
            data["route"] = "fusion_repair"
        return data


class RegionCombinedPolicyModelResult(BaseModel):
    """Unified region review-plus-decision result from one policy-model call."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: RegionReviewResult
    repair_plan: RegionRepairPlan = Field(default_factory=RegionRepairPlan)
    termination: TerminationAssessment = Field(default_factory=TerminationAssessment)


class ObjectCombinedPolicyModelResult(BaseModel):
    """Unified object review-plus-decision result from one policy-model call."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: ObjectReviewResult
    repair_plan: ObjectRepairPlan = Field(default_factory=ObjectRepairPlan)
    termination: TerminationAssessment = Field(default_factory=TerminationAssessment)


class FusionCombinedPolicyModelResult(BaseModel):
    """Unified fusion review-plus-decision result from one policy-model call."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: FinalReviewResult = Field(default_factory=FinalReviewResult)
    repair_plan: FusionRepairPlan = Field(default_factory=FusionRepairPlan)
    termination: TerminationAssessment = Field(default_factory=TerminationAssessment)


class RegionPolicyDecision(BaseModel):
    """Final region policy decision after model output and hard-rule reconciliation."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: RegionReviewResult
    final_route: Literal["region_repair", "object_repair"]
    final_route_reason: str
    final_target_objects: list[str] = Field(default_factory=list)
    strategy_enabled: bool = Field(default=False)
    final_strategy_label: str | None = Field(default=None)
    final_strategy_rationale: str | None = Field(default=None)
    accept_current_result: bool = Field(default=False)
    continue_refinement: bool = Field(default=True)
    final_reason: str = Field(default="")
    applied_rules: list[str] = Field(default_factory=list)


class ObjectPolicyDecision(BaseModel):
    """Final object policy decision after model output and hard-rule reconciliation."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: ObjectReviewResult
    final_route: Literal["object_repair"] = Field(default="object_repair")
    final_route_reason: str = Field(default="")
    strategy_enabled: bool = Field(default=False)
    final_strategy_label: str | None = Field(default=None)
    final_strategy_rationale: str | None = Field(default=None)
    accept_current_result: bool = Field(default=False)
    continue_refinement: bool = Field(default=True)
    final_reason: str = Field(default="")
    applied_rules: list[str] = Field(default_factory=list)


class FusionPolicyDecision(BaseModel):
    """Final fusion policy decision after model output and hard-rule reconciliation."""

    prior_issue_assessment: list[PriorIssueAssessment] = Field(default_factory=list)
    review: FinalReviewResult = Field(default_factory=FinalReviewResult)
    final_route: Literal["fusion_repair"] = Field(default="fusion_repair")
    final_route_reason: str = Field(default="")
    strategy_enabled: bool = Field(default=False)
    final_strategy_label: str | None = Field(default=None)
    final_strategy_rationale: str | None = Field(default=None)
    accept_current_result: bool = Field(default=False)
    continue_refinement: bool = Field(default=True)
    final_outcome: Literal[
        "accepted_clean",
        "accepted_minor_residuals",
        "continue_refinement",
        "stopped_with_residual_issues",
    ] = Field(default="continue_refinement")
    final_reason: str = Field(default="")
    applied_rules: list[str] = Field(default_factory=list)


class StopDecision(BaseModel):
    """Policy-layer terminal decision for a supervisor-controlled refinement cycle."""

    outcome: Literal["accept", "stop", "continue"]
    reason: str
    confidence: Literal["low", "medium", "high"] = Field(default="medium")


class RepairAcceptanceDecision(BaseModel):
    """Policy-layer decision on whether to accept the latest repair result."""

    accept_repair: bool = Field(default=True)
    rationale: str
    resolved_issue_ids: list[str] = Field(default_factory=list)
    new_issue_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = Field(default="medium")


class SupervisorIssueMemory(BaseModel):
    """Compact issue summary stored in supervisor working memory."""

    issue_id: str
    scope: Literal["layout", "region", "object", "fusion"] = Field(default="region")
    target_id: str | None = Field(default=None)
    criterion: str | None = Field(default=None)
    reason: str
    status: Literal["seen", "attempted", "resolved", "unresolved", "blocked", "skipped"] = Field(
        default="seen"
    )
    attempts: int = Field(default=0, ge=0)
    source_iteration: str | None = Field(default=None)


class SupervisorDecisionMemory(BaseModel):
    """A short decision note captured during supervisor routing."""

    iteration: str
    actor: str
    action: str
    rationale: str
    related_issues: list[str] = Field(default_factory=list)


class LayoutSupervisorMemory(BaseModel):
    """Short-lived structured working memory for the layout supervisor."""

    canvas_width: int | None = Field(default=None)
    canvas_height: int | None = Field(default=None)
    layout_overview: str | None = Field(default=None)
    complexity_assessment: dict = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    region_ids: list[str] = Field(default_factory=list)
    decisions: list[SupervisorDecisionMemory] = Field(default_factory=list)
    checklist_summary: list[str] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None)


class ObjectRepairSupervisorMemory(BaseModel):
    """Short-lived structured working memory for object repair routing."""

    region_id: str
    object_ids: list[str] = Field(default_factory=list)
    issue_history: list[SupervisorIssueMemory] = Field(default_factory=list)
    object_attempts: dict[str, int] = Field(default_factory=dict)
    object_last_failure: dict[str, str] = Field(default_factory=dict)
    resolved_objects: list[str] = Field(default_factory=list)
    unresolved_objects: list[str] = Field(default_factory=list)
    routing_notes: list[SupervisorDecisionMemory] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None)


class RegionSupervisorMemory(BaseModel):
    """Short-lived structured working memory for one region supervisor."""

    region_id: str
    iteration: int = Field(default=0, ge=0)
    goals: list[str] = Field(default_factory=list)
    accepted_constraints: list[str] = Field(default_factory=list)
    review_route_history: list[SupervisorDecisionMemory] = Field(default_factory=list)
    attempted_region_strategies: list[str] = Field(default_factory=list)
    attempted_object_strategies: list[str] = Field(default_factory=list)
    resolved_issues: list[SupervisorIssueMemory] = Field(default_factory=list)
    unresolved_issues: list[SupervisorIssueMemory] = Field(default_factory=list)
    blocked_issues: list[SupervisorIssueMemory] = Field(default_factory=list)
    object_issue_status: dict[str, dict] = Field(default_factory=dict)
    decision_notes: list[SupervisorDecisionMemory] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None)


class FusionSupervisorMemory(BaseModel):
    """Short-lived structured working memory for merged-SVG fusion review."""

    iteration: int = Field(default=0, ge=0)
    issue_groups_seen: list[SupervisorIssueMemory] = Field(default_factory=list)
    attempted_merge_strategies: list[str] = Field(default_factory=list)
    resolved_cross_region_issues: list[SupervisorIssueMemory] = Field(default_factory=list)
    remaining_cross_region_issues: list[SupervisorIssueMemory] = Field(default_factory=list)
    stable_regions: list[str] = Field(default_factory=list)
    unstable_boundaries: list[dict] = Field(default_factory=list)
    decision_notes: list[SupervisorDecisionMemory] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None)


class BboxSupervisorMemory(BaseModel):
    """Short-lived structured working memory for bbox review/refinement loops."""

    scope_key: str
    scope: Literal["layout", "recognition"]
    iteration: int = Field(default=0, ge=0)
    issue_history: list[SupervisorIssueMemory] = Field(default_factory=list)
    attempted_adjustment_types: list[str] = Field(default_factory=list)
    accepted_changes: list[str] = Field(default_factory=list)
    rejected_changes: list[str] = Field(default_factory=list)
    decision_notes: list[SupervisorDecisionMemory] = Field(default_factory=list)
    stop_reason: str | None = Field(default=None)


class AgentRequest(BaseModel):
    """Input schema for starting a new agent run."""

    message: str = Field(default="", description="The user request for the agent.")
    api_provider: str | None = Field(
        default=None,
        description="Optional API provider override for this run, for example openai_compatible.",
    )
    api_key: str | None = Field(
        default=None,
        description="Optional API key override for this run.",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional API base URL override for this run.",
    )
    api_format: str | None = Field(
        default=None,
        description="Optional API format override for this run, for example openai_chat_completions or openai_responses.",
    )
    max_retries: int | None = Field(
        default=None,
        ge=0,
        description="Optional low-level API retry override for this run.",
    )
    transport_max_attempts: int | None = Field(default=None, ge=1)
    response_validation_max_attempts: int | None = Field(default=None, ge=1)
    image_path: str | None = Field(
        default=None,
        description="Optional local raster image path used for actual conversion.",
    )
    region_processing_mode: Literal["serial", "parallel"] | None = Field(
        default=None,
        description="Whether region SVG generation runs serially or through a bounded parallel task pool.",
    )
    region_concurrency: int | None = Field(
        default=None,
        ge=1,
        le=16,
        description=(
            "Shared worker budget when region_processing_mode is parallel. "
            "Each active region reserves one worker; any leftover workers may be borrowed for object-level parallelism."
        ),
    )
    bbox_issue_concurrency: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Maximum number of independent bbox issue refine threads that may run concurrently inside one region.",
    )
    bbox_issue_stagnation_rounds: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Early-stop threshold for one bbox issue thread when improvement remains below the local stagnation threshold.",
    )
    bbox_global_stagnation_rounds: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Early-stop threshold for recognition bbox global scan rounds when the issue set keeps repeating with low gain.",
    )
    bbox_initial_localization_max_attempts: int | None = Field(default=None, ge=1)
    bbox_refinement_max_rounds: int | None = Field(default=None, ge=0)
    bbox_global_stagnation_max_rounds: int | None = Field(default=None, ge=1)
    workflow_mode: Literal["initial_only", "region", "region_object"] | None = Field(
        default=None,
        description=(
            "Controls whether the pipeline stops after the initial merged SVG, "
            "runs only region-level refinement, or continues into object-level refinement."
        ),
    )
    project_name: str | None = Field(
        default=None,
        description="Optional human-friendly display name for the run.",
    )
    agent_model: str | None = Field(
        default=None,
        description="Optional coordinator/final-review model override for this run.",
    )
    subagent_model: str | None = Field(
        default=None,
        description="Optional subagent/region-worker model override for this run.",
    )
    agent_name: str | None = Field(
        default=None,
        description="Optional coordinator name override for this run.",
    )
    use_previous_response_id: bool | None = Field(
        default=None,
        description="Optional Responses API state reuse override for this run.",
    )
    max_retry: int | None = Field(
        default=None,
        ge=0,
        description="Optional per-task repair retry override for this run.",
    )
    region_repair_max_attempts: int | None = Field(default=None, ge=0)
    object_repair_max_attempts: int | None = Field(default=None, ge=0)
    fidelity_verification_max_attempts: int | None = Field(default=None, ge=1)
    fidelity_verification_independent_budget: bool | None = Field(default=None)
    fusion_max_retry: int | None = Field(
        default=None,
        ge=0,
        description="Optional maximum number of merge-time fusion repair passes for this run.",
    )
    fusion_repair_max_attempts: int | None = Field(default=None, ge=0)
    max_budget: int | None = Field(
        default=None,
        ge=0,
        description="Optional total model-call budget override for this run.",
    )
    run_model_call_budget: int | None = Field(default=None, ge=0)
    supervisor_memory_enabled: bool | None = Field(
        default=None,
        description="Whether supervisor memory is injected into prompts and allowed to affect supervisor or policy decisions.",
    )
    supervisor_memory_persist_enabled: bool | None = Field(
        default=None,
        description="Whether supervisor memory artifacts are generated and persisted to disk.",
    )
    strategy_enabled: bool | None = Field(
        default=None,
        description="Enable optional strategy hints inside combined policy-model decisions.",
    )
    recognition_bbox_refine_mode: Literal["llm", "sam", "hybrid"] | None = Field(
        default=None,
        description="Select how issue-level object bbox refinement runs after region recognition.",
    )
    sam_provider_mode: Literal["local", "remote"] | None = Field(
        default=None,
        description="Choose whether SAM-backed refinement should use a local runtime or a remote service.",
    )
    sam_remote_url: str | None = Field(
        default=None,
        description="Optional SAM remote service URL override for this run.",
    )
    sam_enabled: bool | None = Field(
        default=None,
        description="Whether SAM-backed bbox refinement is enabled for this run.",
    )
    sam_fallback_to_llm: bool | None = Field(
        default=None,
        description="Whether SAM-backed refinement should fall back to the existing LLM refine path.",
    )
    thread_id: str | None = Field(
        default=None,
        description="Optional thread identifier used for short-term memory across turns.",
    )


class UploadImageRequest(BaseModel):
    """JSON upload payload for drag-and-drop images from the frontend."""

    filename: str = Field(description="Original local filename.")
    content_base64: str = Field(description="Base64-encoded file bytes.")


class UploadImageResponse(BaseModel):
    """Saved upload response returned to the frontend."""

    image_path: str = Field(description="Saved local image path that can be reused by /invoke.")
    filename: str = Field(description="Original filename.")
    size_bytes: int = Field(description="Decoded file size in bytes.")


class ApprovalRequest(BaseModel):
    """Approval request emitted by a guarded tool."""

    action_name: str = Field(description="The sensitive action that needs approval.")
    action_summary: str = Field(description="A human-readable summary of what will happen.")
    tool_name: str = Field(description="The tool that requested approval.")
    payload: dict = Field(default_factory=dict, description="Tool input payload under review.")


class ApprovalDecision(BaseModel):
    """Client decision for a pending approval."""

    thread_id: str = Field(description="Thread containing a paused agent run.")
    decision: Literal["approve", "reject"] = Field(description="The human approval decision.")
    comment: str | None = Field(
        default=None,
        description="Optional reviewer comment passed back into the workflow.",
    )


class ChatMessage(BaseModel):
    """Message representation for the API and demo frontend."""

    role: Literal["user", "assistant", "system"] = Field(description="Message role.")
    content: str = Field(description="Message content.")
    created_at: datetime = Field(default_factory=utc_now)


class ExecutionEvent(BaseModel):
    """A single execution timeline event."""

    timestamp: datetime = Field(default_factory=utc_now)
    stage: str = Field(description="Machine-readable stage identifier.")
    title: str = Field(description="Short user-facing event title.")
    detail: str | None = Field(default=None, description="Optional event detail.")
    level: Literal["info", "success", "warning", "error"] = Field(default="info")
    stage_duration_ms: int | None = Field(
        default=None,
        description="Elapsed milliseconds spent in the current stage when this event was recorded.",
    )
    payload: dict | None = Field(default=None, description="Optional structured event payload.")


class WorkerStatus(BaseModel):
    """Live execution status for one worker thread/task."""

    worker_id: str = Field(description="Stable worker identifier, usually the thread name.")
    status: Literal["idle", "running", "completed", "failed"] = Field(description="Current worker status.")
    stage: str = Field(description="Current worker stage.")
    task_id: str | None = Field(default=None, description="Optional task identifier such as a region id.")
    detail: str | None = Field(default=None, description="Optional worker detail.")
    semantic_stage: str | None = Field(default=None, description="Short user-facing stage label for the active task.")
    started_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)
    duration_ms: int | None = Field(default=None)


class FailureArtifactHint(BaseModel):
    """A file path that helps explain or debug a failed/paused run."""

    label: str = Field(description="Short user-facing label for the artifact.")
    relative_path: str = Field(description="Artifact-relative path for the file.")
    kind: str = Field(default="file", description="Coarse artifact kind such as state, timeline, request, or response.")


class FailureDiagnostic(BaseModel):
    """Structured failure or pause summary suitable for API responses and UI rendering."""

    status: str | None = Field(default=None)
    terminal_stage: str | None = Field(default=None)
    failure_stage: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    error_type: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    root_cause_type: str | None = Field(default=None)
    root_cause_message: str | None = Field(default=None)
    policy_name: str | None = Field(default=None)
    model_name: str | None = Field(default=None)
    response_model: str | None = Field(default=None)
    attempt: int | None = Field(default=None)
    attempts_total: int | None = Field(default=None)
    last_event_title: str | None = Field(default=None)
    last_event_detail: str | None = Field(default=None)
    last_success_stage: str | None = Field(default=None)
    request_path: str | None = Field(default=None)
    raw_response_path: str | None = Field(default=None)
    artifact_hints: list[FailureArtifactHint] = Field(default_factory=list)


class ExecutionRun(BaseModel):
    """Execution metadata for the current or recent run."""

    run_id: str = Field(description="Unique run identifier.")
    owner_thread_id: str | None = Field(
        default=None,
        description="Thread that owns this run and is allowed to mutate its artifacts.",
    )
    mode: Literal["invoke", "resume"] = Field(description="How the run was started.")
    status: Literal["queued", "running", "needs_approval", "paused", "completed", "failed", "cancelled"] = Field(
        description="Current run status.",
    )
    current_stage: str = Field(description="Current execution stage.")
    failure_stage: str | None = Field(default=None, description="Concrete business stage where the failure or pause occurred.")
    started_at: datetime = Field(default_factory=utc_now)
    current_stage_started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    current_stage_duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None)
    failure_diagnostic: FailureDiagnostic | None = Field(default=None)
    project_name: str = Field(description="Project label associated with this run.")
    artifact_dir: str | None = Field(default=None, description="Filesystem directory for run artifacts.")
    artifact_revision: str | None = Field(default=None)
    worker_statuses: list[WorkerStatus] = Field(default_factory=list)
    events: list[ExecutionEvent] = Field(default_factory=list)


class ThreadState(BaseModel):
    """Short-term memory snapshot for a conversation thread."""

    thread_id: str = Field(description="Conversation thread id.")
    bound_run_id: str | None = Field(
        default=None,
        description="The single conversion run bound to this workspace.",
    )
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_approval: ApprovalRequest | None = Field(default=None)
    current_run: ExecutionRun | None = Field(default=None)
    recent_runs: list[ExecutionRun] = Field(default_factory=list)


class RunRenameRequest(BaseModel):
    """Request body for renaming a saved desktop project."""

    project_name: str = Field(min_length=1, max_length=120)

    @field_validator("project_name", mode="before")
    @classmethod
    def normalize_project_name(cls, value: object) -> str:
        return " ".join(str(value or "").strip().split())


class ThreadCreateResponse(BaseModel):
    """Thread creation response."""

    thread_id: str = Field(description="Newly created thread id.")


class RunStartResponse(BaseModel):
    """Response returned when a run has been accepted for processing."""

    thread_id: str = Field(description="Conversation thread id.")
    run: ExecutionRun = Field(description="The newly created run metadata.")
    messages: list[ChatMessage] = Field(default_factory=list)


class RunListResponse(BaseModel):
    """Global saved-project list used by the History page."""

    runs: list[ExecutionRun] = Field(default_factory=list)
    total: int | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=6, ge=1)
    total_pages: int | None = Field(default=None, ge=1)
    has_more: bool = Field(default=False)


class RunOpenResponse(BaseModel):
    """Persisted run attached to its owning workspace."""

    thread_id: str
    run: ExecutionRun
    snapshot: "AgentResponse"


class HistoryPreviewResponse(BaseModel):
    """Read-only URLs for existing files shown on a History card."""

    run_id: str
    input_preview_url: str | None = None
    output_preview_url: str | None = None


class AgentResponse(BaseModel):
    """Snapshot response for the current thread state."""

    thread_id: str = Field(description="The active conversation thread id.")
    bound_run_id: str | None = Field(default=None)
    status: Literal["queued", "running", "needs_approval", "paused", "completed", "failed", "cancelled"] = Field(
        description="Current thread execution status.",
    )
    content: str | None = Field(
        default=None,
        description="The latest assistant response when available.",
    )
    approval_request: ApprovalRequest | None = Field(
        default=None,
        description="Approval payload when the agent paused before a sensitive action.",
    )
    messages: list[ChatMessage] = Field(
        default_factory=list,
        description="The current short-term chat history stored for this thread.",
    )
    current_run: ExecutionRun | None = Field(default=None)
    recent_runs: list[ExecutionRun] = Field(default_factory=list)
    project_runs: list[ExecutionRun] = Field(default_factory=list)


class ResumeResponse(RunStartResponse):
    """Response after a resume request has been accepted."""

    pass


class FrontendDefaultsResponse(BaseModel):
    """Resolved runtime defaults exposed to the frontend invocation form."""

    default_user_input: str = Field(default="")
    api_key_configured: bool = Field(default=False)
    base_url: str | None = Field(default=None)
    api_provider: str = Field(default="openai_compatible")
    api_format: str = Field(default="openai_responses")
    max_retries: int = Field(default=0)
    transport_max_attempts: int = Field(default=1)
    response_validation_max_attempts: int = Field(default=1)
    region_processing_mode: str = Field(default="serial")
    region_concurrency: int = Field(default=1)
    bbox_issue_concurrency: int = Field(default=1)
    bbox_issue_stagnation_rounds: int = Field(default=1)
    bbox_global_stagnation_rounds: int = Field(default=1)
    bbox_initial_localization_max_attempts: int = Field(default=1)
    bbox_refinement_max_rounds: int = Field(default=0)
    bbox_global_stagnation_max_rounds: int = Field(default=1)
    workflow_mode: str = Field(default="region_object")
    agent_model: str = Field(default="")
    subagent_model: str = Field(default="")
    agent_name: str = Field(default="")
    use_previous_response_id: bool = Field(default=False)
    max_retry: int = Field(default=0)
    region_repair_max_attempts: int = Field(default=0)
    object_repair_max_attempts: int = Field(default=0)
    fidelity_verification_max_attempts: int = Field(default=1)
    fidelity_verification_independent_budget: bool = Field(default=False)
    fusion_max_retry: int = Field(default=3)
    fusion_repair_max_attempts: int = Field(default=0)
    max_budget: int = Field(default=0)
    run_model_call_budget: int = Field(default=0)
    manual_refine_worker_budget: int = Field(default=15)
    supervisor_memory_enabled: bool = Field(default=False)
    supervisor_memory_persist_enabled: bool = Field(default=True)
    strategy_enabled: bool = Field(default=True)
    recognition_bbox_refine_mode: str = Field(default="llm")
    sam_provider_mode: str = Field(default="remote")
    sam_remote_url: str | None = Field(default=None)
    sam_enabled: bool = Field(default=False)
    sam_fallback_to_llm: bool = Field(default=True)


class FrontendHostInfoResponse(BaseModel):
    """Small host-capability payload consumed by both web and desktop shells."""

    host_mode: Literal["web", "desktop"] = Field(default="web")
    desktop_shell_supported: bool = Field(default=True)
    desktop_client_hint: str = Field(default="")
    web_monitor_hint: str = Field(default="")
    frontend_url: str | None = Field(default=None)
    platform: str | None = Field(default=None)
    can_open_local_file_picker: bool = Field(default=False)


class RuntimeOverridesPayload(BaseModel):
    """Persisted global runtime overrides shared by invoke and manual adjustment."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None)
    api_key_configured: bool | None = Field(
        default=None,
        description="Read-only frontend hint indicating an API key override exists without echoing the secret.",
    )
    runtime_config_path: str | None = Field(
        default=None,
        description="Read-only diagnostics path for the persisted runtime override file.",
    )
    base_url: str | None = Field(default=None)
    api_provider: str | None = Field(default=None)
    api_format: str | None = Field(default=None)
    workflow_mode: Literal["initial_only", "region", "region_object"] | None = Field(default=None)
    region_processing_mode: Literal["serial", "parallel"] | None = Field(default=None)
    region_concurrency: int | None = Field(default=None, ge=1, le=16)
    bbox_refinement_max_rounds: int | None = Field(default=None, ge=0)
    agent_model: str | None = Field(default=None)
    subagent_model: str | None = Field(default=None)
    agent_name: str | None = Field(default=None)
    use_previous_response_id: bool | None = Field(default=None)
    region_repair_max_attempts: int | None = Field(default=None, ge=0)
    object_repair_max_attempts: int | None = Field(default=None, ge=0)
    fusion_repair_max_attempts: int | None = Field(default=None, ge=0)
    run_model_call_budget: int | None = Field(default=None, ge=1)
    manual_refine_worker_budget: int | None = Field(default=None, ge=1)
    supervisor_memory_enabled: bool | None = Field(default=None)
    supervisor_memory_persist_enabled: bool | None = Field(default=None)
    strategy_enabled: bool | None = Field(default=None)
    recognition_bbox_refine_mode: Literal["llm", "sam", "hybrid"] | None = Field(default=None)
    sam_provider_mode: Literal["local", "remote"] | None = Field(default=None)
    sam_remote_url: str | None = Field(default=None)
    sam_enabled: bool | None = Field(default=None)
    sam_fallback_to_llm: bool | None = Field(default=None)


class ObjectBboxRefinementResult(BaseModel):
    """Normalized result returned by one issue-level object bbox refinement provider call."""

    provider: str
    mode: Literal["llm", "sam_local", "sam_remote"]
    status: Literal["applied", "skipped", "unavailable", "failed"]
    target_id: str
    bbox: RegionBoundingBox | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(default="")
    issue: BboxQualityIssue | None = Field(default=None)
    raw_text: str = Field(default="")
    artifacts: dict = Field(default_factory=dict)


class BudgetSnapshot(BaseModel):
    """Persisted budget state for a resumable conversion run."""

    limit: int = Field(default=0, ge=0)
    used: int = Field(default=0, ge=0)
    remaining: int = Field(default=0, ge=0)
    mode: Literal["carry_forward", "top_up"] = Field(default="top_up")


class RetrySnapshot(BaseModel):
    """Persisted retry counters for resumable conversion runs."""

    max_retry: int = Field(default=0, ge=0)
    limits: dict[str, int | bool] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    exhausted_tasks: list[str] = Field(default_factory=list)


class RegionResumeState(BaseModel):
    """Persisted per-region resume status."""

    region_id: str
    status: Literal["pending", "running", "completed", "failed", "paused"] = Field(default="pending")
    phase: Literal["initial", "refine"] | None = Field(default=None)
    last_completed_step: str | None = Field(default=None)
    retry_exhausted: bool = Field(default=False)
    artifact_dir: str | None = Field(default=None)


class RunFailureSnapshot(BaseModel):
    """Structured persisted failure or pause reason."""

    type: str | None = Field(default=None)
    message: str | None = Field(default=None)
    failure_stage: str | None = Field(default=None)
    root_cause_type: str | None = Field(default=None)
    root_cause_message: str | None = Field(default=None)
    diagnostic: FailureDiagnostic | None = Field(default=None)


class RunTimestampsSnapshot(BaseModel):
    """Persisted timestamps for a resumable run."""

    started_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)
    paused_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class RunState(BaseModel):
    """Persisted state machine for resumable raster-to-SVG runs."""

    run_id: str
    thread_id: str | None = Field(default=None)
    project_name: str = Field(default="agent-run")
    status: Literal["queued", "running", "paused", "completed", "failed", "cancelled"] = Field(default="queued")
    pause_reason: str | None = Field(default=None)
    current_stage: str = Field(default="queued")
    resume_token: str | None = Field(default=None)
    request: dict = Field(default_factory=dict)
    budget: BudgetSnapshot = Field(default_factory=BudgetSnapshot)
    retry: RetrySnapshot = Field(default_factory=RetrySnapshot)
    checkpoints: dict[str, bool] = Field(default_factory=dict)
    regions: list[RegionResumeState] = Field(default_factory=list)
    failure: RunFailureSnapshot = Field(default_factory=RunFailureSnapshot)
    timestamps: RunTimestampsSnapshot = Field(default_factory=RunTimestampsSnapshot)


class ResumePlan(BaseModel):
    """A computed plan describing how an interrupted run can resume."""

    available: bool = Field(default=False)
    run_dir: str
    current_stage: str | None = Field(default=None)
    resume_stage: str | None = Field(default=None)
    reason: str | None = Field(default=None)
    status: str | None = Field(default=None)
    budget: BudgetSnapshot = Field(default_factory=BudgetSnapshot)
    completed_regions: list[str] = Field(default_factory=list)
    pending_regions: list[str] = Field(default_factory=list)


class ResumeRunRequest(BaseModel):
    """Request body for resuming a previous raster-to-SVG run from artifacts."""

    run_id: str = Field(description="Owned run identifier to continue.")
    thread_id: str = Field(description="Workspace thread that owns the run.")
    extra_budget: int | None = Field(default=None, ge=0, description="Optional additional model-call budget.")
    budget_mode: Literal["carry_forward", "top_up"] = Field(default="top_up")


class ArtifactResumeInfo(BaseModel):
    """Resume metadata surfaced to the frontend artifact panel."""

    available: bool = Field(default=False)
    reason: str | None = Field(default=None)
    current_stage: str | None = Field(default=None)
    resume_stage: str | None = Field(default=None)
    pause_reason: str | None = Field(default=None)
    budget_used: int | None = Field(default=None)
    budget_limit: int | None = Field(default=None)
    budget_remaining: int | None = Field(default=None)
    completed_regions: int = Field(default=0)
    pending_regions: int = Field(default=0)


class ArtifactFileEntry(BaseModel):
    """One artifact file exposed to the frontend."""

    relative_path: str = Field(description="Path relative to the run artifact directory.")
    name: str = Field(description="Filename only.")
    kind: str = Field(description="Simple file kind such as svg, png, json, or txt.")
    size_bytes: int = Field(description="File size in bytes.")
    modified_at: datetime = Field(description="Last-modified timestamp.")
    preview_url: str | None = Field(default=None, description="Inline preview URL when supported.")
    download_url: str = Field(description="Direct download URL for the file.")


class ArtifactPreviewSet(BaseModel):
    """Best-effort preview links for common comparison assets."""

    input_image_url: str | None = Field(default=None)
    output_svg_url: str | None = Field(default=None)
    output_png_url: str | None = Field(default=None)
    initial_svg_url: str | None = Field(default=None)


class ArtifactRequestSummary(BaseModel):
    """Resolved request details shown in the frontend."""

    message: str = Field(default="")
    image_path: str | None = Field(default=None)
    api_provider: str | None = Field(default=None)
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    api_format: str | None = Field(default=None)
    max_retries: int | None = Field(default=None)
    transport_max_attempts: int | None = Field(default=None)
    response_validation_max_attempts: int | None = Field(default=None)
    region_processing_mode: str | None = Field(default=None)
    region_concurrency: int | None = Field(default=None)
    bbox_issue_concurrency: int | None = Field(default=None)
    bbox_issue_stagnation_rounds: int | None = Field(default=None)
    bbox_global_stagnation_rounds: int | None = Field(default=None)
    bbox_initial_localization_max_attempts: int | None = Field(default=None)
    bbox_refinement_max_rounds: int | None = Field(default=None)
    bbox_global_stagnation_max_rounds: int | None = Field(default=None)
    workflow_mode: str | None = Field(default=None)
    project_name: str | None = Field(default=None)
    agent_model: str | None = Field(default=None)
    subagent_model: str | None = Field(default=None)
    agent_name: str | None = Field(default=None)
    use_previous_response_id: bool | None = Field(default=None)
    max_retry: int | None = Field(default=None)
    region_repair_max_attempts: int | None = Field(default=None)
    object_repair_max_attempts: int | None = Field(default=None)
    fidelity_verification_max_attempts: int | None = Field(default=None)
    fidelity_verification_independent_budget: bool | None = Field(default=None)
    fusion_max_retry: int | None = Field(default=None)
    fusion_repair_max_attempts: int | None = Field(default=None)
    max_budget: int | None = Field(default=None)
    run_model_call_budget: int | None = Field(default=None)
    supervisor_memory_enabled: bool | None = Field(default=None)
    supervisor_memory_persist_enabled: bool | None = Field(default=None)
    strategy_enabled: bool | None = Field(default=None)
    recognition_bbox_refine_mode: str | None = Field(default=None)
    sam_provider_mode: str | None = Field(default=None)
    sam_remote_url: str | None = Field(default=None)
    sam_enabled: bool | None = Field(default=None)
    sam_fallback_to_llm: bool | None = Field(default=None)


class ArtifactBox(BaseModel):
    """One region or object bounding box shown in the artifact viewer."""

    x: int
    y: int
    width: int
    height: int


class ArtifactObjectOverlay(BaseModel):
    """One recognized object with an optional viewer bbox."""

    object_id: str
    object_type: str
    description: str = Field(default="")
    bbox: ArtifactBox | None = Field(default=None)
    bbox_space: Literal["region_local", "global"] = Field(default="global")
    retry_limit: int | None = Field(default=None)
    retry_used: int | None = Field(default=None)
    retry_exhausted: bool | None = Field(default=None)


class ArtifactRegionOverlay(BaseModel):
    """One planned region plus its recognized objects."""

    region_id: str
    description: str = Field(default="")
    bbox: ArtifactBox
    bbox_space: Literal["global"] = Field(default="global")
    status: str | None = Field(default=None)
    objects: list[ArtifactObjectOverlay] = Field(default_factory=list)
    retry_limit: int | None = Field(default=None)
    retry_used: int | None = Field(default=None)
    retry_exhausted: bool | None = Field(default=None)


class ArtifactOutputFrame(BaseModel):
    """One whole-canvas output preview frame in chronological order."""

    frame_id: str
    title: str
    scope: str
    target_id: str | None = Field(default=None)
    iteration: int | None = Field(default=None)
    relative_path: str
    preview_url: str
    download_url: str
    modified_at: datetime
    update_summary: list[str] = Field(default_factory=list)
    remaining_issues: list[str] = Field(default_factory=list)


class ArtifactManualAdjustmentVersion(BaseModel):
    """One persisted manual adjustment result shown outside the progress slider."""

    adjustment_id: str
    title: str
    relative_path: str
    preview_url: str
    download_url: str
    modified_at: datetime
    base_frame_id: str | None = Field(default=None)
    base_adjustment_id: str | None = Field(default=None)
    base_title: str | None = Field(default=None)
    base_preview_url: str | None = Field(default=None)
    base_download_url: str | None = Field(default=None)
    workflow_trace: "WorkflowTrace" = Field(default_factory=lambda: WorkflowTrace())
    adjustment_error: dict | None = Field(default=None)


class WorkflowTraceNode(BaseModel):
    """A compact execution-trace node for the frontend workflow tree."""

    node_id: str
    parent_node_id: str | None = Field(default=None)
    label: str
    kind: Literal["stage", "region", "object", "loop", "terminal"] = Field(default="stage")
    status: Literal["pending", "running", "success", "issue_detected", "retrying", "blocked", "failed", "skipped"] = Field(
        default="pending"
    )
    summary: str | None = Field(default=None)
    execution_mode: Literal["serial", "parallel"] = Field(default="serial")
    target_type: Literal["run", "region", "object"] = Field(default="run")
    target_id: str | None = Field(default=None)
    stage_key: str | None = Field(default=None)
    iteration: int | None = Field(default=None)
    route: str | None = Field(default=None)
    semantic_stage: str | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    event_index: int | None = Field(default=None)
    meta: dict = Field(default_factory=dict)


class WorkflowTraceSummary(BaseModel):
    """Small summary payload for the workflow trace header."""

    status: str = Field(default="idle")
    active_node_id: str | None = Field(default=None)
    regions_total: int = Field(default=0, ge=0)
    retrying_regions: int = Field(default=0, ge=0)
    blocked_regions: int = Field(default=0, ge=0)
    direct_accept_regions: int = Field(default=0, ge=0)
    total_duration_ms: int | None = Field(default=None)
    loop_iterations_total: int = Field(default=0, ge=0)
    budget_used: int | None = Field(default=None, ge=0)
    budget_limit: int | None = Field(default=None, ge=0)


class WorkflowTrace(BaseModel):
    """Frontend-facing workflow trace tree."""

    run_id: str | None = Field(default=None)
    artifact_dir: str | None = Field(default=None)
    summary: WorkflowTraceSummary = Field(default_factory=WorkflowTraceSummary)
    nodes: list[WorkflowTraceNode] = Field(default_factory=list)


class ArtifactSnapshot(BaseModel):
    """Current run artifact metadata for preview, download, and comparison."""

    available: bool = Field(description="Whether the final artifact output is ready for result-only actions such as manual adjustment.")
    bbox_overlays_ready: bool = Field(
        default=False,
        description="Whether refined bbox overlays are ready to render on the input preview before final output completion.",
    )
    run_id: str | None = Field(default=None)
    project_name: str | None = Field(default=None)
    status: str | None = Field(default=None)
    current_stage: str | None = Field(default=None)
    failure_stage: str | None = Field(default=None)
    artifact_dir: str | None = Field(default=None)
    artifact_revision: str | None = Field(default=None)
    request: ArtifactRequestSummary | None = Field(default=None)
    messages: list[ChatMessage] = Field(default_factory=list)
    overview: dict = Field(default_factory=dict)
    canvas_width: int | None = Field(default=None)
    canvas_height: int | None = Field(default=None)
    regions: list[ArtifactRegionOverlay] = Field(default_factory=list)
    output_frames: list[ArtifactOutputFrame] = Field(default_factory=list)
    manual_adjustments: list[ArtifactManualAdjustmentVersion] = Field(default_factory=list)
    workflow_trace: WorkflowTrace = Field(default_factory=WorkflowTrace)
    manual_workflow_trace: WorkflowTrace = Field(default_factory=WorkflowTrace)
    manual_adjustment_error: dict | None = Field(default=None)
    failure_diagnostic: FailureDiagnostic | None = Field(default=None)
    previews: ArtifactPreviewSet = Field(default_factory=ArtifactPreviewSet)
    resume: ArtifactResumeInfo = Field(default_factory=ArtifactResumeInfo)
    files: list[ArtifactFileEntry] = Field(default_factory=list)


class ManualAdjustmentIssue(BaseModel):
    """A lightweight local issue used only by post-conversion manual adjustment."""

    criterion: str
    reason: str
    severity: Literal["low", "medium", "high"] = Field(default="medium")


class ManualAdjustmentPreEditAnalysis(BaseModel):
    """Structured pre-edit analysis for agent-mode post-conversion manual adjustment."""

    goal_summary: str
    desired_outcomes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    review_checks: list[str] = Field(default_factory=list)
    baseline_issues: list[ManualAdjustmentIssue] = Field(default_factory=list)
    edit_strategy: Literal["object", "object_collection", "subtree", "region", "bbox_fragment"] = Field(default="object")
    rewrite_policy: Literal["patch_preferred", "rewrite_allowed", "rewrite_required"] = Field(default="patch_preferred")


class ManualSvgAdjustmentResult(BaseModel):
    """Structured result for one manual SVG adjustment pass."""

    svg_fragment: str
    edit_operation: Literal[
        "replace_object",
        "replace_object_collection",
        "replace_subtree",
        "replace_region",
        "replace_bbox_fragment",
    ] = Field(default="replace_object")
    target_ids: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    new_ids: list[str] = Field(default_factory=list)
    rewrite_used: bool = Field(default=False)
    change_summary: list[str] = Field(default_factory=list, max_length=3)
    remaining_limitations: list[str] = Field(default_factory=list)

    @field_validator("change_summary", mode="before")
    @classmethod
    def normalize_change_summary(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        normalized: list[str] = []
        for item in value:
            text = " ".join(str(item).strip().split())
            if not text:
                continue
            normalized.append(text[:160])
        return normalized[:3]


class ManualAdjustmentWorkerPassResult(BaseModel):
    """Single-call worker-mode result that reviews the target and edits it in one pass."""

    goal_summary: str
    desired_outcomes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    review_checks: list[str] = Field(default_factory=list)
    baseline_issues: list[ManualAdjustmentIssue] = Field(default_factory=list)
    edit_strategy: Literal["object", "object_collection", "subtree", "region", "bbox_fragment"] = Field(default="object")
    rewrite_policy: Literal["patch_preferred", "rewrite_allowed", "rewrite_required"] = Field(default="patch_preferred")
    svg_fragment: str
    edit_operation: Literal[
        "replace_object",
        "replace_object_collection",
        "replace_subtree",
        "replace_region",
        "replace_bbox_fragment",
    ] = Field(default="replace_object")
    target_ids: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    new_ids: list[str] = Field(default_factory=list)
    rewrite_used: bool = Field(default=False)
    change_summary: list[str] = Field(default_factory=list, max_length=3)
    remaining_limitations: list[str] = Field(default_factory=list)

    @field_validator("change_summary", mode="before")
    @classmethod
    def normalize_change_summary(cls, value: object) -> list[str]:
        return ManualSvgAdjustmentResult.normalize_change_summary(value)


class ManualAdjustmentReview(BaseModel):
    """Review result for an agent-mode manual SVG adjustment pass."""

    passed: bool = Field(default=False)
    regression_detected: bool = Field(default=False)
    remaining_issues: list[ManualAdjustmentIssue] = Field(default_factory=list)
    summary: str = Field(default="")


class ManualAdjustmentRequest(BaseModel):
    """Request body for post-conversion manual adjustment."""

    thread_id: str
    run_id: str | None = Field(default=None)
    base_frame_id: str | None = Field(default=None)
    base_adjustment_id: str | None = Field(default=None)
    mode: Literal["worker", "agent"] = Field(default="worker")
    agent_budget: int | None = Field(default=None, ge=1, le=12)
    target_region_id: str | None = Field(default=None)
    target_object_ids: list[str] = Field(default_factory=list)
    selection_bbox: ArtifactBox | None = Field(default=None)
    reference_selection_bbox: ArtifactBox | None = Field(default=None)
    target_description: str | None = Field(default=None)
    user_introduction: str = Field(default="")
    use_reference_images: bool = Field(default=True)
    reference_image_paths: list[str] = Field(default_factory=list)
    include_default_crop: bool = Field(default=True)
    include_no_image: bool = Field(default=False)


class ManualAdjustmentResponse(BaseModel):
    """Response after a manual adjustment request has completed."""

    ok: bool = Field(default=True)
    run_id: str
    scope: str
    target_ids: list[str] = Field(default_factory=list)
    applied_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    edit_strategy: str | None = Field(default=None)
    artifact_snapshot: ArtifactSnapshot
