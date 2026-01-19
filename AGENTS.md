# llm-d-bench Agent Instructions

When working on this codebase, follow these architectural patterns and coding standards. This repository implements a Tekton-based CI/CD framework for LLM inference benchmarking.

---

## Architecture Requirements

### Follow the Three-Tier Design

Always structure your changes according to this hierarchy:

```
PipelineRuns (Concrete Instances)
    ↓ (parameters)
Pipelines (Orchestration)
    ↓ (task invocation + dependencies)
Tasks (Atomic Operations)
    ↓ (container execution)
Results
```

- **Tasks**: Create atomic operations (download, deploy, benchmark, cleanup)
- **Pipelines**: Orchestrate task dependencies and conditional execution
- **PipelineRuns**: Define concrete execution instances with specific parameters

Ensure parameters flow correctly: PipelineRun → Pipeline → Task. Use PVCs or emptyDir for workspace storage.

### Respect Deployment Mode Isolation

Three deployment modes exist, each with mode-specific deploy/cleanup tasks:

- **RHOAI**: KServe LLMInferenceService (distributed inference)
- **llm-d**: Helmfile-based GitOps deployment
- **RHAIIS**: Pod-based vLLM deployment

**Rule**: Place mode-specific tasks in `tasks/deployment/{mode}/`. Share common tasks (download-model, wait-for-endpoint) across all modes in `tasks/deployment/common/`.

### Respect Benchmark Tool Isolation

Two benchmark tools are supported:

- **GuideLLM**: Load testing, detailed metrics (default)
- **MLPerf**: Standardized industry benchmarks

**Rule**: Place tool-specific tasks in `tasks/benchmark/{tool}/`. Prefix all tool-specific parameters with the tool name (GUIDELLM_*, MLPERF_*) to prevent conflicts.

### Follow Directory Structure

Organize code according to this structure:

```
tasks/
  benchmark/{tool}/          - Tool-specific benchmark tasks
  deployment/common/         - Shared deployment tasks
  deployment/{mode}/         - Mode-specific deploy/cleanup tasks
  common/                    - Cross-cutting utilities

pipelines/
  deployment/{mode}/         - End-to-end pipelines by mode
  benchmark/{tool}/          - Standalone benchmark pipelines

pipelineruns/
  {mode}/                    - Mode-specific example runs
  benchmark/{tool}/          - Standalone benchmark examples

build/{tool}/                - Container images per tool
config/rbac/                 - Service accounts, roles, bindings
config/secrets/              - Secret templates
```

---

## Task Design Rules

### Always Provide Sensible Defaults

Provide defaults for all optional parameters. Only omit defaults for truly required parameters (MODEL_NAME, TARGET, NAMESPACE).

```yaml
# REQUIRED - no default
- name: MODEL_NAME
  description: HuggingFace model identifier
  type: string

# OPTIONAL - provide default
- name: GUIDELLM_RATE
  description: Comma-separated list of rates to test
  type: string
  default: "1,50,100"
```

### Always Use optional: true for Secrets

Never let tasks fail due to missing secrets. Always mark secrets as optional.

```yaml
env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: huggingface-token
        key: HF_TOKEN
        optional: true  # REQUIRED - prevents failure if secret missing
```

### Implement Idempotency with SKIP_IF_EXISTS

Make tasks re-runnable by checking if resources already exist before creating them.

```yaml
script: |
  #!/bin/bash
  set -e

  if [ "$(params.SKIP_IF_EXISTS)" = "true" ] && [ -d "$TARGET_PATH" ]; then
    echo "✓ Already exists - skipping"
    exit 0
  fi

  # Proceed with creation...
```

### Always Sanitize Model Names

Model names contain `/` which breaks file paths and Kubernetes resource names. Always sanitize them.

```bash
# For file paths: replace / with -
MODEL_DIR_NAME=$(echo "$(params.MODEL_NAME)" | sed 's/\//-/g')

# For K8s resource names: additionally lowercase
DEPLOYMENT_NAME=$(echo "$(params.MODEL_NAME)" | sed 's/\//-/g' | tr '[:upper:]' '[:lower:]')
```

