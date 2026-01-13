# Advanced Guide

This guide covers advanced topics for using, modifying, and extending the llm-d-bench project.

## Table of Contents

- [Repository Structure](#repository-structure)
- [Infrastructure Requirements](#infrastructure-requirements)
- [Tekton Concepts](#tekton-concepts)
- [Parameter Inheritance and Defaults](#parameter-inheritance-and-defaults)
- [Using the Tekton CLI](#using-the-tekton-cli)
- [Model Name Sanitization](#model-name-sanitization)
- [Creating Custom Tasks](#creating-custom-tasks)
- [Creating Custom Pipelines](#creating-custom-pipelines)
- [MLflow Integration](#mlflow-integration)
- [Building Custom Images](#building-custom-images)
- [Adding New Benchmark Tools](#adding-new-benchmark-tools)
- [Troubleshooting](#troubleshooting)
- [Additional Resources](#additional-resources)

---

## Repository Structure

```
llm-d-bench/
├── build/                    # Custom benchmark image source
│   ├── guidellm/             # GuideLLM with MLflow integration
│   └── mlperf/               # MLPerf benchmark wrapper
│
├── config/                   # Configuration resources
│   ├── rbac/                 # Service accounts and roles
│   ├── secrets/              # Secret templates
│   └── workspaces/           # PVC definitions
│
├── docs/                     # Documentation
│   └── ADVANCED.md           # This file
│
├── pipelineruns/             # Pipeline execution definitions
│   ├── llm-d/                # llm-d (Helmfile) deployments
│   ├── rhoai/                # RHOAI (KServe) deployments
│   ├── rhaiis/               # RHAIIS (Pod) deployments
│   └── benchmark/            # Standalone benchmarks
│       ├── guidellm/         # GuideLLM examples
│       └── mlperf/           # MLPerf examples
│
├── pipelines/                # Pipeline definitions (orchestration)
│   ├── deployment/           # Deployment mode pipelines
│   │   ├── llm-d/            # llm-d end-to-end
│   │   ├── rhoai/            # RHOAI end-to-end
│   │   └── rhaiis/           # RHAIIS end-to-end
│   └── benchmark/            # Benchmark pipelines
│       ├── guidellm/         # GuideLLM pipelines
│       └── mlperf/           # MLPerf pipelines
│
├── scripts/                  # Utility scripts
│   └── install.sh            # Installation automation
│
├── tasks/                    # Task definitions (atomic operations)
│   ├── deployment/           # Deployment-specific tasks
│   │   ├── llm-d/            # llm-d deployment tasks
│   │   ├── rhoai/            # RHOAI deployment tasks
│   │   ├── rhaiis/           # RHAIIS deployment tasks
│   │   └── common/           # Shared deployment tasks
│   └── benchmark/guidellm/   # Benchmark tool tasks
│
└── README.md                 # Quick start guide
```

### Directory Purposes

- **`tasks/`**: Atomic, reusable operations (build, deploy, benchmark, cleanup)
  - `deployment/`: Mode-specific deployment tasks
  - `benchmark/`: Tool-specific benchmark tasks
- **`pipelines/`**: Orchestration of tasks into workflows
  - `deployment/`: Full end-to-end workflows per deployment mode
  - `benchmark/`: Standalone benchmark pipelines
- **`pipelineruns/`**: Concrete executions with specific parameters
  - Organized by deployment mode and benchmark tool
- **`build/`**: Benchmark tool container images
  - Each tool has its own subdirectory
- **`config/`**: Kubernetes resources (RBAC, secrets, PVCs)
- **`scripts/`**: Installation and utility automation

---

## Infrastructure Requirements

### RHOAI Deployment (LLMInferenceService)

This repository supports **RHOAI deployment** using distributed inference through `LLMInferenceService` via RHOAI 3.0. However, infrastructure provisioning is **not yet fully automated** and may require manual adjustments.

**Key Points:**

- **Deployment Mechanism**: Uses KServe's `LLMInferenceService` custom resource for distributed inference
- **Infrastructure**: Requires RHOAI 3.0 (Red Hat OpenShift AI) or compatible KServe installation
- **Manual Setup**: Infrastructure components may need manual configuration
- **Reference Manifests**: See `infra/manifests/rhoai/` and `infra/manifests/rhcl/` for example configurations

**What's Automated:**
- Model download from HuggingFace
- `LLMInferenceService` deployment and configuration
- Benchmark execution
- Deployment cleanup

**What May Require Manual Setup:**
- RHOAI/KServe operator installation
- Service mesh configuration (Istio/OpenShift Service Mesh)
- GPU node configuration and scheduling
- Storage class provisioning
- Network policies and ingress

**Recommendation**: Review the manifests in `infra/manifests/` and adapt them to your cluster's configuration before running downstream e2e pipelines.

---

## Tekton Concepts

### Tasks

A **Task** is the smallest unit of work in Tekton. It defines:
- **Parameters**: Inputs that customize the task behavior
- **Steps**: Sequential shell scripts or container commands
- **Workspaces**: Shared storage volumes
- **Results**: Outputs passed to other tasks

Example task structure:
```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: my-task
spec:
  params:
    - name: INPUT
      type: string
      default: "default-value"
  steps:
    - name: step-1
      image: registry.access.redhat.com/ubi9/ubi:latest
      script: |
        #!/bin/bash
        echo "Input: $(params.INPUT)"
```

**Tasks in this repo:**
- `download-model`: Downloads HuggingFace models to PVC (common)
- `deploy-rhoai-model`: Creates LLMInferenceService deployments
- `deploy-llm-d-helmfile`: Deploys using Helmfile GitOps
- `deploy-rhaiis-pod`: Deploys as simple Pod with RHAIIS/vLLM
- `wait-for-endpoint`: Polls endpoint until ready (common)
- `run-guidellm-benchmark`: Executes GuideLLM benchmarks
- `cleanup-rhoai-deployment`, `cleanup-llm-d-deployment`, `cleanup-rhaiis-deployment`: Remove deployments

### Pipelines

A **Pipeline** chains tasks together into a workflow. It defines:
- **Parameters**: Inputs for the entire pipeline
- **Tasks**: Ordered task invocations
- **Workspaces**: Shared volumes across tasks
- **When conditions**: Conditional task execution

Example pipeline structure:
```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: my-pipeline
spec:
  params:
    - name: MODEL_NAME
      type: string
  tasks:
    - name: task-1
      taskRef:
        name: my-task
      params:
        - name: INPUT
          value: $(params.MODEL_NAME)
```

**Pipelines in this repo:**
- `guidellm-build-image`: Builds custom GuideLLM container
- `guidellm-run-benchmark-pipeline`: Standalone benchmark execution
- `llm-d-end-to-end-benchmark`: Complete llm-d workflow (download → deploy-helmfile → wait → benchmark → cleanup)
- `rhoai-end-to-end-benchmark`: Complete RHOAI workflow (download → deploy-rhoai → wait → benchmark → cleanup)
- `rhaiis-end-to-end-benchmark`: Complete RHAIIS workflow (download → deploy-rhaiis → wait → benchmark → cleanup)

### PipelineRuns

A **PipelineRun** is a concrete execution of a pipeline with specific parameter values. It:
- References a pipeline
- Provides all required parameter values
- Binds workspaces to PVCs
- Can specify service accounts, timeouts, and cleanup policies

**PipelineRuns in this repo:**
- Located in `pipelineruns/llm-d/`, `pipelineruns/rhoai/`, `pipelineruns/rhaiis/`, and `pipelineruns/benchmark/guidellm/`
- Each represents a specific benchmark experiment
- Uses `generateName` for unique run names

---

## Parameter Inheritance and Defaults

Parameters flow through three levels: **Task → Pipeline → PipelineRun**

### Level 1: Task Default Values

Tasks define default values for parameters:

```yaml
# tasks/benchmark/run-benchmark.yaml
spec:
  params:
    - name: MAX_SECONDS
      type: string
      default: "600"    # Default value
```

### Level 2: Pipeline Overrides

Pipelines can override task defaults:

```yaml
# pipelines/downstream/full-benchmark-lifecycle.yaml
spec:
  params:
    - name: MAX_SECONDS
      type: string
      default: "600"    # Pipeline-level default
  tasks:
    - name: run-benchmark
      params:
        - name: MAX_SECONDS
          value: $(params.MAX_SECONDS)    # Pass pipeline param to task
```

### Level 3: PipelineRun Overrides

PipelineRuns override pipeline defaults:

```yaml
# pipelineruns/downstream/my-benchmark.yaml
spec:
  params:
    - name: MAX_SECONDS
      value: "1200"    # Override for this specific run
```

### Inheritance Rules

1. **If not specified in PipelineRun**: Uses pipeline default
2. **If not specified in Pipeline**: Uses task default
3. **If not specified in Task**: Parameter is required

**Example:**
```
Task:        MAX_SECONDS = "600"  (default)
Pipeline:    MAX_SECONDS = "600"  (optional override)
PipelineRun: MAX_SECONDS = "1200" (final value used)
```

This means you only need to specify parameters that differ from defaults!

---

## Using the Tekton CLI

### Installation

```bash
# macOS
brew install tektoncd-cli

# Linux
curl -LO https://github.com/tektoncd/cli/releases/download/v0.38.0/tkn_0.38.0_Linux_x86_64.tar.gz
tar xvzf tkn_0.38.0_Linux_x86_64.tar.gz -C /usr/local/bin/ tkn
```

### Creating a PipelineRun from CLI

Instead of YAML files, you can use `tkn` to start pipelines:

#### Example: Complete Benchmark Lifecycle

This example replicates `pipelineruns/downstream/redhatai-llama-3.3-70b-instruct-fp8-dynamic-1k-1k.yaml`:

```bash
tkn pipeline start full-benchmark-lifecycle \
  --namespace downstream-llm-d \
  --serviceaccount deploy-model-sa \
  --workspace name=models-storage,claimName=models-storage \
  --param MODEL_NAME="RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic" \
  --param MODEL_REVISION="main" \
  --param NAMESPACE="downstream-llm-d" \
  --param VLLM_ARGS="--max-model-len=8192" \
  --param VLLM_ARGS="--uvicorn-log-level=debug" \
  --param VLLM_ARGS="--trust-remote-code" \
  --param VLLM_ARGS="--gpu-memory-utilization=0.92" \
  --param VLLM_ARGS="--no-enable-prefix-caching" \
  --param VLLM_ARGS="--disable-log-requests" \
  --param ENABLE_AUTH="false" \
  --param REPLICAS="1" \
  --param IMAGE="image-registry.openshift-image-registry.svc:5000/downstream-llm-d/guidellm-custom:latest" \
  --param TARGET="https://redhatai-llama-33-70b-instruct-fp8-dynamic-kserve-workload-svc.downstream-llm-d.svc.cluster.local:8000" \
  --param PROCESSOR="RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic" \
  --param BACKEND_TYPE="openai_http" \
  --param RATE_TYPE="concurrent" \
  --param RATE="650,500,300,200,100,50,1" \
  --param DATA="prompt_tokens=1000,output_tokens=1000" \
  --param MAX_SECONDS="600" \
  --param MAX_REQUESTS="" \
  --param ACCELERATOR="H200" \
  --param EXPERIMENT_NAME="redhatai-llama-33-70b-instruct-fp8-dynamic-1k-1k" \
  --param VERSION="RHOAI-3.0" \
  --param TP="1" \
  --param BENCHMARK_ENV_VARS="GUIDELLM__MAX_WORKER_PROCESSES=100" \
  --param MLFLOW_ENABLED="true" \
  --param TAGS="llm-d-version=RHOAI-3.0" \
  --param HEALTH_CHECK_TIMEOUT="3600" \
  --param SKIP_DOWNLOAD="true" \
  --param SKIP_DEPLOY="false" \
  --param SKIP_BENCHMARK="false" \
  --param SKIP_CLEANUP="false" \
  --showlog
```

**Note**: For array parameters like `VLLM_ARGS`, repeat the `--param` flag for each element.

#### Simplified Example (Using Defaults)

Most parameters have defaults, so you can simplify:

```bash
tkn pipeline start full-benchmark-lifecycle \
  --namespace downstream-llm-d \
  --serviceaccount deploy-model-sa \
  --workspace name=models-storage,claimName=models-storage \
  --param MODEL_NAME="meta-llama/Llama-3.1-8B" \
  --param NAMESPACE="downstream-llm-d" \
  --param TARGET="https://meta-llama-llama-31-8b-kserve-workload-svc.downstream-llm-d.svc.cluster.local:8000" \
  --param RATE="1,50,100" \
  --param MLFLOW_ENABLED="true" \
  --showlog
```

### Useful tkn Commands

```bash
# List pipelines
tkn pipeline list -n downstream-llm-d

# List recent runs
tkn pipelinerun list -n downstream-llm-d

# Watch logs
tkn pipelinerun logs -f <pipelinerun-name> -n downstream-llm-d

# View specific task logs
tkn pipelinerun logs <pipelinerun-name> -t run-benchmark -n downstream-llm-d

# Describe a pipeline
tkn pipeline describe full-benchmark-lifecycle -n downstream-llm-d

# Cancel a running pipeline
tkn pipelinerun cancel <pipelinerun-name> -n downstream-llm-d

# Delete completed runs
tkn pipelinerun delete <pipelinerun-name> -n downstream-llm-d
```

---

## Model Name Sanitization

Deployment names in Kubernetes have strict naming requirements. The project automatically sanitizes model names using this logic:

```bash
DEPLOYMENT_NAME=$(echo "$MODEL_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/\//-/g' | sed 's/\.//g' | sed 's/-$//' | cut -c1-42)
```

---

## Creating Custom Tasks

### Task Template

```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: my-custom-task
  labels:
    app.kubernetes.io/version: "0.1"
  annotations:
    tekton.dev/displayName: "My Custom Task"
    tekton.dev/tags: custom, example
    tekton.dev/platforms: "linux/amd64"
spec:
  description: |
    A custom task for my specific use case.
    Provide detailed documentation here.

  params:
    - name: INPUT_PARAM
      description: Description of what this parameter does
      type: string
      default: "default-value"

    - name: ARRAY_PARAM
      description: Array parameter example
      type: array
      default: []

  workspaces:
    - name: shared-data
      description: Shared workspace for data
      optional: false

  steps:
    - name: main-step
      image: registry.access.redhat.com/ubi9/ubi:latest
      workingDir: /tmp
      script: |
        #!/bin/bash
        set -e

        echo "Input: $(params.INPUT_PARAM)"

        # Access workspace
        ls -la $(workspaces.shared-data.path)

        # Your logic here
```

### Best Practices

1. **Use descriptive parameter names**: `MODEL_NAME` not `M`
2. **Provide defaults when sensible**: Makes tasks easier to use
3. **Document everything**: Description, parameters, expected behavior
4. **Use `set -e`**: Fail fast on errors
5. **Log progress**: Use `echo` statements for debugging
6. **Handle idempotency**: Check if work already done before proceeding

### Adding a New Task

1. Create YAML file in appropriate directory:
   - `tasks/benchmark/guidellm/` - Benchmarking operations
   - `tasks/deployment/common/` - Shared utilities
   - `tasks/deployment/rhoai/` - RHOAI-specific
   - `tasks/deployment/llm-d/` - llm-d-specific
   - `tasks/deployment/rhaiis/` - RHAIIS-specific

2. Test task standalone:
   ```bash
   oc apply -f tasks/my-category/my-task.yaml -n downstream-llm-d
   ```

3. Create a TaskRun for testing:
   ```yaml
   apiVersion: tekton.dev/v1
   kind: TaskRun
   metadata:
     generateName: test-my-task-
   spec:
     taskRef:
       name: my-custom-task
     params:
       - name: INPUT_PARAM
         value: "test-value"
   ```

4. Update `scripts/install.sh` to include your task

---

## Creating Custom Pipelines

### Pipeline Template

```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: my-custom-pipeline
  labels:
    app.kubernetes.io/version: "0.1"
  annotations:
    tekton.dev/displayName: "My Custom Pipeline"
    tekton.dev/tags: custom, example
spec:
  description: |
    A custom pipeline for my workflow.

  params:
    # Pipeline-level parameters
    - name: MODEL_NAME
      description: Model identifier
      type: string

    - name: SKIP_STAGE_1
      description: Skip the first stage
      type: string
      default: "false"

  workspaces:
    - name: shared-workspace
      description: Shared data workspace

  tasks:
    # Stage 1: First task
    - name: stage-1
      when:
        - input: "$(params.SKIP_STAGE_1)"
          operator: in
          values: ["false"]
      taskRef:
        name: my-custom-task
      params:
        - name: INPUT_PARAM
          value: $(params.MODEL_NAME)
      workspaces:
        - name: shared-data
          workspace: shared-workspace

    # Stage 2: Depends on stage-1
    - name: stage-2
      runAfter:
        - stage-1
      taskRef:
        name: another-task
      params:
        - name: SOME_PARAM
          value: "value"
```

### Pipeline Patterns

#### Sequential Execution
```yaml
tasks:
  - name: task-1
    taskRef:
      name: first-task

  - name: task-2
    runAfter:
      - task-1
    taskRef:
      name: second-task
```

#### Conditional Execution
```yaml
- name: conditional-task
  when:
    - input: "$(params.SKIP_ME)"
      operator: in
      values: ["false"]
  taskRef:
    name: my-task
```

#### Parameter Passing
```yaml
# Pass pipeline param to task
params:
  - name: MODEL_NAME
    value: $(params.MODEL_NAME)

# Pass array param (expanded)
params:
  - name: VLLM_ARGS
    value: $(params.VLLM_ARGS[*])
```

---

## MLflow Integration

### Overview

The custom benchmark image (`build/`) wraps GuideLLM with MLflow tracking.

### MLflow Parameters Logged

The following parameters are automatically logged to MLflow:

- `target` - Inference endpoint URL
- `model` - Model name
- `backend_type` - Backend type (e.g., openai_http)
- `rate_type` - Rate strategy (concurrent/synchronous)
- `rates` - Comma-separated rate values
- `prompt_tokens` - Input token count
- `output_tokens` - Output token count
- `max_seconds` - Duration per rate
- `max_requests` - Max requests per rate
- `processor` - Tokenizer name
- `accelerator` - GPU type (H200, A100, etc.)
- `tp` - Tensor parallelism size

### MLflow Metrics Logged

For each concurrency level, the following metrics are logged:

**Throughput:**
- `throughput_requests_per_sec`
- `total_tokens_per_second`
- `throughput_output_tokens_per_sec`

**Latency:**
- `latency_mean_sec`, `latency_median_sec`
- `latency_p50_sec`, `latency_p90_sec`, `latency_p95_sec`, `latency_p99_sec`

**Time to First Token (TTFT):**
- `ttft_mean_ms`, `ttft_median_ms`
- `ttft_p95_ms`, `ttft_p99_ms`

**Inter-Token Latency (ITL):**
- `itl_mean_ms`, `itl_median_ms`
- `itl_p95_ms`, `itl_p99_ms`

**Time Per Output Token (TPOT):**
- `tpot_mean_ms`, `tpot_median_ms`
- `tpot_p95_ms`, `tpot_p99_ms`

**Request Stats:**
- `total_requests`, `successful_requests`, `failed_requests`
- `error_rate`
- `request_concurrency_mean`

**Tokens:**
- `total_input_tokens`, `total_output_tokens`, `total_tokens`

### MLflow Tags

Default tags automatically set:
- `model` - Model name
- `rate_type` - Concurrent or synchronous
- `vllm` - vLLM version (from endpoint)
- `guidellm` - GuideLLM version
- `accelerator` - GPU type (if specified)

Custom tags from PipelineRun `TAGS` parameter:
```yaml
params:
  - name: TAGS
    value:
      - "llm-d-version=RHOAI-3.0"
      - "team=ai"
      - "environment=production"
```

### MLflow Artifacts

- `results/benchmark_sweep.json` - Complete benchmark results
- `logs/benchmark_sweep_console.log` - Console output
- `reports/*.html` - Visualization reports (if generated)

### Customizing MLflow Parameters

To add new parameters to MLflow tracking, edit `build/src/benchmark/main.py`:

```python
# Around line 456
params = {
    "target": target,
    "model": model,
    # ... existing params ...
    "my_new_param": my_value,  # Add your parameter
}

mlflow.log_params(params)
```

Then rebuild the image:
```bash
oc create -f pipelineruns/build-image-run.yaml -n downstream-llm-d
```

---

## MLPerf Benchmark Tool

### Overview

llm-d-bench supports two benchmark tools: **GuideLLM** (default) and **MLPerf**. Switch between them by using different benchmark images and pipelines.

**GuideLLM:**
- Load testing with concurrency control
- Detailed performance metrics (TTFT, ITL, TPOT)
- Integrated MLflow tracking
- Custom visualization reports

**MLPerf:**
- Standardized MLPerf Inference benchmark
- Official MLPerf scenarios (Offline, Server, etc.)
- Accuracy and performance testing
- Industry-standard metrics

### Switching Between Tools

The benchmark tasks are tool-specific:
- GuideLLM: Use `run-guidellm-benchmark` task or `guidellm-run-benchmark-pipeline`
- MLPerf: Use `run-mlperf-benchmark` task or `mlperf-run-benchmark-pipeline`

**GuideLLM Example:**
```yaml
params:
  - name: IMAGE
    value: "image-registry.openshift-image-registry.svc:5000/llm-d-bench/guidellm-custom:latest"
  - name: RATE
    value: "1,50,100"
  - name: DATA
    value: "prompt_tokens=1000,output_tokens=1000"
  - name: MAX_SECONDS
    value: "600"
```

**MLPerf Example:**
```yaml
params:
  - name: IMAGE
    value: "image-registry.openshift-image-registry.svc:5000/llm-d-bench/mlperf-custom:latest"
  - name: DATASET_NAME
    value: "cnn_eval.json"
  - name: SCENARIO
    value: "Offline"
  - name: TEST_MODE
    value: "accuracy"
  - name: NUM_SAMPLES
    value: "4388"
```

### Parameter Mapping

| Parameter | GuideLLM | MLPerf | Notes |
|-----------|----------|--------|-------|
| **TARGET** | ✓ | ✓ | Inference endpoint URL |
| **MODEL** | ✓ | ✓ | Model identifier (MLPerf derives category) |
| **EXPERIMENT_NAME** | ✓ | ✓ | MLflow experiment name |
| **MLFLOW_TRACKING_URI** | ✓ | ✓ | MLflow server |
| **RATE** | ✓ | ✗ | Concurrency levels (GuideLLM only) |
| **DATA** | ✓ | ✗ | Token counts (GuideLLM only) |
| **MAX_SECONDS** | ✓ | ✗ | Duration per rate (GuideLLM only) |
| **DATASET_NAME** | ✗ | ✓ | Dataset filename (MLPerf only) |
| **SCENARIO** | ✗ | ✓ | MLPerf scenario (Offline, Server, etc.) |
| **TEST_MODE** | ✗ | ✓ | Test mode (accuracy, performance) |
| **BATCH_SIZE** | ✗ | ✓ | Batch size (MLPerf only) |
| **NUM_SAMPLES** | ✗ | ✓ | Number of samples (MLPerf only) |

### Dataset Management for MLPerf

MLPerf benchmarks require dataset files pre-uploaded to the `models-storage` PVC.

#### Dataset Storage Structure

```
models-storage PVC:
├── models/                    # Model files (existing)
│   ├── meta-llama-llama-31-8b/
│   └── ...
└── datasets/                  # Dataset files (for MLPerf)
    ├── cnn_eval.json
    └── ...
```

#### Uploading Datasets

**Step 1: Create a temporary pod with PVC mounted**

```bash
oc run dataset-upload --image=registry.access.redhat.com/ubi9/ubi:latest \
  --overrides='{"spec":{"volumes":[{"name":"models-storage","persistentVolumeClaim":{"claimName":"models-storage"}}],"containers":[{"name":"dataset-upload","image":"registry.access.redhat.com/ubi9/ubi:latest","command":["sleep","3600"],"volumeMounts":[{"name":"models-storage","mountPath":"/mnt/storage"}]}]}}' \
  -n llm-d-bench
```

**Step 2: Create datasets directory and upload files**

```bash
# Create datasets directory
oc exec -it dataset-upload -n llm-d-bench -- mkdir -p /mnt/storage/datasets

# Copy dataset file from local machine to PVC
oc cp cnn_eval.json dataset-upload:/mnt/storage/datasets/cnn_eval.json -n llm-d-bench

# Verify upload
oc exec -it dataset-upload -n llm-d-bench -- ls -lh /mnt/storage/datasets/
```

**Step 3: Clean up**

```bash
oc delete pod dataset-upload -n llm-d-bench
```

#### Dataset Path Resolution

When you specify `DATASET_NAME: "cnn_eval.json"`, the benchmark task automatically constructs:

```bash
DATASET_PATH="/mnt/storage/datasets/cnn_eval.json"
```

The task verifies the dataset exists before running MLPerf and fails with a helpful error if not found.

### MLPerf Model Category Derivation

The MLPerf wrapper automatically derives the `--model-category` parameter from the MODEL name:

**Examples:**
- `RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8` → `llama3.1-8b`
- `meta-llama/Llama-3.1-70B` → `llama3.1-70b`
- `meta-llama/Llama-2-70B` → `llama2-70b`

To customize this logic, edit `build/mlperf/src/benchmark/main.py:derive_model_category()`.

### Building MLPerf Image

Before using MLPerf, build the custom MLPerf image:

```bash
# Build MLPerf image
oc create -f pipelineruns/benchmark/mlperf/build-image-run.yaml -n llm-d-bench

# Watch build progress
tkn pipelinerun logs -f -n llm-d-bench

# Image location:
# image-registry.openshift-image-registry.svc:5000/llm-d-bench/mlperf-custom:latest
```

### Running MLPerf Benchmarks

**Option 1: End-to-End Pipeline** (recommended)

Use the MLPerf-specific deployment pipeline for a complete workflow:

1. Upload datasets to PVC (see Dataset Management above)
2. Run end-to-end pipeline with deployment + benchmark + cleanup:

```bash
# llm-d deployment with MLPerf benchmark
oc create -f pipelineruns/llm-d/meta-llama-3.1-8b-mlperf.yaml -n llm-d-bench
```

**Available MLPerf deployment pipelines:**
- `llm-d-end-to-end-benchmark-mlperf` - llm-d (Helmfile) + MLPerf
- Additional deployment modes can use standalone benchmark (see Option 2)

**Option 2: Standalone Benchmark**

1. Deploy your model first (using any deployment mode with `SKIP_BENCHMARK=true`)
2. Upload datasets to PVC (see Dataset Management above)
3. Run standalone MLPerf benchmark:

```bash
oc create -f pipelineruns/benchmark/mlperf/run-benchmark-example.yaml -n llm-d-bench
```

### MLPerf Scenarios

MLPerf supports multiple standardized scenarios:

- **Offline**: Maximum throughput, no latency constraints
- **Server**: Target QPS with latency constraints
- **SingleStream**: Process one sample at a time
- **MultiStream**: Process multiple streams simultaneously

Each scenario has specific metrics and requirements. See [MLPerf Inference rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc) for details.

---

## Building Custom Images

### Overview

The `build/` directory contains container build configurations for benchmark tools. Each tool has its own subdirectory with build files.

### Directory Structure

```
build/
├── guidellm/              # GuideLLM with MLflow integration
│   ├── Containerfile
│   ├── pyproject.toml
│   └── src/
└── mlperf/                # MLPerf benchmark wrapper
    ├── Containerfile
    └── src/
```

### Current Tools

#### guidellm/

GuideLLM benchmark tool with custom MLflow integration wrapper.

**Base Image:** `ghcr.io/vllm-project/guidellm:v0.3.1`

**Enhancements:**
- MLflow 3.7.0 integration for experiment tracking
- S3 artifact storage support
- Benchmark result processing and visualization
- CSV consolidation for historical comparison
- Interactive Plotly HTML reports

**Local Build:**
```bash
cd build/guidellm
podman build -t guidellm-custom:latest -f Containerfile .
```

**Pipeline Build:**
```bash
oc create -f pipelineruns/benchmark/guidellm/build-image-run.yaml
```

#### mlperf/

MLPerf benchmark tool with MLflow integration wrapper.

**Base Image:** `python:3.11-slim`

**Components:**
- MLCommons MLPerf Inference loadgen
- OpenShift PSAP MLPerf harness for LLMs
- MLflow integration for experiment tracking
- Support for Offline, Server, SingleStream, and MultiStream scenarios

**Local Build:**
```bash
cd build/mlperf
podman build -t mlperf-custom:latest -f Containerfile .
```

**Pipeline Build:**
```bash
oc create -f pipelineruns/benchmark/mlperf/build-image-run.yaml
```

**Requirements:**
- Datasets must be pre-uploaded to `models-storage` PVC
- See [MLPerf Benchmark Tool](#mlperf-benchmark-tool) section for details

### Image Build Pipeline

The `guidellm-build-image` pipeline builds a custom container with MLflow integration:

```bash
# Trigger image build
oc create -f pipelineruns/benchmark/guidellm/build-image-run.yaml -n llm-d-bench

# Watch build progress
tkn pipelinerun logs -f -n llm-d-bench

# New image will be at:
# image-registry.openshift-image-registry.svc:5000/llm-d-bench/guidellm-custom:latest
```

### Build Process

1. **git-clone**: Clones this repository
2. **guidellm-buildah-build**: Builds container using `build/guidellm/Containerfile`
3. **Push**: Pushes to OpenShift internal registry

### Adding New Benchmark Tools

To add a new benchmark tool, create a subdirectory with the following structure:

#### 1. Create Directory

```bash
mkdir -p build/<tool-name>
cd build/<tool-name>
```

#### 2. Add Containerfile

Create a `Containerfile` (or `Dockerfile`) with your build instructions:

```dockerfile
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy tool code
COPY src/ /app/
WORKDIR /app

# Set entrypoint
ENTRYPOINT ["python", "-m", "benchmark.main"]
```

#### 3. Add Dependencies

Choose your dependency management approach:

**Option A: requirements.txt** (simple)
```txt
locust==2.15.1
mlflow==3.7.0
boto3==1.28.0
```

**Option B: pyproject.toml** (modern)
```toml
[project]
name = "locust-benchmark"
version = "0.1.0"
dependencies = [
    "locust>=2.15.1",
    "mlflow>=3.7.0",
    "boto3>=1.28.0",
]
```

#### 4. Add Tool-Specific Code (Optional)

Create `src/` directory for custom wrapper code:

```bash
mkdir -p src/benchmark
```

Example wrapper for MLflow integration:
```python
# src/benchmark/main.py
import subprocess
import mlflow

def run_benchmark(target, model, rate):
    # Execute benchmark tool
    result = subprocess.run([
        "locust",
        "--host", target,
        "--users", str(rate),
        # ... other args
    ], capture_output=True)

    # Log to MLflow
    if mlflow_enabled:
        mlflow.log_metrics({
            "throughput": parse_throughput(result),
            "latency": parse_latency(result),
        })
```

#### 5. Test Build Locally

```bash
podman build -t <tool-name>:test -f Containerfile .
podman run <tool-name>:test --help
```

#### 6. Create Tekton Build Pipeline

See the [Adding New Benchmark Tools](#adding-new-benchmark-tools) section for creating the corresponding Tekton tasks and pipelines.

### Best Practices

#### Container Images

1. **Use specific base image versions** - Not `latest`
   ```dockerfile
   # Good
   FROM python:3.11.6-slim

   # Bad
   FROM python:latest
   ```

2. **Multi-stage builds** - Keep images small
   ```dockerfile
   FROM python:3.11 AS builder
   RUN pip install --user package

   FROM python:3.11-slim
   COPY --from=builder /root/.local /root/.local
   ```

3. **Layer caching** - Copy dependencies before code
   ```dockerfile
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   COPY src/ /app/  # Changes more frequently
   ```

#### Dependencies

1. **Pin versions** - Ensure reproducibility
   ```txt
   # Good
   mlflow==3.7.0

   # Bad
   mlflow>=3.0
   ```

2. **Minimal dependencies** - Only install what you need
3. **Security** - Regularly update dependencies for CVE fixes

#### MLflow Integration

For consistency with existing tools, consider integrating with MLflow:

```python
import mlflow

# Set tracking URI
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))

# Create experiment
mlflow.set_experiment(experiment_name)

# Log parameters and metrics
with mlflow.start_run():
    mlflow.log_params({
        "model": model_name,
        "rate": rate,
    })

    # Run benchmark
    results = run_benchmark()

    # Log metrics
    mlflow.log_metrics(results)

    # Upload artifacts
    mlflow.log_artifact("results.json")
```

#### Image Size Optimization

Tips to keep images small:

1. Use slim/alpine base images
2. Multi-stage builds
3. Clean up in same layer:
   ```dockerfile
   RUN apt-get update && \
       apt-get install -y build-essential && \
       pip install package && \
       apt-get remove -y build-essential && \
       apt-get autoremove -y && \
       rm -rf /var/lib/apt/lists/*
   ```
4. Use `.dockerignore`:
   ```
   .git
   *.md
   tests/
   __pycache__/
   ```

### Build Arguments

Use build arguments for flexibility:

```dockerfile
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

ARG TOOL_VERSION=1.0.0
RUN pip install benchmark-tool==${TOOL_VERSION}
```

Then build with:
```bash
podman build --build-arg PYTHON_VERSION=3.12 -t tool:latest .
```

### Testing Custom Images

Before creating Tekton pipelines, test your image:

```bash
# Build
podman build -t benchmark-tool:test .

# Test execution
podman run --rm benchmark-tool:test --help

# Test against local endpoint
podman run --rm \
  -e MLFLOW_TRACKING_URI=http://localhost:5000 \
  benchmark-tool:test \
  --target http://model-server:8000 \
  --model test-model \
  --rate 10
```

### Registry and Versioning

#### Tagging Strategy

Use semantic versioning:
- `<tool>:latest` - Latest build (for development)
- `<tool>:v1.0.0` - Specific version (for production)
- `<tool>:v1.0.0-dev` - Development version

Example:
```bash
podman tag guidellm-custom:latest \
  image-registry.openshift-image-registry.svc:5000/llm-d-bench/guidellm-custom:v1.0.0
```

#### Pushing to Registry

```bash
podman push \
  image-registry.openshift-image-registry.svc:5000/llm-d-bench/guidellm-custom:v1.0.0
```

### Troubleshooting Image Builds

#### Build Fails

1. Check base image exists:
   ```bash
   podman pull <base-image>
   ```

2. Verify dependency syntax:
   ```bash
   pip install -r requirements.txt  # Test locally
   ```

3. Check for typos in Containerfile

#### Image Too Large

1. Check layer sizes:
   ```bash
   podman history <image>
   ```

2. Use dive for analysis:
   ```bash
   dive <image>
   ```

3. Optimize as described above

#### Runtime Errors

1. Test entrypoint:
   ```bash
   podman run --entrypoint /bin/sh -it <image>
   ```

2. Check environment variables:
   ```bash
   podman run --rm <image> env
   ```

---

## Adding New Benchmark Tools

This section covers the complete workflow for adding a new benchmark tool to llm-d-bench.

### Current Tools

- **guidellm/**: GuideLLM with MLflow integration wrapper (default)

### Adding a New Benchmark Tool

To add a new benchmark tool (e.g., "locust", "wrk2", or your in-house tool):

#### 1. Create Build Directory

Create `/build/<tool-name>/`:
```bash
mkdir -p build/locust
cd build/locust
```

Add the following files:
- **Containerfile** - Container build definition
- **Dependencies file** - requirements.txt, pyproject.toml, etc.
- **Tool wrapper** (optional) - Custom code to integrate with MLflow or process results

For detailed build instructions and best practices, see the [Building Custom Images](#building-custom-images) section above.

Example Containerfile:
```dockerfile
FROM python:3.11-slim

# Install benchmark tool
RUN pip install locust

# Copy wrapper scripts (if any)
COPY src/ /app/
WORKDIR /app

ENTRYPOINT ["python", "-m", "locust_wrapper"]
```

#### 2. Create Task Directory

Create `/tasks/benchmark/<tool-name>/`:
```bash
mkdir -p tasks/benchmark/locust
```

Create `run-benchmark.yaml` with standardized parameters:

**Required Parameters:**
- `IMAGE` - Benchmark tool container image
- `TARGET` - Inference endpoint URL
- `MODEL` - Model identifier
- `RATE` - Load specification
- `MAX_SECONDS` - Duration
- `MLFLOW_ENABLED` - Enable MLflow tracking
- `TAGS` - Array of tags

**Tool-specific Parameters:**
Add any tool-specific configuration parameters

Example task structure:
```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: run-locust-benchmark
spec:
  params:
    - name: IMAGE
    - name: TARGET
    - name: MODEL
    - name: RATE
    - name: MAX_SECONDS
    - name: MLFLOW_ENABLED
    - name: TAGS
    # Tool-specific params here
  steps:
    - name: run-benchmark
      image: $(params.IMAGE)
      script: |
        # Execute benchmark
        # Process results
        # Upload to MLflow (if enabled)
```

If you need a custom build task, create `buildah-build.yaml` following the pattern in `guidellm/buildah-build.yaml`.

#### 3. Create Pipelines

Create `/pipelines/benchmark/<tool-name>/`:
```bash
mkdir -p pipelines/benchmark/locust
```

Create two pipelines:

**build-image.yaml** - Build the benchmark tool image:
- Clones source repository
- Builds container image with buildah
- Pushes to registry

**run-benchmark.yaml** - Standalone benchmark execution:
- Waits for endpoint (optional)
- Runs benchmark task
- No deployment management

#### 4. Create Example PipelineRuns

Create `/pipelineruns/benchmark/<tool-name>/`:
```bash
mkdir -p pipelineruns/benchmark/locust
```

Create example pipelinerun files:
- `build-image-run.yaml` - Example build configuration
- `run-benchmark-example.yaml` - Example standalone benchmark run

#### 5. Update Deployment Mode Pipelines (Optional)

To use the new tool in deployment mode pipelines:

Edit pipelines in:
- `pipelines/deployment/llm-d/e2e-benchmark.yaml`
- `pipelines/deployment/rhoai/e2e-benchmark.yaml`
- `pipelines/deployment/rhaiis/e2e-benchmark.yaml`

Change the benchmark task reference:
```yaml
# OLD:
- name: run-guidellm-benchmark
  taskRef:
    name: run-guidellm-benchmark

# NEW:
- name: run-locust-benchmark
  taskRef:
    name: run-locust-benchmark
```

Update the `IMAGE` parameter to point to your tool's image.

#### 6. Installation

No changes needed to `scripts/install.sh` - it auto-discovers tasks and pipelines using `find`.

Just run:
```bash
./scripts/install.sh -n <namespace>
```

#### 7. Documentation

Update the main README.md:
- Add your tool to the "Benchmark Tools" section
- Document any tool-specific requirements or features

### Best Practices

1. **Standardize Parameters**: Use common parameter names (IMAGE, TARGET, MODEL, etc.) to maintain consistency
2. **MLflow Integration**: Support MLflow logging for result tracking and comparison
3. **Error Handling**: Gracefully handle failures and provide clear error messages
4. **Documentation**: Include clear usage examples in your pipelinerun files
5. **Versioning**: Use specific image tags, not `latest`, for reproducibility
6. **Cleanup**: Ensure your tool doesn't leave behind temporary files or resources

### Parameter Consistency

All benchmark tools should support these core parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| IMAGE | string | Benchmark tool container image |
| TARGET | string | Inference endpoint URL |
| MODEL | string | Model identifier |
| RATE | string | Load specification (format varies by tool) |
| MAX_SECONDS | string | Benchmark duration in seconds |
| MLFLOW_ENABLED | string | "true" or "false" |
| TAGS | array | Key=value tags for tracking |

Tool-specific parameters should be clearly documented and prefixed if possible (e.g., `LOCUST_SPAWN_RATE`).

### Example: Minimal Benchmark Tool

Here's a minimal example for adding a simple HTTP load testing tool:

```yaml
# tasks/benchmark/curl-bench/run-benchmark.yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: run-curl-benchmark
spec:
  params:
    - name: TARGET
    - name: MODEL
    - name: RATE
    - name: MAX_SECONDS
  steps:
    - name: benchmark
      image: curlimages/curl:latest
      script: |
        #!/bin/sh
        echo "Running curl benchmark against $(params.TARGET)"
        # Simple benchmark logic here
```

This minimal approach works for simple tools. For production use, add MLflow integration, proper result processing, and error handling.

### Reference Implementation

For a complete example, see:
- GuideLLM tasks: `/tasks/benchmark/guidellm/`
- GuideLLM pipelines: `/pipelines/benchmark/guidellm/`
- GuideLLM build files: `/build/guidellm/`

---

## Troubleshooting

### Common Issues

#### 1. Pipeline Stuck in Pending

**Symptom**: PipelineRun shows status `PipelineRunPending`

**Causes**:
- Missing workspace PVC
- Service account lacks permissions
- Resource limits exceeded

**Solution**:
```bash
# Check PVCs exist
oc get pvc -n downstream-llm-d

# Check service account
oc get sa deploy-model-sa -n downstream-llm-d

# Check node resources
oc describe nodes | grep -A 5 "Allocated resources"
```

#### 2. Download Task Fails

**Symptom**: `download-model` task fails with authentication error

**Causes**:
- Missing HuggingFace token
- Invalid token
- Model requires authentication

**Solution**:
```bash
# Verify secret exists
oc get secret huggingface-token -n downstream-llm-d

# Check token value
oc get secret huggingface-token -n downstream-llm-d -o jsonpath='{.data.HF_TOKEN}' | base64 -d

# Recreate with valid token
oc delete secret huggingface-token -n downstream-llm-d
oc create secret generic huggingface-token \
  --from-literal=HF_TOKEN=hf_xxxxxxxxxxxxx \
  -n downstream-llm-d
```

#### 3. Deployment Task Fails

**Symptom**: `deploy-model` fails with permission error

**Causes**:
- Service account lacks RBAC permissions
- Namespace mismatch

**Solution**:
```bash
# Check role binding
oc get rolebinding deploy-model-rolebinding -n downstream-llm-d -o yaml

# Verify service account has role
oc describe role deploy-model-role -n downstream-llm-d

# Re-apply RBAC
oc apply -f config/rbac/deploy-model-rbac.yaml -n downstream-llm-d
```

#### 4. Wait-for-Endpoint Times Out

**Symptom**: `wait-for-endpoint` exceeds timeout

**Causes**:
- Model too large for available GPUs
- vLLM configuration error
- Insufficient GPU memory

**Solution**:
```bash
# Check deployment logs
oc logs -l serving.kserve.io/inferenceservice=<deployment-name> -n downstream-llm-d

# Check pod events
oc get events -n downstream-llm-d --sort-by='.lastTimestamp'

# Adjust HEALTH_CHECK_TIMEOUT or vLLM args
```

#### 5. Benchmark Fails with TLS Error

**Symptom**: Benchmark fails with certificate verification error

**Cause**: Self-signed certificates in cluster

**Solution**:
Already handled by setting `verify: false` in backend args. If still fails:
```bash
# Check TARGET URL uses https://
# Ensure GUIDELLM__REQUEST_TIMEOUT is set (default: 6000)
```

#### 6. MLflow Artifacts Not Logged

**Symptom**: Run completes but no artifacts in MLflow

**Causes**:
- MLflow server unreachable
- S3 credentials invalid
- Benchmark output missing

**Solution**:
```bash
# Check MLflow connectivity
oc exec -it <benchmark-pod> -- curl -k $MLFLOW_TRACKING_URI/health

# Verify S3 secret
oc get secret mlflow-s3-secret -n downstream-llm-d -o yaml

# Check benchmark output exists
oc exec -it <benchmark-pod> -- ls -la /tmp/benchmark_sweep.json
```

### Debugging Tips

#### View Task Logs
```bash
# Get PipelineRun name
tkn pipelinerun list -n downstream-llm-d

# View specific task logs
tkn pipelinerun logs <pipelinerun-name> -t download-model -n downstream-llm-d
tkn pipelinerun logs <pipelinerun-name> -t deploy-model -n downstream-llm-d
tkn pipelinerun logs <pipelinerun-name> -t run-benchmark -n downstream-llm-d
```

#### Check Pod Status
```bash
# List pods for PipelineRun
oc get pods -l tekton.dev/pipelineRun=<pipelinerun-name> -n downstream-llm-d

# Describe pod for events
oc describe pod <pod-name> -n downstream-llm-d

# Get pod logs
oc logs <pod-name> -c step-run-benchmark -n downstream-llm-d
```

#### Inspect Resources
```bash
# Check LLMInferenceService status
oc get llminferenceservice -n downstream-llm-d
oc describe llminferenceservice <deployment-name> -n downstream-llm-d

# Check PVC usage
oc get pvc models-storage -n downstream-llm-d
oc describe pvc models-storage -n downstream-llm-d
```

#### Enable Debug Logging
```bash
# In PipelineRun, set:
params:
  - name: LOG_LEVEL
    value: "DEBUG"
```

---

## Additional Resources

- **Tekton Documentation**: https://tekton.dev/docs/
- **GuideLLM**: https://github.com/vllm/guidellm
- **MLflow**: https://mlflow.org/docs/latest/index.html
- **KServe**: https://kserve.github.io/website/
- **vLLM**: https://docs.vllm.ai/