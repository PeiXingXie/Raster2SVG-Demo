"""Shared prompt text for bbox coordinate semantics."""

BBOX_COORDINATE_CONVENTION_RULE = (
    'BBox coordinate convention: bbox must be {"x": int, "y": int, "width": int, "height": int}; '
    "x and y are the top-left corner of the box; width and height are box size, not bottom-right coordinates; "
    "the right edge is x + width and the bottom edge is y + height."
)

GLOBAL_BBOX_COORDINATE_RULE = (
    "Bboxes in this request are global source-image coordinates unless explicitly stated otherwise."
)

GLOBAL_SVG_OUTPUT_COORDINATE_RULE = (
    "Return SVG geometry in the same global source-image coordinate frame as the provided bboxes."
)

GLOBAL_CROP_VISUAL_EVIDENCE_RULE = (
    "Attached crop images are visual evidence for appearance and comparison only; "
    "do not treat a crop's top-left as SVG coordinate (0,0), except in dedicated bbox-localization workers."
)

GLOBAL_NO_OFFSET_REAPPLICATION_RULE = (
    "Do not add region bbox offsets or object bbox offsets again when interpreting provided bboxes or current SVG geometry."
)

GLOBAL_NO_LOCAL_COORDINATE_GUESS_RULE = (
    "Do not infer or report new numeric crop-local coordinates from crop images; "
    "use provided bboxes and current SVG structure only as coordinate-frame evidence."
)