### Avoid GPU Nodes for Non-Inference Tasks

Conserve GPU resources by preventing benchmark/utility tasks from scheduling on GPU nodes.

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: nvidia.com/gpu
              operator: DoesNotExist
```

### Use Array Parameters for Lists

Use array parameters for MLFLOW_TAGS, VLLM_ARGS, BENCHMARK_ENV_VARS. Expand with `[*]` syntax.

```yaml
params:
  - name: MLFLOW_TAGS
    type: array
    default: []

# In task invocation - expand array
params:
  - name: MLFLOW_TAGS
    value: $(params.MLFLOW_TAGS[*])

# In script - iterate over array
for tag in "${TAGS_ARRAY[@]}"; do
  echo "Tag: $tag"
done
```

---

## Pipeline Design Rules

### Use runAfter for Sequential Execution

Create task dependencies with `runAfter`.

```yaml
- name: deploy-model
  runAfter:
    - download-model  # Wait for download to complete
  taskRef:
    name: deploy-rhoai-model
```

### Use when Clauses for Conditional Execution

Control workflow dynamically with `when` clauses.

```yaml
- name: run-guidellm-benchmark
  when:
    - input: "$(params.SKIP_BENCHMARK)"
      operator: in
      values: ["false"]
    - input: "$(tasks.detect-benchmark-type.results.BENCHMARK_TYPE)"
      operator: in
      values: ["guidellm"]
  taskRef:
    name: run-guidellm-benchmark
```

### Propagate Parameters Through All Three Levels

Parameters must flow through: PipelineRun → Pipeline → Task. Never skip a level.

```yaml
# Pipeline: accept parameter
params:
  - name: GUIDELLM_RATE
    default: ""

# Pipeline: pass to task
tasks:
  - name: run-guidellm-benchmark
    params:
      - name: GUIDELLM_RATE
        value: $(params.GUIDELLM_RATE)  # REQUIRED

# PipelineRun: provide value
params:
  - name: GUIDELLM_RATE
    value: "1"
```

### Match Workspace Names Consistently

Use consistent naming for workspace bindings between pipeline and task.

```yaml
# Pipeline workspace definition
workspaces:
  - name: models-storage

# Task workspace binding
tasks:
  - name: download-model
    workspaces:
      - name: models-storage      # Task's workspace name
        workspace: models-storage  # Pipeline's workspace name
```

### Always Provide Stage Control Parameters

Allow users to skip stages with SKIP_* parameters.

```yaml
params:
  - name: SKIP_DOWNLOAD
    type: string
    default: "false"
  - name: SKIP_DEPLOY
    type: string
    default: "false"
  - name: SKIP_BENCHMARK
    type: string
    default: "false"
  - name: SKIP_CLEANUP
    type: string
    default: "false"
```

---

## PipelineRun Design Rules

### Use generateName, Not name

Allow multiple runs of the same pipeline with unique identifiers.

```yaml
metadata:
  generateName: qwen-qwen3-06b-example-  # GOOD
  # name: qwen-qwen3-06b-example         # BAD - prevents multiple runs
```

### Bind Service Accounts via taskRunTemplate

Configure RBAC permissions at the PipelineRun level.

```yaml
spec:
  taskRunTemplate:
    serviceAccountName: deploy-model-sa
```

### Choose Appropriate Workspace Types

Use PVC for persistent data, emptyDir for ephemeral data.

```yaml
workspaces:
  - name: models-storage
    persistentVolumeClaim:
      claimName: models-storage  # Persistent - survives pipeline

  - name: results
    emptyDir: {}  # Ephemeral - cleaned up after pipeline
```

### Set TTL for Automatic Cleanup

Clean up completed PipelineRuns automatically.

```yaml
spec:
  ttlSecondsAfterFinished: 3600  # Delete after 1 hour
