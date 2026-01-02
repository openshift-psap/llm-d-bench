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
- [Troubleshooting](#troubleshooting)
- [Additional Resources](#additional-resources)

---

## Repository Structure

```
llm-d-bench/
├── build/            # Custom benchmark image source
│
├── config/           # Configuration resources
│   ├── rbac/         # Service accounts and roles
│   ├── secrets/      # Secret templates
│   └── workspaces/   # PVC definitions
│
├── docs/             # Documentation
│   └── ADVANCED.md   # This file
│
├── pipelineruns/     # Pipeline execution definitions
│   ├── downstream/   # Downstream (KServe) deployments
│   └── upstream/     # Upstream (Helmfile) deployments
│
├── pipelines/        # Pipeline definitions (orchestration)
│   ├── benchmark/    # Benchmark-only pipelines
│   ├── downstream/   # Full lifecycle (KServe)
│   └── upstream/                  # Full lifecycle (Helmfile)
│
├── scripts/          # Utility scripts
│   └── install.sh    # Installation automation
│
├── tasks/            # Task definitions (atomic operations)
│   ├── benchmark/    # Image building and benchmarking
│   ├── common/       # Shared tasks
│   ├── downstream/   # KServe deployment tasks
│   └── upstream/     # Helmfile deployment tasks
│
└── README.md         # Quick start guide
```

### Directory Purposes

- **`tasks/`**: Atomic, reusable operations (build, deploy, benchmark, cleanup)
- **`pipelines/`**: Orchestration of tasks into workflows
- **`pipelineruns/`**: Concrete executions with specific parameters
- **`build/`**: Custom container image with MLflow integration
- **`config/`**: Kubernetes resources (RBAC, secrets, PVCs)
- **`scripts/`**: Installation and utility automation

---

## Infrastructure Requirements

### Downstream Deployment (LLMInferenceService)

This repository supports **downstream llm-d deployment** using distributed inference through `LLMInferenceService` via RHOAI 3.0. However, infrastructure provisioning is **not yet fully automated** and may require manual adjustments.

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
- `download-model`: Downloads HuggingFace models to PVC
- `deploy-model`: Creates LLMInferenceService deployments
- `wait-for-endpoint`: Polls endpoint until ready
- `run-benchmark`: Executes GuideLLM benchmarks
- `cleanup-deployment`: Removes deployments

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
- `build-image`: Builds custom GuideLLM container
- `run-benchmark`: Standalone benchmark execution
- `full-benchmark-lifecycle`: Complete downstream workflow (download → deploy → benchmark → cleanup)
- `upstream-benchmark-lifecycle`: Complete upstream workflow (deploy Helmfile → benchmark → cleanup)

### PipelineRuns

A **PipelineRun** is a concrete execution of a pipeline with specific parameter values. It:
- References a pipeline
- Provides all required parameter values
- Binds workspaces to PVCs
- Can specify service accounts, timeouts, and cleanup policies

**PipelineRuns in this repo:**
- Located in `pipelineruns/downstream/` and `pipelineruns/upstream/`
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
   - `tasks/benchmark/` - Benchmarking operations
   - `tasks/common/` - Shared utilities
   - `tasks/downstream/` - KServe-specific
   - `tasks/upstream/` - Helmfile-specific

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

## Building Custom Images

### Image Build Pipeline

The `build-image` pipeline builds a custom container with MLflow integration:

```bash
# Trigger image build
oc create -f pipelineruns/build-image-run.yaml -n downstream-llm-d

# Watch build progress
tkn pipelinerun logs -f -n downstream-llm-d

# New image will be at:
# image-registry.openshift-image-registry.svc:5000/downstream-llm-d/guidellm-custom:latest
```

### Build Process

1. **git-clone**: Clones this repository
2. **buildah-build**: Builds container using `build/Containerfile`
3. **Push**: Pushes to OpenShift internal registry

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
oc get secret huggingface-token -n downstream-llm-d -o jsonpath='{.data.HF_CLI_TOKEN}' | base64 -d

# Recreate with valid token
oc delete secret huggingface-token -n downstream-llm-d
oc create secret generic huggingface-token \
  --from-literal=HF_CLI_TOKEN=hf_xxxxxxxxxxxxx \
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