# Raster-to-SVG Agent Demo

这是一个将位图图片转换为可编辑 SVG 的实验项目。项目会读取一张本地 raster 图片，调用多模态模型完成版面拆分、分区生成、检查与修复，并把输入、过程文件和最终结果全部保存到一次 run 的产物目录中。

如果你是第一次接手这个项目，建议先看下面的“5 分钟跑通一次 SVG 转换”。

## 5 分钟跑通一次 SVG 转换

### 1. 准备环境

推荐使用 Conda：

```powershell
conda env create -f environment.yml
conda activate agent-demo
```

项目依赖安装：

```powershell
python -m pip install -e .
```

如果你还需要运行测试或 lint，再安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

### 2. 复制并填写 `.env`

先复制模板：

```powershell
Copy-Item .env.example .env
```

至少需要确认这 4 个参数：

```env
API_KEY=your-real-api-key
BASE_URL=https://api.poe.com/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_responses
```

对新手来说，最常见的起步配置就是上面这组。  
如果你的模型服务兼容 OpenAI 风格接口，通常只需要把 `API_KEY` 和 `BASE_URL` 改成你自己的值。

### 3. 准备输入图片

假设要转换的图片是：

```text
test\CNNhard.png
```

也可以换成你自己的绝对路径，例如：

```text
D:\path\to\your\image.png
```

### 4. 执行转换

直接运行：

```powershell
python -m deepagents_template.main "请将这张图片转换为可编辑 SVG，尽量保留原始布局、文字和连线语义。" --image-path "test\CNNhard.png"
```

运行时终端会持续输出阶段进度，例如：

- 当前处理到哪个阶段
- 当前是串行还是并行处理 region
- 使用了哪个模型和 API 格式
- 本次产物写到了哪个目录

### 5. 去哪里看结果

每次运行都会在 `artifacts/runs/` 下创建一个新目录，命名形式大致是：

```text
artifacts/runs/20260612-123456-CNNhard/
```

最重要的结果文件通常在这里：

- `output/final.svg`
  最终 SVG
- `output/final_review.json`
  最终全局检查结果
- `output/report.md`
  本次转换的 Markdown 报告
- `output/report.json`
  同一份报告的结构化 JSON
- `input/request.json`
  本次运行真正使用的请求参数
- `input/input_metadata.json`
  输入图片的尺寸等元数据
- `intermediate/layout_detection.json`
  版面拆分结果
- `intermediate/regions.json`
  归一化后的 region 列表
- `intermediate/region_results.json`
  各 region 的汇总结果
- `run_state.json`
  用于恢复运行状态的快照

如果你想快速判断“这次是否成功”，优先看：

1. `output/final.svg`
2. `output/final_review.json`
3. `output/report.md`

## 新手最需要知道的参数怎么选

这个项目的参数分两类：

- `.env` 里的参数：给整个项目设置默认值
- 命令行或 HTTP 请求里的参数：只影响本次运行

原则很简单：

1. 经常不变的，写进 `.env`
2. 这次任务临时想改的，放到命令行或请求体里

### 一组推荐的入门默认值

```env
API_KEY=your-real-api-key
BASE_URL=https://api.poe.com/v1
API_PROVIDER=openai_compatible
API_FORMAT=openai_responses
MAX_RETRIES=2

AGENT_MODEL=gpt-5.4-medium
SUBAGENT_MODEL=gpt-5.4-medium

RUN_ARTIFACTS_DIR=artifacts/runs
MAX_RETRY=5
MAX_BUDGET=80
REGION_PROCESSING_MODE=parallel
REGION_CONCURRENCY=8
WORKFLOW_MODE=region_object
SUPERVISOR_MEMORY_ENABLED=false
SUPERVISOR_MEMORY_PERSIST_ENABLED=true
STRATEGY_ENABLED=true
```

### 常用参数怎么理解