```

### Document Parameter Defaults Inline

Add comments showing default values for clarity.

```yaml
params:
  - name: GUIDELLM_RATE
    value: "1"  # DEFAULT: "1,50,100"
  - name: ACCELERATOR
    value: "H200"  # DEFAULT: "" (empty)
```

---

## Naming Conventions (Mandatory)

Follow these naming conventions strictly:

| Element | Convention | Examples |
|---------|-----------|----------|
| **Files** | kebab-case | run-benchmark.yaml, deploy-model.yaml |
| **Parameters** | SCREAMING_SNAKE_CASE | MODEL_NAME, GUIDELLM_RATE |
| **Resources (metadata.name)** | kebab-case | run-guidellm-benchmark |
| **Tool Prefixes** | {TOOL}_ | GUIDELLM_*, MLPERF_* |

### Tool Prefixing is Mandatory

Prevent parameter conflicts by prefixing tool-specific parameters.

```yaml
# Tool-specific parameters
GUIDELLM_RATE
GUIDELLM_DATA
MLPERF_SCENARIO
MLPERF_BATCH_SIZE

# Common parameters (no prefix)
MODEL_NAME
TARGET
NAMESPACE
MLFLOW_ENABLED
```

### Parameter Categories Reference

| Category | Examples | Usage |
|----------|----------|-------|
| **Common** | MODEL_NAME, TARGET, NAMESPACE, MLFLOW_ENABLED | All tools and modes |
| **GuideLLM** | GUIDELLM_RATE, GUIDELLM_DATA, GUIDELLM_MAX_SECONDS | GuideLLM only |
| **MLPerf** | MLPERF_SCENARIO, MLPERF_DATASET_NAME, MLPERF_BATCH_SIZE | MLPerf only |
| **Deployment** | VLLM_ARGS, REPLICAS, ENABLE_AUTH | Deployment config |
| **Stage Control** | SKIP_DOWNLOAD, SKIP_DEPLOY, SKIP_BENCHMARK | Workflow control |

---

## Secret Management Rules

### Never Hardcode Secrets

Always use Kubernetes secrets. Never hardcode tokens, passwords, or URLs.

```yaml
# BAD - hardcoded
env:
  - name: HF_TOKEN
    value: "hf_abc123..."

# GOOD - from secret
env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: huggingface-token
        key: HF_TOKEN
        optional: true
```

### Required Secrets

- `huggingface-token` (key: `HF_TOKEN`) - For model downloads

### Optional Secrets

- `mlflow-ui-auth` (keys: `username`, `password`, `tracking-uri`) - For MLflow tracking
- `mlflow-s3-secret` (keys: `access-key`, `secret-key`, `bucket-name`, `region`) - For S3 storage

### Volume Mount Pattern

For file-based secrets, mount as read-only volumes.

```yaml
volumeMounts:
  - name: credentials
    mountPath: /secrets
    readOnly: true

volumes:
  - name: credentials
    secret:
      secretName: api-credentials
      optional: true
```

---

## Parameter Design Requirements

### Always Include Comprehensive Descriptions

Every parameter must have a clear, detailed description.

```yaml
params:
  - name: PARAMETER_NAME          # SCREAMING_SNAKE_CASE
    description: >-                # Multi-line descriptions allowed
      What this parameter does.
      Include tool association if tool-specific.
      Document optional behavior.
    type: string                   # or array
    default: "sensible-value"      # Provide when possible
```

### Parameter Types

- Use `string` for single values
- Use `array` for lists (expand with `[*]`)

### Description Guidelines

- Be specific and comprehensive
- Mention tool association for tool-specific params
- Document optional behavior (e.g., "optional - empty disables feature")
- Include examples for complex cases

---

## Bash Script Standards

### Always Use set -e

Fail fast on errors.

```bash
#!/bin/bash
set -e  # REQUIRED - fail on first error
```

### Echo Progress for Debugging

Provide clear progress messages.

```bash
echo "Starting operation..."
echo "Parameter value: $(params.PARAM_NAME)"
echo "✓ Operation complete"
```

### Validate Inputs Early

Check required parameters before operations.

```bash
if [ -z "$(params.REQUIRED_PARAM)" ]; then
  echo "ERROR: REQUIRED_PARAM is empty"
  exit 1
