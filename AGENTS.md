# llm-d-bench Agent Instructions

Engineering guidelines for llm-d-bench, a Tekton-based LLM inference benchmarking framework.

---

## Core Architecture

### Three-Tier Design

```
PipelineRuns (instances) → Pipelines (orchestration) → Tasks (atomic operations)
```

- **Tasks**: Atomic operations with sensible defaults
- **Pipelines**: Orchestrate task dependencies with `runAfter` and `when` clauses
- **PipelineRuns**: Concrete instances, minimal parameters only

### Deployment Mode Isolation

Three modes with mode-specific deploy/cleanup tasks:

- **llm-d**: Helmfile-based GitOps (`tasks/deployment/llm-d/`)
- **RHOAI**: KServe distributed inference (`tasks/deployment/rhoai/`)
- **RHAIIS**: Pod-based vLLM (`tasks/deployment/rhaiis/`)

**Rule**: Share common tasks (`tasks/deployment/common/`), isolate mode-specific logic.

### Benchmark Tool Isolation

- **GuideLLM**: Load testing (`tasks/benchmark/guidellm/`)
- **MLPerf**: Industry benchmarks (`tasks/benchmark/mlperf/`)

**Rule**: Prefix tool parameters (`GUIDELLM_*`, `MLPERF_*`).

### Directory Structure

```
config/
  cluster/          # Infrastructure (RBAC, secrets, PVCs)
  profiles/         # Workload configs (vLLM, deployment, benchmark)
tasks/
  common/           # Cross-cutting utilities
  deployment/
    common/         # Shared deployment tasks
    {mode}/         # Mode-specific deploy/cleanup
  benchmark/{tool}/ # Tool-specific benchmarks
pipelines/deployment/{mode}/  # End-to-end pipelines
pipelineruns/{mode}/         # Mode-specific examples
```

---

## Configuration Management

### Profile-Based Configuration

Use ConfigMaps as single source of truth:

```yaml
# config/profiles/vllm/vllm-default.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-default
  namespace: llm-d-bench
  annotations:
    description: "Standard vLLM config"
  labels:
    config-type: vllm
data:
  VLLM_ARGS: |
    --max-model-len=8192
    --gpu-memory-utilization=0.92
```

**Profiles**: vLLM configs, deployment platforms, benchmark workloads, EPP scheduler configs.

### Configuration Precedence

```
Task Defaults → ConfigMap Profiles → PipelineRun Params
(lowest)        (middle)             (highest)
```

**Example**:
1. Task default: `REPLICAS="1"`
2. ConfigMap: `REPLICAS="2"` (overrides task)
3. PipelineRun: `REPLICAS="3"` (overrides all)

### Pipeline Configuration Flow

**All pipelines start with merge-configs task** (Stage 0):

```yaml
tasks:
  # Stage 0: Merge Configuration Profiles
  - name: merge-configs
    taskRef:
      name: merge-configs
    params:
      - name: VLLM_CONFIG
        value: $(params.VLLM_CONFIG)
      - name: DEPLOYMENT_CONFIG
        value: $(params.DEPLOYMENT_CONFIG)
      - name: BENCHMARK_CONFIG
        value: $(params.BENCHMARK_CONFIG)
      - name: EPP_CONFIG
        value: $(params.EPP_CONFIG)

  # Stage 1: Download Model
  - name: download-model
    runAfter: [merge-configs]
```

**Purpose**:
- Validates all referenced ConfigMaps exist
- Provides early failure if profiles are misconfigured
- Tasks read ConfigMaps directly using profile names

### Minimal PipelineRuns

**Production files** should only contain:
- Required parameters (MODEL_NAME, RELEASE_NAME, TP)
- Experiment-specific overrides (REPLICAS, BENCHMARK_ENV_VARS)
- Profile references (VLLM_CONFIG, DEPLOYMENT_CONFIG, BENCHMARK_CONFIG)

```yaml
params:
  - name: MODEL_NAME
    value: "meta-llama/Llama-3.1-8B"
  - name: VLLM_CONFIG
    value: "vllm-default"
  - name: DEPLOYMENT_CONFIG
    value: "deployment-llm-d-inference-scheduling"
  - name: BENCHMARK_CONFIG
    value: "concurrent-1k-1k"
  - name: RELEASE_NAME
    value: "llama-31-8b"
  - name: TP
    value: "1"
  # No defaults, no stage control, no Kueue labels
```

**Example files** (`*-example.yaml`) should:
- Document ALL possible parameters
- Include defaults as comments
- Show Kueue labels as examples
- Include stage control params