| 参数 | 你什么时候需要关心它 | 推荐起步值 | 说明 |
|---|---|---|---|
| `API_KEY` | 任何时候都必须配置 | 你的真实 key | 模型服务鉴权 |
| `BASE_URL` | 任何时候都必须确认 | 你的服务地址 | OpenAI-compatible 服务入口 |
| `API_PROVIDER` | 基本不用改 | `openai_compatible` | 当前实现只支持这一种 provider |
| `API_FORMAT` | 服务兼容性不确定时要关心 | `openai_responses` | 不兼容时再切到 `openai_chat_completions` |
| `MAX_RETRIES` | API 偶发失败较多时 | `2` | 单次底层 API 调用失败后的重试次数 |
| `MAX_RETRY` | 图片很复杂、修复轮数不够时 | `5` | 单个 region/object 的修复轮数上限 |
| `MAX_BUDGET` | 想控制总成本时 | `80` | 整次 pipeline 允许的模型调用预算 |
| `REGION_PROCESSING_MODE` | 机器性能一般或调试时 | `parallel` | `serial` 更稳，`parallel` 更快 |
| `REGION_CONCURRENCY` | `parallel` 模式下 | `8` | 并发 worker 上限，范围 1 到 16 |
| `WORKFLOW_MODE` | 想控制流程深度时 | `region_object` | 完整流程；其余模式见下文 |
| `SUPERVISOR_MEMORY_ENABLED` | 调试高级行为时 | `false` | 一般保持默认即可 |
| `STRATEGY_ENABLED` | 调试 policy 输出时 | `true` | 一般保持默认即可 |

### 命令行里最常用的可调参数

实际 CLI 支持这些主要参数：

```text
--image-path
--api-provider
--api-format
--region-processing-mode
--region-concurrency
--workflow-mode
--supervisor-memory-enabled
--strategy-enabled
```

对应源码入口见 [main.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/main.py:1)。

### 三种最常见的参数组合

#### 1. 先求稳定跑通

适合第一次使用，或者图片较复杂、你先不追求速度：

```powershell
python -m deepagents_template.main "请将这张图片转换为可编辑 SVG，保留布局与文本。" `
  --image-path "test\CNNhard.png" `
  --region-processing-mode serial `
  --workflow-mode region_object
```

特点：

- 速度慢一些
- 更容易观察每个 region 的问题
- 适合排查失败原因

#### 2. 默认推荐方案

适合大多数日常转换：

```powershell
python -m deepagents_template.main "请将这张图片转换为可编辑 SVG，保留布局、文字和关系。" `
  --image-path "test\CNNhard.png" `
  --region-processing-mode parallel `
  --region-concurrency 8 `
  --workflow-mode region_object
```

特点：

- 速度和质量比较均衡
- 对大多数图都适合作为默认方案

#### 3. 先快速出一个初稿

适合你只想先拿到一个可看的初版：

```powershell
python -m deepagents_template.main "请先快速生成一个可编辑 SVG 初稿。" `
  --image-path "test\CNNhard.png" `
  --workflow-mode initial_only