fi
```

### Use Tekton Parameter Syntax

```bash
MODEL_NAME="$(params.MODEL_NAME)"
WORKSPACE_PATH="$(workspaces.storage.path)"

# Array expansion
for item in $(params.ARRAY_PARAM[*]); do
  echo "Processing: $item"
done
```

---

## Prohibited Practices

### ❌ Never Hardcode Values

```yaml
# BAD
env:
  - name: MLFLOW_TRACKING_URI
    value: "https://mlflow.example.com"  # Hardcoded!

# GOOD
env:
  - name: MLFLOW_TRACKING_URI
    valueFrom:
      secretKeyRef:
        name: mlflow-ui-auth
        key: tracking-uri
        optional: true
```

### ❌ Never Duplicate Logic

```yaml
# BAD - multiple copies of same task
tasks/deployment/rhoai/download-model.yaml
tasks/deployment/llm-d/download-model.yaml

# GOOD - single common task
tasks/deployment/common/download-model.yaml
```

### ❌ Never Create Bash Scripts Instead of Tasks

```bash
# BAD
scripts/deploy-model.sh
scripts/run-benchmark.sh

# GOOD
tasks/deployment/{mode}/deploy-model.yaml
tasks/benchmark/{tool}/run-benchmark.yaml
```

### ❌ Never Mix Advanced Docs in README

Keep README simple. Put advanced documentation in `docs/`.

```markdown
# BAD: README.md with advanced topics
1. Installation
2. Quickstart
3. Advanced Deployment Options     ← Move to docs/
4. Custom Pipeline Development      ← Move to docs/

# GOOD: README.md
1. Installation
2. Quickstart
3. Documentation → See docs/
```

### ❌ Never Create Parameters Without Tool Prefixes

```yaml
# BAD - ambiguous
params:
  - name: RATE          # Which tool?
  - name: DURATION      # Which tool?

# GOOD - clear ownership
params:
  - name: GUIDELLM_RATE
  - name: MLPERF_SERVER_TARGET_QPS
```

### ❌ Never Leave Parameters Undocumented

```yaml
# BAD
params:
  - name: GUIDELLM_RATE
    type: string
    default: "1,50,100"
    # No description!

# GOOD
params:
  - name: GUIDELLM_RATE
    description: Comma-separated list of rates to test (GuideLLM only)
    type: string
    default: "1,50,100"
```

### ❌ Never Omit Defaults for Optional Parameters

```yaml
# BAD
params:
  - name: GUIDELLM_PROCESSOR
    description: Tokenizer model name (optional)
    type: string
    # No default - will fail!

# GOOD
params:
  - name: GUIDELLM_PROCESSOR
    description: Tokenizer model name (optional)
    type: string
    default: ""  # Empty = optional
```

### ❌ Never Forget Model Name Sanitization

```bash
# BAD
MODEL_PATH="/models/$(params.MODEL_NAME)"
# Result: /models/meta-llama/Llama-3.1-8B (breaks!)

# GOOD
MODEL_DIR_NAME=$(echo "$(params.MODEL_NAME)" | sed 's/\//-/g')
MODEL_PATH="/models/${MODEL_DIR_NAME}"
# Result: /models/meta-llama-Llama-3.1-8B
```

### ❌ Never Skip Parameter Propagation Levels

```yaml
# BAD - parameter not passed to task
tasks:
  - name: run-guidellm-benchmark
    params:
      - name: TARGET
        value: $(params.TARGET)
      # GUIDELLM_RATE missing!

# GOOD - all parameters propagated
tasks:
  - name: run-guidellm-benchmark
    params:
      - name: TARGET
        value: $(params.TARGET)
      - name: GUIDELLM_RATE
        value: $(params.GUIDELLM_RATE)