**Never** include in production files:
- Parameters with defaults (MODEL_REVISION, NAMESPACE, TARGET, etc.)
- Stage control (SKIP_*) - defaults to all false
- Kueue labels - only in examples
- Unnecessary comments

---

## Task Design Rules

### Provide Sensible Defaults

```yaml
params:
  - name: GUIDELLM_RATE
    description: Comma-separated rates to test
    type: string
    default: "1,50,100"  # Always provide defaults for optional params
```

**Only omit defaults for truly required params**: MODEL_NAME, TARGET, NAMESPACE, RELEASE_NAME.

### Secrets Always Optional

```yaml
env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: huggingface-token
        key: HF_TOKEN
        optional: true  # REQUIRED - prevents task failure
```

### Idempotent Tasks

```bash
if [ "$(params.SKIP_IF_EXISTS)" = "true" ] && [ -d "$TARGET_PATH" ]; then
  echo "✓ Already exists - skipping"
  exit 0
fi
```

### Sanitize Model Names

```bash
# File paths: replace / with -
MODEL_DIR=$(echo "$(params.MODEL_NAME)" | sed 's/\//-/g')

# K8s resources: lowercase and replace /
K8S_NAME=$(echo "$(params.MODEL_NAME)" | sed 's/\//-/g' | tr '[:upper:]' '[:lower:]')
```

### Avoid GPU Nodes for Non-Inference Tasks

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: nvidia.com/gpu
              operator: DoesNotExist
```

### Use Array Parameters

```yaml
params:
  - name: MLFLOW_TAGS
    type: array
    default: []

# Expand in task invocation
params:
  - name: MLFLOW_TAGS
    value: $(params.MLFLOW_TAGS[*])
```

---

## Pipeline Design Rules

### Sequential Execution

```yaml
- name: deploy-model
  runAfter: [download-model]
  taskRef:
    name: deploy-llm-d-helmfile
```

### Conditional Execution

```yaml
- name: run-benchmark
  when:
    - input: "$(params.SKIP_BENCHMARK)"
      operator: in
      values: ["false"]
  taskRef:
    name: run-guidellm-benchmark
```

### Parameter Propagation

Always propagate through all three levels:

```yaml
# Pipeline: accept
params:
  - name: GUIDELLM_RATE
    default: "1,50,100"

# Pipeline: pass to task
tasks:
  - name: benchmark
    params:
      - name: GUIDELLM_RATE
        value: $(params.GUIDELLM_RATE)

# PipelineRun: optionally override
params:
  - name: GUIDELLM_RATE
    value: "1"
```

### Workspace Binding

```yaml
# Pipeline
workspaces:
  - name: models-storage

# Task binding
tasks:
  - name: download
    workspaces:
      - name: models-storage
        workspace: models-storage
```

---

## PipelineRun Design Rules

### Use generateName

```yaml
metadata:
  generateName: experiment-name-  # Allows multiple runs
```

### Service Account Binding

```yaml
taskRunTemplate:
  serviceAccountName: deploy-model-sa
```

### Workspace Types

```yaml
workspaces:
  - name: models-storage
    persistentVolumeClaim:
      claimName: models-storage  # Persistent

  - name: results
    emptyDir: {}  # Ephemeral
```

### TTL Cleanup

```yaml
spec:
  ttlSecondsAfterFinished: 3600  # Delete after 1 hour
```

---

## Naming Conventions

| Element | Convention | Examples |
|---------|-----------|----------|
| Files | kebab-case | run-benchmark.yaml |
| Parameters | SCREAMING_SNAKE_CASE | MODEL_NAME, GUIDELLM_RATE |
| Resources | kebab-case | run-guidellm-benchmark |
| Tool Prefixes | {TOOL}_ | GUIDELLM_*, MLPERF_* |

---

## Required Practices

### ✅ Always Do

- Provide defaults for optional parameters
- Use `optional: true` for all secrets
- Sanitize model names before using in paths/K8s resources
- Propagate parameters through all three tiers
- Use tool prefixes (GUIDELLM_*, MLPERF_*)
- Document parameters with descriptions
- Use profile ConfigMaps for reusable configs
- Keep production PipelineRuns minimal
- Avoid GPU nodes for non-inference tasks

### ❌ Never Do

- Hardcode secrets, URLs, or tokens
- Duplicate logic across modes (use common tasks)
- Create bash scripts instead of Tekton tasks
- Mix deployment logic in common tasks
- Skip parameter defaults for optional params
- Forget model name sanitization
- Break naming conventions
- Include verbose docs in README (use docs/)
- Include default params in production PipelineRuns
- Add Kueue labels or stage control to production files

---

## Bash Script Standards

```bash
#!/bin/bash
set -e  # Fail on errors

