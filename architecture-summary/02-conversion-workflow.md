# Core Conversion Workflow

## 1. Main Flow

The following flow maps directly to the current stages in `RasterToSvgPipeline.run()`.

```mermaid
flowchart TD
    Start(["Start Run"]) --> Load["loading-input<br/>validate, copy, and read image metadata"]
    Load --> Layout["layout-detection<br/>layout recognition, Region planning, bbox review, Checklist, SVG template"]
    Layout --> Crop["region-cropping<br/>create crop.png for each Region"]
    Crop --> InitialRegion["region-process initial<br/>region recognition and first SVG fragment"]
    InitialRegion --> InitialMerge["initial-integration<br/>merge first-pass Region SVGs and review"]
    InitialMerge --> Mode{"workflow_mode"}

    Mode -->|"initial_only"| SkipRefine["use initial Region results directly"]
    Mode -->|"region"| RefineRegion["region-process refine<br/>Region review and region repair"]
    Mode -->|"region_object"| RefineObject["region-process refine<br/>Region review, object repair, region repair"]

    SkipRefine --> FinalMerge["final-integration<br/>merge final Region SVGs"]
    RefineRegion --> FinalMerge
    RefineObject --> FinalMerge
    FinalMerge --> FinalReview["final rendering and visual review"]
    FinalReview --> Report["summarizing-result<br/>report.json + report.md"]
    Report --> Completed(["completed"])

    Load -. "exception" .-> Failed(["failed"])
    Layout -. "exception" .-> Failed
    Crop -. "exception" .-> Failed
    InitialRegion -. "exception" .-> Failed
    RefineRegion -. "exception" .-> Failed
    RefineObject -. "exception" .-> Failed
    FinalMerge -. "exception" .-> Failed

    Layout -. "budget exhausted" .-> Paused(["paused: budget_exhausted"])
    InitialRegion -. "budget exhausted" .-> Paused
    RefineRegion -. "budget exhausted" .-> Paused
    RefineObject -. "budget exhausted" .-> Paused
    FinalMerge -. "budget exhausted" .-> Paused
    Load -. "user cancel" .-> Cancelled(["cancelled"])
    Layout -. "user cancel" .-> Cancelled
    InitialRegion -. "user cancel" .-> Cancelled
    RefineRegion -. "user cancel" .-> Cancelled
    RefineObject -. "user cancel" .-> Cancelled
    FinalMerge -. "user cancel" .-> Cancelled
    Paused -->|"add budget and resume"| Resume["continue from latest checkpoint"]
    Resume --> Layout
    Resume --> Crop
    Resume --> InitialRegion
    Resume --> InitialMerge
    Resume --> RefineRegion
    Resume --> RefineObject
    Resume --> FinalMerge
```

`workflow_mode` currently has three values: `initial_only` skips refinement; `region` runs only region-level review and region repair; `region_object` is the default main path and enables object-level repair in addition to region-level repair. Object repair does not run in every refinement mode.

## 2. Layout Planning Stage

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant L as Layout Worker
    participant B as BBox Supervisor
    participant C as Checklist Worker
    participant F as File System

    P->>L: full image, width, height
    L-->>P: LayoutDetectionResult + raw text
    P->>F: write layout_detection.json/raw.txt
    P->>P: normalize_regions
    P->>B: review_layout(regions)
    B-->>P: corrected regions + bbox review
    P->>C: full image + layout overview + regions
    C-->>P: image-aware checklist
    P->>P: build_svg_template
    P->>F: write checklist.json / regions.json / template.svg
```

The output contract of this stage is:

- canvas dimensions and overall description;
- normalized, non-overlapping, croppable Region list;
- Checklist used by downstream generation and review;
- SVG template used to fuse Region fragments.

Note: bbox review is an internal step of the Layout Supervisor, not a separate top-level stage in `run()`.

## 3. Initial Region Generation

Each Region gets an independent working directory and can be processed serially or in parallel.

```mermaid
flowchart TD
    RegionInput["Region crop + Region plan + Checklist"] --> Recognize["Region Recognition Worker<br/>identify objects, descriptions, and bbox"]
    Recognize --> BBoxCheck["recognition bbox validation/refinement"]
    BBoxCheck --> Generate["Region SVG Worker<br/>generate first-pass SVG fragment"]
    Generate --> Finalize["deterministic SVG normalization<br/>object groups, IDs, coordinates, fragment"]
    Finalize --> Persist["initial_result.json<br/>initial_region_elements.svgfrag"]

    SamLegacy["SAM provider interface<br/>legacy, pending removal"] -. "should not be a future dependency" .-> BBoxCheck