```

### ❌ Never Mix Deployment Logic in Common Tasks

```yaml
# BAD - mode logic in common task
script: |
  if [ "$MODE" = "rhoai" ]; then
    # RHOAI logic
  elif [ "$MODE" = "llm-d" ]; then
    # llm-d logic
  fi

# GOOD - separate mode-specific tasks
tasks/deployment/rhoai/deploy-model.yaml
tasks/deployment/llm-d/deploy-model.yaml
```

### ❌ Never Break Naming Conventions

```yaml
# BAD - mixed conventions
params:
  - name: modelName        # camelCase
  - name: guidellm_rate    # snake_case
  - name: MLPERF-SCENARIO  # kebab-case

# GOOD - consistent SCREAMING_SNAKE_CASE
params:
  - name: MODEL_NAME
  - name: GUIDELLM_RATE
  - name: MLPERF_SCENARIO
```

### ❌ Never Ignore GPU Resource Allocation

```yaml
# BAD - no affinity (may schedule on GPU node)
# ...task definition...

# GOOD - avoid GPU nodes for non-inference tasks
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: nvidia.com/gpu
              operator: DoesNotExist
```

---

## Testing Requirements

### Pre-Submission Checklist

Before submitting any changes, verify:

- [ ] YAML syntax is valid: `oc apply --dry-run=client -f <file>`
- [ ] Parameters have appropriate defaults (required params: none; optional params: sensible defaults)
- [ ] PipelineRun examples are updated with inline DEFAULT comments
- [ ] Documentation updated in `docs/ADVANCED.md` (not README.md)
- [ ] Naming conventions followed (files: kebab-case, params: SCREAMING_SNAKE_CASE)
- [ ] No hardcoded values (URLs, tokens, secrets)
- [ ] All secrets use `optional: true`
- [ ] Tool prefixes used correctly (GUIDELLM_*, MLPERF_*)

### Testing Workflow

1. Validate YAML: `oc apply --dry-run=client -f <file>`
2. Create/update PipelineRun example in `pipelineruns/{mode}/`
3. Test parameter propagation (PipelineRun → Pipeline → Task)
4. Execute pipeline: `oc create -f pipelineruns/{mode}/test-run.yaml`
5. Verify completion: `oc get pipelinerun -w`
6. Test parameter defaults by removing optional params from PipelineRun

---

## Extension Patterns

### When Adding a New Benchmark Tool

1. Create container image in `build/{tool}/`
2. Create task in `tasks/benchmark/{tool}/run-benchmark.yaml`
3. Use prefixed parameters: `{TOOL}_RATE`, `{TOOL}_DURATION`, etc.
4. Create standalone pipeline in `pipelines/benchmark/{tool}/`
5. Create example PipelineRuns in `pipelineruns/benchmark/{tool}/`
6. Support MLflow integration with MLFLOW_ENABLED parameter
7. Update `tasks/common/detect-benchmark-type.yaml` if needed
8. Run `scripts/install.sh` (auto-discovers new resources)

**Key Requirements**:
- Use SCREAMING_SNAKE_CASE with tool prefixes
- Support both MLflow and PVC storage modes
- Provide sensible defaults for all parameters
- Use `optional: true` for all secrets

### When Adding a New Deployment Mode

1. Create mode-specific deploy task in `tasks/deployment/{mode}/deploy-model.yaml`
2. Create mode-specific cleanup task in `tasks/deployment/{mode}/cleanup-deployment.yaml`
3. Create end-to-end pipeline in `pipelines/deployment/{mode}/e2e-benchmark.yaml`
4. Reuse common tasks (download-model, wait-for-endpoint)
5. Create example PipelineRuns in `pipelineruns/{mode}/`
6. Update RBAC in `config/rbac/` if new K8s resources required
7. Update `docs/ADVANCED.md`

**Key Requirements**:
- Reuse common tasks (never duplicate)
- Only create mode-specific deploy/cleanup tasks
- Maintain parameter compatibility with other modes
- Support all benchmark tools via conditional execution
- Use consistent naming: `{mode}-end-to-end-benchmark`

### When Adding Custom Tasks

Follow this decision tree:

```
Is it used by multiple pipelines?
├─ Yes: Is it deployment-mode-agnostic?
│  ├─ Yes: Is it used across deployment contexts?
│  │  ├─ Yes → tasks/common/
│  │  └─ No → tasks/deployment/common/
│  └─ No: Is it mode-specific?
│     ├─ Yes → tasks/deployment/{mode}/
│     └─ No → tasks/benchmark/{tool}/
└─ No: Is it tool-specific?
   ├─ Yes → tasks/benchmark/{tool}/
   └─ No → tasks/deployment/{mode}/