# Validate inputs
if [ -z "$(params.REQUIRED_PARAM)" ]; then
  echo "ERROR: REQUIRED_PARAM is empty"
  exit 1
fi

# Echo progress
echo "Starting operation..."
echo "Using model: $(params.MODEL_NAME)"

# Use Tekton syntax
MODEL_NAME="$(params.MODEL_NAME)"
WORKSPACE_PATH="$(workspaces.storage.path)"

# Array iteration
for tag in $(params.MLFLOW_TAGS[*]); do
  echo "Tag: $tag"
done

echo "✓ Complete"
```

---

## Extension Patterns

### Adding a Benchmark Tool

1. Create image: `build/{tool}/`
2. Create task: `tasks/benchmark/{tool}/run-benchmark.yaml`
3. Use prefixed parameters: `{TOOL}_RATE`, `{TOOL}_DATA`
4. Create pipeline: `pipelines/benchmark/{tool}/`
5. Create examples: `pipelineruns/benchmark/{tool}/`
6. Support MLflow with `MLFLOW_ENABLED` parameter
7. Run `./scripts/install.sh` (auto-discovers resources)

### Adding a Deployment Mode

1. Create deploy task: `tasks/deployment/{mode}/deploy-model.yaml`
2. Create cleanup task: `tasks/deployment/{mode}/cleanup-deployment.yaml`
3. Create pipeline: `pipelines/deployment/{mode}/e2e-benchmark.yaml`
4. Reuse common tasks (download-model, wait-for-endpoint)
5. Create examples: `pipelineruns/{mode}/`
6. Update RBAC if needed: `config/cluster/rbac/`

### Adding a Profile

1. Create ConfigMap: `config/profiles/{category}/{name}.yaml`
2. Add to kustomization: `config/profiles/{category}/kustomization.yaml`
3. Document in `docs/PROFILES.md`
4. Apply: `oc apply -k config/profiles/`

---

## Quick Reference

### Common Parameters

```yaml
MODEL_NAME       # HuggingFace model ID (required)
TARGET           # Inference endpoint (required)
RELEASE_NAME     # Deployment identifier (required)
TP               # Tensor parallelism (default: "1")
REPLICAS         # Worker replicas (default: "1")
MLFLOW_ENABLED   # Enable tracking (default: "false")
```

### Profile Parameters

```yaml
VLLM_CONFIG         # vllm-default, vllm-fp8-cache, vllm-experts-parallel
DEPLOYMENT_CONFIG   # deployment-llm-d-inference-scheduling, deployment-rhoai-kserve, deployment-rhaiis-vllm-pod
BENCHMARK_CONFIG    # concurrent-1k-1k, concurrent-8k-1k
EPP_CONFIG          # scheduler-precise-prefix-cache, scheduler-cache-aware, scheduler-pd-disaggregation (llm-d only)
```

### GuideLLM Parameters

```yaml
GUIDELLM_RATE           # default: "1,50,100"
GUIDELLM_DATA           # default: "prompt_tokens=1000,output_tokens=1000"
GUIDELLM_MAX_SECONDS    # default: "600"
GUIDELLM_BACKEND_TYPE   # default: "openai_http"
```

### Stage Control

```yaml
SKIP_DOWNLOAD    # default: "false"
SKIP_DEPLOY      # default: "false"
SKIP_BENCHMARK   # default: "false"
SKIP_CLEANUP     # default: "false"
```

---

## Troubleshooting

### Parameters not reaching tasks
```bash
oc get pipelinerun <name> -o yaml | grep PARAM_NAME
# Check all three levels: PipelineRun → Pipeline → Task
```

### Array parameters not expanding
```yaml
# Use [*] syntax
params:
  - name: TAGS
    value: $(params.TAGS[*])
```

### Secrets missing
```yaml
# Always use optional: true
optional: true
```

### Tasks not found
```bash
oc get task | grep <task-name>
oc apply -f tasks/.../task.yaml
```

---

## Critical Files for Reference

- Task pattern: `tasks/benchmark/guidellm/run-benchmark.yaml`
- Pipeline pattern: `pipelines/deployment/llm-d/e2e-benchmark.yaml`
- PipelineRun pattern: `pipelineruns/llm-d/deepseek-ai-deepseek-r1-0528-1k-1k.yaml`
- Example pattern: `pipelineruns/llm-d/qwen-qwen3-06b-example.yaml`
- Profile pattern: `config/profiles/vllm/vllm-default.yaml`
