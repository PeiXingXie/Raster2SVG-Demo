# 核心转换工作流

## 1. 主流程

以下流程直接对应 `RasterToSvgPipeline.run()` 的现行阶段。

```mermaid
flowchart TD
    Start(["开始 Run"]) --> Load["loading-input<br/>检查、复制并读取图片元数据"]
    Load --> Layout["layout-detection<br/>布局识别、Region 规划、bbox review、Checklist、SVG template"]
    Layout --> Crop["region-cropping<br/>为每个 Region 生成 crop.png"]
    Crop --> InitialRegion["region-process initial<br/>区域识别与第一版 SVG fragment"]
    InitialRegion --> InitialMerge["initial-integration<br/>合并第一版 Region SVG 并审查"]
    InitialMerge --> Mode{"workflow_mode"}

    Mode -->|"initial_only"| SkipRefine["直接采用初始 Region 结果"]
    Mode -->|"标准模式"| Refine["region-process refine<br/>Region review、对象修复、区域修复"]

    SkipRefine --> FinalMerge["final-integration<br/>合并最终 Region SVG"]
    Refine --> FinalMerge
    FinalMerge --> FinalReview["最终渲染与视觉审查"]
    FinalReview --> Report["summarizing-result<br/>report.json + report.md"]
    Report --> Completed(["completed"])

    Load -. "异常" .-> Failed(["failed"])
    Layout -. "异常" .-> Failed
    Crop -. "异常" .-> Failed
    InitialRegion -. "异常" .-> Failed
    Refine -. "异常" .-> Failed
    FinalMerge -. "异常" .-> Failed

    Layout -. "预算耗尽" .-> Paused(["paused: budget_exhausted"])
    InitialRegion -. "预算耗尽" .-> Paused
    Refine -. "预算耗尽" .-> Paused
    FinalMerge -. "预算耗尽" .-> Paused
    Paused -->|"追加预算并恢复"| Resume["从最近 checkpoint 继续"]
    Resume --> Layout
    Resume --> Crop
    Resume --> InitialRegion
    Resume --> InitialMerge
    Resume --> Refine
    Resume --> FinalMerge
```

## 2. Layout Planning 阶段

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant L as Layout Worker
    participant B as BBox Supervisor
    participant C as Checklist Worker
    participant F as File System

    P->>L: 输入整图、宽度、高度
    L-->>P: LayoutDetectionResult + raw text
    P->>F: 写 layout_detection.json/raw.txt
    P->>P: normalize_regions
    P->>B: review_layout(regions)
    B-->>P: 修正后的 regions + bbox review
    P->>C: 整图 + layout overview + regions
    C-->>P: image-aware checklist
    P->>P: build_svg_template
    P->>F: 写 checklist.json / regions.json / template.svg
```

该阶段的输出合同是：

- 画布尺寸和整体描述；
- 归一化、非重叠且可裁剪的 Region 列表；
- 后续生成和审查使用的 Checklist；
- 用于融合各 Region fragment 的 SVG 模板。

注意：bbox review 是 Layout Supervisor 的内部步骤，不是主 `run()` 中独立的顶层阶段。

## 3. Region 初始生成

每个 Region 都会建立独立工作目录，并在串行或并行模式下处理。

```mermaid
flowchart TD
    RegionInput["Region crop + Region plan + Checklist"] --> Recognize["Region Recognition Worker<br/>识别对象、描述和 bbox"]
    Recognize --> BBoxCheck["识别 bbox 校验/细化"]
    BBoxCheck --> Generate["Region SVG Worker<br/>生成第一版 SVG fragment"]
    Generate --> Finalize["确定性 SVG 规整<br/>对象分组、ID、坐标与 fragment"]
    Finalize --> Persist["initial_result.json<br/>initial_region_elements.svgfrag"]

    SamLegacy["SAM provider 接口<br/>遗留、即将移除"] -. "不应作为未来依赖" .-> BBoxCheck