```

**Examples**:
- `tasks/common/` - Cross-cutting utilities (detect-benchmark-type)
- `tasks/deployment/common/` - Shared deployment tasks (download-model, wait-for-endpoint)
- `tasks/deployment/{mode}/` - Mode-specific (deploy-rhoai-model, cleanup-llm-d-deployment)
- `tasks/benchmark/{tool}/` - Tool-specific (run-guidellm-benchmark, run-mlperf-benchmark)

---

## Quick Reference

### Common Parameters (All Tools/Modes)

```yaml
MODEL_NAME               # HuggingFace model identifier (required)
TARGET                   # Inference endpoint URL (required)
NAMESPACE                # Kubernetes namespace (required)
MLFLOW_ENABLED           # Enable MLflow tracking (default: "false")
MLFLOW_EXPERIMENT_NAME   # MLflow experiment name (default varies by tool)
MLFLOW_TAGS              # Additional tags array (default: [])
VERSION                  # Version identifier (default: "")
TP                       # Tensor parallelism size (default: "1")
BENCHMARK_ENV_VARS       # Additional env vars array (default: [])
ACCELERATOR              # Accelerator type tag (default: "")
```

### GuideLLM Parameters (GUIDELLM_* prefix)

```yaml
GUIDELLM_RATE              # Rates to test (default: "1,50,100")
GUIDELLM_DATA              # Request data profile (default: "prompt_tokens=1000,output_tokens=1000")
GUIDELLM_MAX_SECONDS       # Max duration per rate (default: "600")
GUIDELLM_PROCESSOR         # Tokenizer model name (default: "")
GUIDELLM_BACKEND_TYPE      # Backend type (default: "openai_http")
GUIDELLM_RATE_TYPE         # Rate strategy (default: "concurrent")
GUIDELLM_MAX_REQUESTS      # Max requests per rate (default: "")
```

### MLPerf Parameters (MLPERF_* prefix)

```yaml
MLPERF_DATASET_NAME        # Dataset filename (default: "")
MLPERF_SCENARIO            # Scenario type (default: "")
MLPERF_TEST_MODE           # Test mode: accuracy/performance (default: "")
MLPERF_BATCH_SIZE          # Batch size (default: "")
MLPERF_NUM_SAMPLES         # Number of samples (default: "")
MLPERF_OUTPUT_DIR          # Output directory (default: "")
MLPERF_SERVER_TARGET_QPS   # Target QPS for Server scenario (default: "")
```

### Stage Control Parameters

```yaml
SKIP_DOWNLOAD       # Skip model download (default: "false")
SKIP_DEPLOY         # Skip deployment (default: "false")
SKIP_BENCHMARK      # Skip benchmark (default: "false")
SKIP_CLEANUP        # Skip cleanup (default: "false")
SKIP_IF_EXISTS      # Task-level idempotency (default: "true")
```

### Task Locations

**Common Tasks**:
- `download-model` → `tasks/deployment/common/`
- `wait-for-endpoint` → `tasks/deployment/common/`
- `detect-benchmark-type` → `tasks/common/`

**Deploy Tasks**:
- `deploy-rhoai-model`, `deploy-llm-d-helmfile`, `deploy-rhaiis-pod`

**Cleanup Tasks**:
- `cleanup-rhoai-deployment`, `cleanup-llm-d-deployment`, `cleanup-rhaiis-deployment`

**Benchmark Tasks**:
- `run-guidellm-benchmark` → `tasks/benchmark/guidellm/`
- `run-mlperf-benchmark` → `tasks/benchmark/mlperf/`

### Pipeline Locations

**Deployment Pipelines (End-to-End)**:
- `rhoai-end-to-end-benchmark` → `pipelines/deployment/rhoai/`
- `llm-d-end-to-end-benchmark` → `pipelines/deployment/llm-d/`
- `rhaiis-end-to-end-benchmark` → `pipelines/deployment/rhaiis/`

**Benchmark Pipelines (Standalone)**:
- `guidellm-run-benchmark-pipeline` → `pipelines/benchmark/guidellm/`
- `mlperf-run-benchmark-pipeline` → `pipelines/benchmark/mlperf/`

---

## Troubleshooting Actions

### When Parameters Don't Reach Tasks

Check propagation at all three levels:

```bash
oc get pipelinerun <name> -o yaml | grep PARAMETER_NAME
cat pipelines/.../pipeline.yaml | grep PARAMETER_NAME
cat tasks/.../task.yaml | grep PARAMETER_NAME
```

Ensure: PipelineRun → Pipeline → Task all reference the parameter.

### When Array Parameters Don't Expand

Use `[*]` syntax:

```yaml
params:
  - name: MLFLOW_TAGS
    value: $(params.MLFLOW_TAGS[*])  # Expand array
