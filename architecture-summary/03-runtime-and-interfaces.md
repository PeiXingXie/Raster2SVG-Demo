# 运行时、接口与交互时序

## 1. 桌面安装版启动时序

```mermaid
sequenceDiagram
    actor User as 用户
    participant E as Electron Main
    participant FS as 用户数据目录
    participant B as Bundled Backend
    participant API as FastAPI
    participant UI as desktop.html

    User->>E: 启动 Shape Studio
    E->>E: 判断 packaged mode
    E->>E: 在 127.0.0.1 查找空闲端口
    E->>FS: 创建 artifacts/runs 与 logs
    E->>B: spawn raster-svg-api(.exe)
    B->>API: 使用 APP_HOST/APP_PORT 启动
    E->>API: 轮询 GET /health
    alt 后端健康
        API-->>E: 200 {status: ok}
        E->>UI: 打开 /static/desktop.html
    else 超时或后端缺失
        E->>User: 显示启动失败及 backend.log 路径
        E->>E: 退出应用
    end
    User->>E: 关闭应用
    E->>B: 终止后端进程树
```

## 2. 一次转换请求的端到端时序

```mermaid
sequenceDiagram
    actor User as 用户
    participant UI as Desktop UI
    participant API as FastAPI
    participant TS as ThreadStore
    participant EX as Background Executor
    participant PL as RasterToSvgPipeline
    participant M as Model API
    participant AF as Artifact Files

    UI->>API: POST /threads
    API->>TS: create_thread()
    TS-->>UI: thread_id

    User->>UI: 选择图片并开始
    UI->>API: POST /uploads(base64)
    API->>AF: 保存到 _uploads
    AF-->>UI: image_path

    UI->>API: POST /invoke(request + thread_id)
    API->>TS: 创建 queued/running Run
    API->>AF: 写 metadata
    API->>EX: submit background conversion
    API-->>UI: run_id + started

    EX->>PL: RasterToSvgPipeline.run()
    loop 每个模型工作单元
        PL->>M: 图片/SVG/结构化 Prompt
        M-->>PL: 结构化结果 + raw text
        PL->>AF: 写中间结果、trace、model logs
        PL->>TS: push_event / update_run
    end

    par UI 状态轮询
        UI->>API: GET /threads/{id}/snapshot
        API->>TS: 读取消息、事件和 Run
        TS-->>UI: AgentResponse
    and UI Artifact 轮询
        UI->>API: GET /threads/{id}/artifacts
        API->>AF: 汇总预览、文件和 Workflow Trace
        AF-->>UI: ArtifactSnapshot
    end

    PL-->>EX: report markdown
    EX->>TS: finish_run(completed)
    EX->>AF: 写 output 与 metadata
    UI->>API: 最后一次 snapshot/artifacts
    API-->>UI: final.svg、preview、report、files
```

## 3. 后台执行模型

HTTP `/invoke` 不等待完整转换：

1. API 验证 Thread 和请求；
2. 创建 Run 和 Artifact 目录；
3. 将 `_run_agent_in_background` 提交到线程池；
4. 立即向前端返回 Run Start Response；
5. 前端通过轮询读取运行进度。

当前 API 全局线程池为有限 Worker 数，防止单个服务进程无限创建顶层 Run 线程。每个 Pipeline 内部还可能为 Region/Object 创建局部线程池，因此容量规划需要同时考虑：

```text
并发 Run 数 × 每个 Run 的 Region 并发 × 模型端限流
```

## 4. Thread、Run 与 Artifact 的关系

```mermaid
erDiagram
    THREAD ||--o{ RUN : contains
    RUN ||--|| ARTIFACT_DIRECTORY : owns
    RUN ||--o{ EVENT : emits
    THREAD ||--o{ MESSAGE : contains
    ARTIFACT_DIRECTORY ||--|| RUN_STATE : persists
    ARTIFACT_DIRECTORY ||--o{ ARTIFACT_FILE : contains
    ARTIFACT_DIRECTORY ||--o{ MANUAL_ADJUSTMENT : versions

    THREAD {
        string thread_id
        string status
        string current_run_id
    }
    RUN {
        string run_id
        string project_name
        string status
        string current_stage
        string artifact_dir
    }
    RUN_STATE {
        string status
        string current_stage
        json checkpoints
        json budget
        json retry
    }
```

- Thread 是前端会话容器，可以保留多次 Run 历史。
- Run 是一次具体转换或恢复执行。
- Artifact Directory 是 Run 的持久化事实来源。
- ThreadStore 主要是进程内运行视图；服务重启后的恢复依赖磁盘 Artifact 和 Run State。

## 5. 主要接口契约

### 5.1 配置与宿主

| Method | Path | 作用 |
| --- | --- | --- |
| GET | `/config/defaults` | 返回前端默认配置。 |
| GET | `/config/runtime-overrides` | 读取持久化覆盖配置，不回传 API Key 明文。 |
| POST | `/config/runtime-overrides` | 合并并保存覆盖配置。 |
| DELETE | `/config/runtime-overrides` | 清空覆盖配置。 |
| GET | `/frontend/host-info` | 返回 desktop/web host mode 和 URL。 |

### 5.2 执行与监控

| Method | Path | 作用 |
| --- | --- | --- |
| POST | `/uploads` | 保存输入图片。 |
| POST | `/threads` | 创建 Thread。 |
| GET | `/threads/{thread_id}` | 读取 Thread 原始状态。 |
| POST | `/invoke` | 创建新的后台转换 Run。 |
| GET | `/threads/{thread_id}/snapshot` | 获取适合 UI 的运行快照。 |
| GET | `/threads/{thread_id}/artifacts` | 获取 Artifact 视图。 |
| GET | `/threads/{thread_id}/artifacts/file` | 预览或下载 Artifact 文件。 |

### 5.3 恢复与后处理

| Method | Path | 作用 |
| --- | --- | --- |
| GET | `/runs/resume-plan` | 根据当前 Thread 拥有的 Run ID 计算可恢复阶段。 |
| POST | `/runs/resume` | 校验 Run 所有权后在原 Thread 中继续转换。 |
| POST | `/threads/{thread_id}/manual-adjust` | 创建人工调整版本。 |
| POST | `/threads/{thread_id}/debug-review` | 独立执行审查工具。 |
| PATCH | `/threads/{thread_id}/runs/{run_id}` | 重命名项目。 |
| DELETE | `/threads/{thread_id}/runs/{run_id}` | 删除非活动 Run。 |

## 6. 前端维护边界

### 现行维护对象

- `desktop.html`；
- `desktop-app.js`；
- `static/js/api-client.js`；
- `static/js/state.js`；
- `static/js/renderers/*`；
- `static/js/components/*`。

### 遗留对象

- 根路径 `/` 返回的 `index.html`；
- 与旧 Web 页面强绑定的 `app.js` 和样式。

浏览器 Web 页面缺乏持续维护，可能在配置字段、人工调整、历史项目或 Workflow Trace 等功能上落后。修复桌面功能时，不应默认要求旧 Web 页面同步具备完全一致能力，除非项目重新决定恢复该入口。