```

SAM 相关接口在代码中尚存，但架构决策应按“待移除”处理；文档、测试和新功能不应扩大其依赖范围。

## 4. Initial Integration 的作用

第一轮 Region 生成完成后，系统不会立即逐区域修复，而是先合并为完整画布：

1. 将每个 Region 的初始 fragment 注入 SVG template；
2. 渲染完整 SVG 为可供模型比较的预览；
3. 执行全图审查；
4. 为后续 Region refinement 提供全局视觉上下文。

这避免了只看局部 crop 时无法发现的比例、对齐、跨区域一致性和整体风格问题。

## 5. Region Refinement 与 Object Repair

```mermaid
flowchart TD
    Review["审查 Region 当前结果"] --> Decision{"问题类型"}
    Decision -->|"无问题"| Accept["接受 Region"]
    Decision -->|"对象级问题"| ObjectIssues["提取独立 Object issues"]
    Decision -->|"区域整体问题"| RegionRepair["Region repair"]

    ObjectIssues --> Capacity["从共享 Region 并发池借用空闲槽位"]
    Capacity --> ObjGen["对象生成/修复"]
    ObjGen --> ObjReview["对象渲染与审查"]
    ObjReview --> ObjPass{"通过？"}
    ObjPass -->|"否且仍可重试"| ObjGen
    ObjPass -->|"通过或重试耗尽"| MergeObject["写回 object_svg_index"]

    MergeObject --> RegionReview["重新生成/审查 Region"]
    RegionRepair --> RegionReview
    RegionReview --> RegionPass{"Region 通过？"}
    RegionPass -->|"否且仍可重试"| Decision
    RegionPass -->|"通过或策略停止"| Persist["final_result.json<br/>final_region_elements.svgfrag"]
    Accept --> Persist
```

### 并发策略

- Region 可以通过 `region_processing_mode=parallel` 并行处理。
- 最大 Region Worker 数由 `region_concurrency` 限制。
- 对象修复优先在当前线程处理第一个对象，再借用 Region 阶段剩余并发槽位处理其他独立对象。
- 输出会按原始 Region 顺序重新组装，避免并发完成顺序影响融合顺序。

### 重试策略

- Region 和 Object 使用独立的 retry task key。
- 每次循环先检查是否仍有 retry capacity。
- 重试耗尽后保留最后一个可用 SVG，而不是无限循环。
- Review、Policy 和停滞条件共同决定是否继续。

## 6. Fusion 与最终输出

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant F as Fusion Supervisor
    participant R as SVG Renderer
    participant V as Final Review Worker
    participant D as Artifact Store

    P->>F: template + merged region fragments
    F->>D: 写 final.svg
    F->>R: 渲染完整 SVG
    alt 渲染成功
        R-->>V: PNG preview + SVG file
        V-->>F: FinalReviewResult
        F->>D: 写 final_review.json/raw.txt
    else 渲染失败
        R-->>F: renderer error
        F->>D: 写 render_error.txt
        F-->>P: 抛出 SvgPreviewRenderError
    end
    P->>D: 写 report.json / report.md
```

最终有效性不仅取决于 XML/SVG 是否可解析，还会综合最终 Review 是否仍有未解决问题。

## 7. 人工调整后处理

人工调整不是核心自动转换管线中的阶段，而是完成 Run 后的独立后处理：

```mermaid
flowchart LR
    Completed["已完成 Run"] --> Select["用户选择 Region / Object / bbox"]
    Select --> References["可选参考图或输入截图"]
    References --> Mode{"调整模式"}
    Mode -->|"worker"| OnePass["单次分析并编辑"]
    Mode -->|"agent"| Loop["分析 → 编辑 → 审查循环"]
    OnePass --> NewVersion["保存 manual adjustment version"]
    Loop --> NewVersion
    NewVersion --> Compare["前端与基准 Frame 对比"]
```

人工调整生成新版本，不应静默覆盖自动转换的原始最终结果。