```

### When Secrets Are Missing

Always use `optional: true`:

```yaml
env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: huggingface-token
        key: HF_TOKEN
        optional: true
```

### When Workspaces Aren't Bound

Verify PipelineRun workspace section matches Pipeline and Task:

```yaml
workspaces:
  - name: models-storage
    persistentVolumeClaim:
      claimName: models-storage
```

### When Tasks Aren't Found

Verify installation:

```bash
oc get task | grep <task-name>
oc apply -f tasks/.../task.yaml  # If missing
```

### When MLflow Isn't Logging

1. Verify MLFLOW_ENABLED=true
2. Check secrets exist: `oc get secret mlflow-ui-auth mlflow-s3-secret`
3. Check task logs: `oc logs <pod> -c step-run-guidellm-benchmark | grep -i mlflow`

### When Models Aren't Found

1. Check download-model task completed: `oc get pipelinerun <name> -o yaml`
2. Verify model on PVC: `oc run -it --rm debug --image=busybox -- ls -la /models`

### When Deployments Fail

1. Check RBAC: `oc get sa deploy-model-sa`
2. Check role bindings: `oc get rolebinding | grep deploy-model`
3. Check task logs: `oc logs <pod> -c step-deploy-<mode>-model`

### When Benchmarks Timeout

Increase timeout:

```yaml
params:
  - name: HEALTH_CHECK_TIMEOUT
    value: "7200"  # 2 hours for large models
```

---

## Summary of Key Requirements

1. **Follow three-tier architecture**: Tasks → Pipelines → PipelineRuns
2. **Reuse common tasks**: Never duplicate logic across modes
3. **Use parameter naming standard**: SCREAMING_SNAKE_CASE with tool prefixes (GUIDELLM_*, MLPERF_*)
4. **Implement idempotency**: Use SKIP_IF_EXISTS pattern
5. **Always use optional: true for secrets**: Never let missing secrets break tasks
6. **Design for extensibility**: Support future tools and modes
7. **Test thoroughly**: Validate YAML, test parameter flow, update docs

**Critical Files for Reference**:
- `tasks/benchmark/guidellm/run-benchmark.yaml` (task pattern exemplar)
- `pipelines/deployment/rhoai/e2e-benchmark.yaml` (pipeline pattern exemplar)
- `pipelineruns/rhoai/qwen-qwen3-06b-example.yaml` (pipelinerun pattern exemplar)
- `docs/ADVANCED.md` (documentation style guide)
