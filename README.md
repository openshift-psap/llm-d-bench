# llm-d-bench

Tekton pipelines for running LLM inference benchmarks with multiple deployment modes and benchmark tools.

> **Note:** llm-d deployment mode (using the official llm-d repository with Helmfile) is experimental and may require additional manual configuration.

For advanced documentation see [docs/ADVANCED.md](docs/ADVANCED.md).

## Prerequisites

- Tekton Pipelines Operator v0.50+
- OpenShift 4.14+
- `oc` CLI
- OpenShift internal image registry (or external registry)

## Quick Start

### 1. Setup

```bash
# Create namespace
oc create namespace llm-d-bench

# Choose PVC mode (RWO for single-node, RWX for multi-pod)
cp config/workspaces/models-storage-pvc-rwo.yaml config/workspaces/models-storage-pvc.yaml

# Install Tekton Pipelines operator
oc apply -f https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml

# Install resources (tasks, pipelines, and PVCs)
./scripts/install.sh -n llm-d-bench --with-pvcs

# Optional: Install with Kueue for GPU quota management
# ./scripts/install.sh -n llm-d-bench --with-infra --with-pvcs
```

See [Storage Configuration](docs/STORAGE.md) for PVC access mode details.

> **Note**: The `--with-infra` flag installs Kueue for PipelineRun queue management and GPU quota enforcement. See [docs/KUEUE.md](docs/KUEUE.md) for details.

### 2. Create Secrets

```bash
# HuggingFace token (required)
oc create secret generic huggingface-token \
  --from-literal=HF_TOKEN=hf_xxxxxxxxxxxxx \
  -n llm-d-bench

# MLflow credentials (optional - only if using MLflow)
oc create secret generic mlflow-ui-auth \
  --from-literal=username=admin \
  --from-literal=password=your-password \
  --from-literal=tracking-uri=https://mlflow-server.example.com \
  -n llm-d-bench

oc create secret generic mlflow-s3-secret \
  --from-literal=access-key=your-access-key \
  --from-literal=secret-key=your-secret-key \
  --from-literal=bucket-name=mlflow-artifacts \
  --from-literal=region=us-east-1 \
  -n llm-d-bench
```

Or copy templates from [config/cluster/secrets/](config/cluster/secrets/) and apply them.

See [MLflow Integration](docs/MLFLOW.md) for detailed setup.

### 3. Setup Internal Image Registry (Optional)

```bash
./scripts/install.sh --setup-image-registry
```