```

特点：

- 最快
- 只做到初始合并 SVG
- 适合先看整体结构，不适合直接当最终稿

## `WORKFLOW_MODE` 应该怎么选

`WORKFLOW_MODE` 有 3 个值：

- `initial_only`
  只生成初始合并 SVG，然后停止
- `region`
  做到 region 级修复，不继续深入 object 级修复
- `region_object`
  完整流程，包含更细粒度的 object 级修复

建议：

- 只想看看能不能跑通：`initial_only`
- 想平衡速度和质量：`region`
- 想尽量拿到最完整结果：`region_object`

当前默认值是 `region_object`，来源见 [config.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/config.py:1)。

## `REGION_PROCESSING_MODE` 和 `REGION_CONCURRENCY` 应该怎么选

### `REGION_PROCESSING_MODE`

- `serial`
  逐个 region 处理，最容易调试
- `parallel`
  多个 region 并发处理，通常更快

### `REGION_CONCURRENCY`

只有 `parallel` 模式下才有意义。  
代码会把它限制在 `1` 到 `16` 之间。

经验建议：

- 小图、简单图：`4`
- 常规使用：`8`
- 机器和服务都比较充足：`12` 到 `16`
- 遇到不稳定、超时、资源竞争：降低到 `2` 或 `4`

对应解析逻辑见 [config.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/config.py:1)。

## 命令行使用说明

### 最基础命令

```powershell
python -m deepagents_template.main "<你的转换要求>" --image-path "<图片路径>"
```

示例：

```powershell
python -m deepagents_template.main "请将这张流程图转换为可编辑 SVG，保留中文文本和箭头连接关系。" --image-path "test\Flow.png"
```

### 如果不传某些参数，会发生什么

- 不传 `message`
  使用 `.env` 中的 `DEFAULT_USER_INPUT`
- 不传 `--api-provider`
  使用 `.env` 中的 `API_PROVIDER`
- 不传 `--api-format`
  使用 `.env` 中的 `API_FORMAT`
- 不传 `--region-processing-mode`
  使用 `.env` 中的 `REGION_PROCESSING_MODE`
- 不传 `--region-concurrency`
  使用 `.env` 中的 `REGION_CONCURRENCY`
- 不传 `--workflow-mode`
  使用 `.env` 中的 `WORKFLOW_MODE`

这套优先级由 [config.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/config.py:1) 统一解析。

## API 服务与前端

这个项目也提供 FastAPI 服务和内置前端页面。

### 启动服务

方式一，直接用 uvicorn：

```powershell
python -m uvicorn deepagents_template.api:app --reload
```

方式二，使用项目脚本：

```powershell
.\start-service.ps1
```

或：

```powershell
.\start-service.bat
```

`start-service.ps1` 会读取 `.env` 中的 `APP_HOST` 和 `APP_PORT`，必要时先执行 `pip install -e .`。

### 打开页面

默认地址：

```text
http://127.0.0.1:8120/
```

### 常用接口

- `GET /health`
  健康检查
- `GET /config/defaults`
  查看前端默认配置
- `POST /uploads`
  上传图片
- `POST /invoke`
  发起一次转换
- `GET /threads/{thread_id}/artifacts`
  查看某次线程对应的产物
- `POST /runs/resume`
  从已有产物目录恢复运行

接口实现见 [api.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/api.py:1)。

### `POST /invoke` 请求示例

```json
{
  "thread_id": "optional-thread-id",
  "message": "请将这张 dashboard 截图转换为可编辑 SVG，并尽量保留图表语义。",
  "image_path": "D:\\path\\to\\input.png",
  "api_provider": "openai_compatible",
  "api_format": "openai_responses",
  "region_processing_mode": "parallel",
  "region_concurrency": 8,
  "workflow_mode": "region_object"
}
```

## 转换流程到底做了什么

当前 CLI 与 API 都要求传入 `image_path`，实际执行的是 [conversion.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/conversion.py:1) 中的 `RasterToSvgPipeline`。主流程如下：

1. 创建本次 run 的产物目录
2. 复制输入图片到 `input/`
3. 提取输入图片元数据
4. 生成 requirement summary 和 acceptance checklist
5. 调用模型做 layout detection
6. 归一化和修正 bbox
7. 按 region 裁图
8. 为每个 region 生成 SVG
9. 对 region 结果执行 review 与 repair
10. 合并所有 region，得到 `output/final.svg`
11. 对最终 SVG 做 final review
12. 写出报告、日志和可恢复状态

## 重要产物目录说明

一次典型运行下，目录大致如下：

```text
artifacts/runs/<timestamp>-<project-name>/
├─ input/
│  ├─ request.json
│  ├─ input_metadata.json
│  └─ <copied-image>
├─ intermediate/
│  ├─ layout_detection.json
│  ├─ regions.json
│  ├─ template.svg
│  ├─ region_results.json
│  └─ regions/
├─ output/
│  ├─ final.svg
│  ├─ final_review.json
│  ├─ report.md
│  └─ report.json
├─ logs/
│  ├─ overview.json
│  ├─ timeline.json
│  └─ files.json
├─ metadata.json
└─ run_state.json
```

其中：

- `input/`
  保存输入图片和本次请求参数
- `intermediate/`
  保存 layout、region 拆分和中间 SVG 片段
- `output/`
  保存最终 SVG 和最终报告
- `logs/`
  保存过程日志和产物写入记录
- `run_state.json`
  保存恢复执行所需的状态

## 配置参数总表

这些参数来自 `.env`，用于设置默认行为：

| 参数名 | 默认值 | 说明 |
|---|---|---|
| `API_KEY` | 空字符串 | 模型服务密钥，兼容旧别名 `OPENAI_API_KEY` / `POE_API_KEY` |
| `BASE_URL` | `None` | 模型服务地址，兼容旧别名 `OPENAI_BASE_URL` |
| `API_PROVIDER` | `openai_compatible` | 当前唯一支持的 provider |
| `API_FORMAT` | `openai_responses` | 底层协议，可切换到 `openai_chat_completions` |
| `MAX_RETRIES` | `2` | 底层 API 请求失败时的重试次数 |
| `LANGSMITH_API_KEY` | 空 | 可选 tracing 配置 |
| `LANGSMITH_TRACING` | `false` | 是否启用 LangSmith tracing |
| `LANGSMITH_PROJECT` | `raster-to-svg-agent-demo` | LangSmith 项目名 |
| `AGENT_MODEL` | `gpt-5.4-medium` | coordinator / final review 模型 |
| `SUBAGENT_MODEL` | `gpt-5.4-medium` | region worker 模型 |
| `AGENT_NAME` | `raster-svg-coordinator` | agent 名称 |
| `USE_PREVIOUS_RESPONSE_ID` | `false` | 是否复用 Responses API 的状态 |
| `APP_HOST` | `127.0.0.1` | FastAPI 监听地址 |
| `APP_PORT` | `8120` | FastAPI 监听端口 |
| `REQUIRE_APPROVAL_FOR_TASK_CREATION` | `false` | 预留审批开关 |
| `RUN_ARTIFACTS_DIR` | `artifacts/runs` | 产物根目录 |
| `DEFAULT_USER_INPUT` | `Convert this image into SVG format` | CLI 未传 message 时使用 |
| `MAX_RETRY` | `5` | 单个修复任务的最大重试轮数 |
| `MAX_BUDGET` | `80` | 整次 run 的模型调用预算 |
| `REGION_PROCESSING_MODE` | `parallel` | 默认 region 处理模式 |
| `REGION_CONCURRENCY` | `8` | 默认并发数 |
| `WORKFLOW_MODE` | `region_object` | 默认工作流深度 |
| `SUPERVISOR_MEMORY_ENABLED` | `false` | 是否启用 supervisor memory |
| `SUPERVISOR_MEMORY_PERSIST_ENABLED` | `true` | 是否持久化 supervisor memory |
| `STRATEGY_ENABLED` | `true` | 是否启用策略提示输出 |

## 请求参数总表

这些参数来自 CLI 或 HTTP 请求体，代表“本次运行”的设置：

| 参数名 | 是否常用 | 说明 |
|---|---|---|
| `message` | 必填 | 本次转换要求 |
| `image_path` | 必填 | 输入图片本地路径 |
| `api_provider` | 偶尔 | 覆盖 `.env` 中的 provider |
| `api_key` | 偶尔 | 覆盖 `.env` 中的 key |
| `base_url` | 偶尔 | 覆盖 `.env` 中的 base URL |
| `api_format` | 常用 | 本次运行改用 `responses` 或 `chat.completions` |
| `max_retries` | 偶尔 | 覆盖底层 API 重试次数 |
| `region_processing_mode` | 常用 | 本次运行用 `serial` 或 `parallel` |
| `region_concurrency` | 常用 | 本次运行的并发数 |
| `workflow_mode` | 常用 | 本次运行的流程深度 |
| `project_name` | 偶尔 | 自定义产物目录名 |
| `agent_model` | 偶尔 | 覆盖 coordinator 模型 |
| `subagent_model` | 偶尔 | 覆盖 worker 模型 |
| `agent_name` | 很少 | 覆盖 agent 名称 |
| `use_previous_response_id` | 很少 | 覆盖 Responses API 状态复用策略 |
| `max_retry` | 偶尔 | 覆盖修复轮数 |
| `max_budget` | 常用 | 覆盖总预算 |
| `supervisor_memory_enabled` | 很少 | 覆盖 supervisor memory 开关 |
| `supervisor_memory_persist_enabled` | 很少 | 覆盖 memory 持久化开关 |
| `strategy_enabled` | 很少 | 覆盖策略提示开关 |

定义见 [schemas.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/schemas.py:1017)。

## 快速排错

### 1. 命令能启动，但模型调用失败

优先检查：

- `API_KEY` 是否真实有效
- `BASE_URL` 是否正确
- `API_FORMAT` 是否和你的服务兼容
- 网络是否能访问模型服务

如果你不确定服务是否支持 `responses`，先尝试改成：

```env
API_FORMAT=openai_chat_completions
```

### 2. 运行很慢或经常超时

可以先这样降复杂度：

- 把 `REGION_PROCESSING_MODE` 改成 `serial`
- 把 `REGION_CONCURRENCY` 降到 `2` 或 `4`
- 把 `WORKFLOW_MODE` 改成 `region` 或 `initial_only`

### 3. 跑到中途停住，怀疑预算不够

检查：

- `.env` 里的 `MAX_BUDGET`
- 产物目录里的 `run_state.json`

如果 run 因预算暂停，可以通过 API 的 `POST /runs/resume` 恢复。

### 4. 不知道这次到底用了哪些参数

直接查看：

```text
artifacts/runs/<run>/input/request.json
```

这份文件最适合用来复盘“本次实际跑的是什么配置”。

## 相关代码入口

- CLI 入口：[main.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/main.py:1)
- 配置解析：[config.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/config.py:1)
- 转换主流程：[conversion.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/conversion.py:1)
- API 服务：[api.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/api.py:1)
- 产物管理：[artifacts.py](/D:/Daily/Schedule/LH/EditableTransf/Demo/src/deepagents_template/artifacts.py:1)
- 部署脚本说明：[quick-start/README.md](/D:/Daily/Schedule/LH/EditableTransf/Demo/quick-start/README.md:1)
