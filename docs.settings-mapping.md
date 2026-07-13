# Settings Name And Value Mapping

This document records the frontend display mapping for desktop settings. Backend keys and submitted values remain unchanged. A `-` mapping means the frontend intentionally displays the backend name or value unchanged.

## Field Name Mapping

| Backend/frontend id | Current backend meaning | Frontend label mapping |
|---|---|---|
| `api-key` | API Key | - |
| `base-url` | Base URL | - |
| `api-provider` | API Provider | API Protocol |
| `api-format` | API Format | Request Format |
| `agent-model` | Coordinator Model | - |
| `subagent-model` | Worker Model | - |
| `settings-workflow-mode` | Workflow Mode | Refinement Depth |
| `workflow-mode` | Workflow Mode | Refinement Depth |
| `settings-region-processing-mode` | Region Mode | Processing Schedule |
| `region-processing-mode` | Region Mode | Processing Schedule |
| `settings-region-concurrency` | Region Concurrency | - |
| `region-concurrency` | Region Concurrency | - |
| `max-budget` | Max Budget | - |
| `max-repair-retry` | Max Repair Retry | - |
| `max-retries` | API Max Retries | - |
| `use-previous-response-id` | Reuse Response State | - |
| `recognition-bbox-refine-mode` | BBox Refine Mode | Detection Box Refinement |
| `sam-enabled` | Enable SAM | - |
| `sam-provider-mode` | SAM Provider | Segmentation Service |
| `sam-remote-url` | SAM Remote URL | - |
| `sam-fallback-to-llm` | SAM Fallback To LLM | - |
| `bbox-issue-concurrency` | BBox Issue Concurrency | - |
| `bbox-issue-stagnation-rounds` | Issue Stagnation Rounds | - |
| `bbox-global-stagnation-rounds` | Global Stagnation Rounds | - |
| `agent-name` | Agent Name | - |
| `supervisor-memory-enabled` | Supervisor Memory Use | - |
| `supervisor-memory-persist-enabled` | Memory Artifact Persist | - |
| `strategy-enabled` | Strategy Hints | - |

## Value Mapping

### `api-format` / `api_format`

| Backend value | Frontend value mapping |
|---|---|
| `openai_chat_completions` | Chat Completions API |
| `openai_responses` | Responses API |

### `settings-workflow-mode`, `workflow-mode` / `workflow_mode`

| Backend value | Frontend value mapping |
|---|---|
| `initial_only` | Quick Draft - basic conversion only |
| `region` | Region Refinement - improve each detected area |
| `region_object` | Full Detail - refine regions and individual objects |

### `settings-region-processing-mode`, `region-processing-mode` / `region_processing_mode`

| Backend value | Frontend value mapping |
|---|---|
| `serial` | One at a time - slower, steadier |
| `parallel` | Faster parallel processing |

### `recognition-bbox-refine-mode` / `recognition_bbox_refine_mode`

| Backend value | Frontend value mapping |
|---|---|
| `llm` | AI vision review |
| `sam` | Segmentation model |
| `hybrid` | Segmentation + AI review |

### `sam-provider-mode` / `sam_provider_mode`

| Backend value | Frontend value mapping |
|---|---|
| `local` | Run on this computer |
| `remote` | Use remote service |

### Boolean Select Values

These values are currently unchanged.

| Backend value | Frontend value mapping |
|---|---|
| `true` | - |
| `false` | - |

Applies to:

- `use-previous-response-id`
- `sam-enabled`
- `sam-fallback-to-llm`
- `supervisor-memory-enabled`
- `supervisor-memory-persist-enabled`
- `strategy-enabled`

### Numeric/Text Inputs

These inputs currently use unchanged raw values.

| Field id | Value mapping |
|---|---|
| `api-key` | - |
| `base-url` | - |
| `api-provider` | - |
| `agent-model` | - |
| `subagent-model` | - |
| `settings-region-concurrency` | - |
| `region-concurrency` | - |
| `max-budget` | - |
| `max-repair-retry` | - |
| `max-retries` | - |
| `sam-remote-url` | - |
| `bbox-issue-concurrency` | - |
| `bbox-issue-stagnation-rounds` | - |
| `bbox-global-stagnation-rounds` | - |
| `agent-name` | - |

## Implementation Notes

- The canonical frontend mapping lives in `src/deepagents_template/static/js/settings-labels.js`.
- The mapping layer defaults to unchanged labels and values when a field or value is not listed.
- Form submission still sends backend enum values such as `region_object`; only the visible option text, field labels, effective-value chips, and summary chips use mapped labels.