See [docs/ADVANCED.md#image-registry-setup](docs/ADVANCED.md#image-registry-setup) for detailed documentation.

### 4. Build Benchmark Image

```bash
# GuideLLM (default)
oc create -f pipelineruns/benchmark/guidellm/build-image-run.yaml -n llm-d-bench

# Or MLPerf (requires dataset upload - see note below)
oc create -f pipelineruns/benchmark/mlperf/build-image-run.yaml -n llm-d-bench
```

> **Note:** For MLPerf benchmarks, datasets must be manually uploaded to the `models-storage` PVC at `/datasets/` before running. See [docs/ADVANCED.md](docs/ADVANCED.md#mlperf-benchmark-tool) for dataset upload instructions.

### 5. Run Benchmark

```bash
# RHOAI example
oc create -f pipelineruns/rhoai/qwen-qwen3-06b-example.yaml -n llm-d-bench

# llm-d example (end-to-end)
oc create -f pipelineruns/llm-d/meta-llama-3.1-8b-mlperf.yaml -n llm-d-bench

# PD Disaggregation example (large models 70B+)
oc create -f pipelineruns/llm-d/meta-llama-3.1-70b-pd-disaggregation.yaml -n llm-d-bench

# Watch logs
tkn pipelinerun logs -f -n llm-d-bench
```

More examples: [llm-d](pipelineruns/llm-d/), [rhoai](pipelineruns/rhoai/), [rhaiis](pipelineruns/rhaiis/)

## Pipelines

### Deployment Mode Pipelines

| Pipeline | Purpose | Tasks |
|----------|---------|-------|
| `llm-d-end-to-end-benchmark` | Full lifecycle with llm-d deployment (GuideLLM or MLPerf)<br/>Supports both inference-scheduling and pd-disaggregation modes | download → deploy-helmfile/deploy-pd-disaggregation → wait → benchmark → cleanup |
| `rhoai-end-to-end-benchmark` | Full lifecycle with RHOAI deployment (GuideLLM) | download → deploy-rhoai → wait → benchmark → cleanup |
| `rhaiis-end-to-end-benchmark` | Full lifecycle with RHAIIS Pod deployment (GuideLLM) | download → deploy-rhaiis → wait → benchmark → cleanup |

### Benchmark Pipelines

| Pipeline | Purpose | Tasks |
|----------|---------|-------|
| `guidellm-build-image` | Build custom GuideLLM image | git-clone → buildah-build |
| `guidellm-run-benchmark-pipeline` | Run benchmark only | wait-for-endpoint → run-benchmark |
| `mlperf-build-image` | Build custom MLPerf image | git-clone → buildah-build |
| `mlperf-run-benchmark-pipeline` | Run MLPerf benchmark only | wait-for-endpoint → run-benchmark |

## Benchmark Tools

llm-d-bench supports two benchmark tools:

- **GuideLLM** (default): Load testing with concurrency control and detailed metrics
- **MLPerf**: Standardized benchmark with Offline, Server, and other scenarios
  - **Requires manual dataset upload**: MLPerf datasets must be uploaded to the `models-storage` PVC before running benchmarks

To switch between tools, use different benchmark images and pipelines. See [Adding Benchmark Tools](docs/ADVANCED.md#adding-benchmark-tools) for details.

## Usage

### Running Benchmarks

**Use existing examples:**
```bash
# Choose deployment mode: rhoai, llm-d, or rhaiis
oc create -f pipelineruns/{mode}/{model-example}.yaml -n llm-d-bench
```

**Custom parameters:**
```bash
# Copy and edit an example
cp pipelineruns/rhoai/qwen-qwen3-06b-example.yaml pipelineruns/rhoai/my-benchmark.yaml
vim pipelineruns/rhoai/my-benchmark.yaml  # Edit TARGET, MODEL, RATE, etc.
oc create -f pipelineruns/rhoai/my-benchmark.yaml -n llm-d-bench
```

**Or use tkn CLI for standalone benchmark:**
```bash
tkn pipeline start guidellm-run-benchmark-pipeline \
  -p TARGET=https://my-model.example.com \
  -p MODEL=Qwen/Qwen3-0.6B \
  -p GUIDELLM_RATE="1,50,100" \
  -n llm-d-bench \
  --showlog
```

See [pipelineruns/](pipelineruns/) for all examples.

### Results Storage

- **MLflow** (`MLFLOW_ENABLED=true`): Results logged to MLflow tracking server → [Setup Guide](docs/MLFLOW.md)
- **PVC** (`MLFLOW_ENABLED=false`): Results saved to `/benchmark-results/` on PVC (JSON, HTML reports, console logs)

### Debugging

```bash
# View logs
tkn pipelinerun logs <pipelinerun-name> -f -n llm-d-bench

# View specific task
tkn pipelinerun logs <pipelinerun-name> -t run-benchmark -n llm-d-bench

# Check status
oc get pipelinerun -n llm-d-bench
oc describe pipelinerun <pipelinerun-name> -n llm-d-bench

# Pod logs
oc logs <pod-name> -c step-run-benchmark -n llm-d-bench
```

## Optional Components

### Tekton CLI (Recommended)

**macOS:**
```bash
brew install tektoncd-cli
```

**Linux:**
```bash
curl -LO https://github.com/tektoncd/cli/releases/download/v0.38.0/tkn_0.38.0_Linux_x86_64.tar.gz
tar xvzf tkn_0.38.0_Linux_x86_64.tar.gz -C /usr/local/bin/ tkn
```

**Verify:**
```bash
tkn version
```

### Tekton Dashboard

> [!WARNING]
> Tekton Dashboard is not secured by default (anyone with the URL can access it). Consider securing with OAuth for production use.

```bash
# Install the Dashboard
oc apply -f https://storage.googleapis.com/tekton-releases/dashboard/latest/release.yaml

# Expose the service
oc expose svc tekton-dashboard -n tekton-pipelines
```

### Experiments Infrastructure

Optional MLflow, GitHub Runners, and Kueue multi-cluster setup for CI/CD integration and automated experiment tracking.

See [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) for detailed deployment instructions.

## Troubleshooting

### Tekton Controllers Not Starting

<details>
<summary>Tekton pipeline pods fail to start with SCC violations</summary>

**Symptoms:**
- PipelineRuns remain in pending state indefinitely
- Tekton controller pods show status: `0/1` or `Deployment` shows `ReplicaFailure`
- Events show: `unable to validate against any security context constraint: provider "anyuid": Forbidden: not usable by user or serviceaccount`
- Error message: `provider restricted-v2: .containers[0].runAsUser: Invalid value: 65532: must be in the ranges`

**Solution:**

Grant the `anyuid` SCC to Tekton service accounts:

```bash
oc adm policy add-scc-to-user anyuid -z tekton-pipelines-controller -n tekton-pipelines
oc adm policy add-scc-to-user anyuid -z tekton-pipelines-webhook -n tekton-pipelines
oc adm policy add-scc-to-user anyuid -z tekton-events-controller -n tekton-pipelines
```

If deployments don't automatically restart, trigger a rollout:

```bash
oc rollout restart deployment/tekton-pipelines-controller -n tekton-pipelines
oc rollout restart deployment/tekton-pipelines-webhook -n tekton-pipelines
oc rollout restart deployment/tekton-events-controller -n tekton-pipelines
```

Verify controllers are running:
```bash
oc get pods -n tekton-pipelines
```

All pods should show `1/1 Running` status.

**If `anyuid` SCC doesn't work:**

In some cases, pods may still fail with errors like:
```
pod.metadata.annotations[container.seccomp.security.alpha.kubernetes.io/...]: Forbidden: seccomp may not be set
```

This happens because Tekton deployments include `seccompProfile.type: RuntimeDefault` in their securityContext, and the `anyuid` SCC doesn't allow seccomp profiles (`Allowed Seccomp Profiles: <none>`).

Use the `privileged` SCC instead:

```bash
oc adm policy add-scc-to-user privileged system:serviceaccount:tekton-pipelines:tekton-pipelines-controller
oc adm policy add-scc-to-user privileged system:serviceaccount:tekton-pipelines:tekton-pipelines-webhook
oc adm policy add-scc-to-user privileged system:serviceaccount:tekton-pipelines:tekton-events-controller
```

Then restart the deployments:

```bash
oc rollout restart deployment tekton-pipelines-controller tekton-pipelines-webhook tekton-events-controller -n tekton-pipelines
```

</details>

### Image Build Push Failures

<details>
<summary>Buildah task fails with "authentication required" when pushing to internal registry</summary>

**Symptoms:**
- Build completes successfully
- Push fails with: `authentication required`
- Error: `writing blob: initiating layer upload to /v2/.../blobs/uploads/`

**Solution:**

Grant the `system:image-builder` role to the service account:

```bash
oc policy add-role-to-user system:image-builder -z default -n llm-d-bench
```

This allows the service account to push images to the internal OpenShift registry.

</details>

For more troubleshooting scenarios, see [docs/ADVANCED.md#troubleshooting](docs/ADVANCED.md#troubleshooting)