```

SAM-related interfaces still exist in code, but architecture decisions should treat them as pending removal. Documentation, tests, and new features should not expand their dependency surface.

## 4. Purpose of Initial Integration

After first-pass Region generation, the system does not immediately repair each region. It first merges the regions into a full canvas:

1. inject each Region's initial fragment into the SVG template;
2. render the complete SVG as a preview for model comparison;
3. run full-image review;
4. provide global visual context for later Region refinement.

This catches proportion, alignment, cross-region consistency, and overall style issues that cannot be reliably seen from local crops alone.

## 5. Region Refinement and Object Repair

```mermaid
flowchart TD
    Review["Review current Region result"] --> Decision{"Issue type"}
    Decision -->|"no issue"| Accept["Accept Region"]
    Decision -->|"object issues and workflow_mode=region_object"| ObjectIssues["Extract independent Object issues"]
    Decision -->|"whole-region issues"| RegionRepair["Region repair"]

    ObjectIssues --> Capacity["Borrow free slots from the shared Region concurrency pool"]
    Capacity --> ObjGen["Object generation/repair"]
    ObjGen --> ObjReview["Object rendering and review"]
    ObjReview --> ObjPass{"Pass?"}
    ObjPass -->|"no, retry capacity remains"| ObjGen
    ObjPass -->|"pass or retries exhausted"| MergeObject["Write back to object_svg_index"]

    MergeObject --> RegionReview["Regenerate/review Region"]
    RegionRepair --> RegionReview
    RegionReview --> RegionPass{"Region passed?"}
    RegionPass -->|"no, retry capacity remains"| Decision
    RegionPass -->|"passed or policy stops"| Persist["final_result.json<br/>final_region_elements.svgfrag"]
    Accept --> Persist
```

### Concurrency Strategy

- Regions can run in parallel with `region_processing_mode=parallel`.
- The maximum number of Region workers is capped by `region_concurrency`.
- Object repair processes the first object on the current thread, then borrows remaining Region-stage slots for other independent objects.
- Top-level conversion Runs are also capped by the API `BoundedExecutor`, so capacity planning must consider the Run queue, Region concurrency, and borrowed object-repair slots together.
- Results are reassembled in original Region order, so parallel completion order does not change fusion order.

### Retry Strategy

- Region and Object work use independent retry task keys.
- Each loop checks whether retry capacity remains before attempting more work.
- When retries are exhausted, the last usable SVG is retained rather than looping forever.
- Review, policy rules, and stagnation conditions jointly decide whether to continue.

## 6. Fusion and Final Output

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant F as Fusion Supervisor
    participant R as SVG Renderer
    participant V as Final Review Worker
    participant D as Artifact Store

    P->>F: template + merged region fragments
    F->>D: write final.svg
    F->>R: render full SVG
    alt render succeeds
        R-->>V: PNG preview + SVG file
        V-->>F: FinalReviewResult
        F->>D: write final_review.json/raw.txt
    else render fails
        R-->>F: renderer error
        F->>D: write render_error.txt
        F-->>P: raise SvgPreviewRenderError
    end
    P->>D: write report.json / report.md
```

Final validity is not only XML/SVG parseability. It also incorporates whether the final Review still reports unresolved issues.

## 7. Manual Adjustment Post-Processing

Manual adjustment is not a stage of the automatic conversion pipeline. It is an independent post-processing flow after a Run completes.

```mermaid
flowchart LR
    Completed["Completed Run"] --> Select["User selects Region / Object / bbox"]
    Select --> References["Optional reference image or screenshot"]
    References --> Mode{"Adjustment mode"}
    Mode -->|"worker"| OnePass["Single analysis and edit"]
    Mode -->|"agent"| Loop["Analyze -> edit -> review loop"]
    OnePass --> NewVersion["Save manual adjustment version"]
    Loop --> NewVersion
    NewVersion --> Compare["Frontend compares with baseline frame"]
```

Manual adjustment creates a new version. It should not silently overwrite the original final result from automatic conversion.
