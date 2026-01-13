# llm-d-bench

Tekton pipelines for running LLM inference benchmarks with multiple deployment modes and benchmark tools.

> **Note:** llm-d deployment mode (using the official llm-d repository with Helmfile) is experimental and may require additional manual configuration.

For advanced documentation see [docs/ADVANCED.md](docs/ADVANCED.md).

## Prerequisites

- Tekton Pipelines Operator v0.50+
- OpenShift 4.14+
- `oc` CLI

## Quick Start

### Install Tekton Pipelines

```bash
# Install latest Tekton Pipelines operator
oc apply -f https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml

# Verify installation
oc get pods -n tekton-pipelines
```

### 0. Create and Set Namespace

```bash
export NAMESPACE=llm-d-bench
oc create namespace $NAMESPACE
```

### 1. Install Tekton Resources

```bash
./scripts/install.sh -n $NAMESPACE
```

### 2. Create Secrets

You can create the necessary secrets manually:

```bash
# HuggingFace token (required)
oc create secret generic huggingface-token \
  --from-literal=HF_TOKEN=hf_xxxxxxxxxxxxx \
  -n $NAMESPACE

# MLflow credentials (optional - only if using MLflow)
oc create secret generic mlflow-ui-auth \
  --from-literal=username=admin \
  --from-literal=password=your-password \
  --from-literal=tracking-uri=https://mlflow-server.example.com \
  -n $NAMESPACE

oc create secret generic mlflow-s3-secret \
  --from-literal=access-key=your-access-key \
  --from-literal=secret-key=your-secret-key \
  --from-literal=bucket-name=mlflow-artifacts \
  --from-literal=region=us-east-1 \
  -n $NAMESPACE
```

or you can create your secret file by copying the templates present in the `config/secrets/` dir and removing the .example, so the install script will apply them.

See [config/secrets/](config/secrets/) for YAML templates.

### 3. Build Custom Image

```bash
oc create -f pipelineruns/benchmark/guidellm/build-image-run.yaml -n $NAMESPACE
```

### 4. Run Benchmark

```bash
# Use a pre-configured experiment (RHOAI mode example)
oc create -f pipelineruns/rhoai/qwen-qwen3-06b-example.yaml -n $NAMESPACE

# Watch logs
tkn pipelinerun logs -f -n $NAMESPACE
```

### Install Tekton CLI (Recommended)

**macOS:**
```bash
brew install tektoncd-cli
```

**Linux:**
```bash
# Download latest release
curl -LO https://github.com/tektoncd/cli/releases/download/v0.38.0/tkn_0.38.0_Linux_x86_64.tar.gz
tar xvzf tkn_0.38.0_Linux_x86_64.tar.gz -C /usr/local/bin/ tkn
```

**Verify:**
```bash
tkn version
```

### Install Tekton Dashboard (Recommended)
> [!WARNING]
> Tekton Dashboard is not secured by default i.e. anyone with the URL can access it. Users might want to secure the dashboard with OAuth.

```bash
# Install the Dashboard
oc apply -f https://storage.googleapis.com/tekton-releases/dashboard/latest/release.yaml

# Expose the service
oc expose svc tekton-dashboard -n tekton-pipelines
```

### Install Experiments Infra (Recommended)

> [!NOTE]
> llm-d-bench can be used without deploying this infra, but it is advised for CI/CD integration and experiment tracking, among others.

The deployment of the experiments infrastructure is completely optional and it is inteded to be a persistent environment for automated benchmarking. The infrastructure is composed by MLFlow, Self Hosted GitHub Action Runners and Kueue with MultiCluster capabilities.

In order to deploy it, create the necessary secrets within `infra/manifests/{mlflow,github-runners,kueue}` and then simply run `oc apply -k .` from the `infra/` dir.

Other manifests for deploying RHOAI and configuring Distributed Inference can be found inside `infra/{rhoai,rhcl}` too.

The repo architecture is designed for extensibility. To add new benchmark tools, see [docs/ADVANCED.md](docs/ADVANCED.md#adding-new-benchmark-tools).

## Pipelines

### Deployment Mode Pipelines

| Pipeline | Purpose | Tasks |
|----------|---------|-------|
| `llm-d-end-to-end-benchmark` | Full lifecycle with llm-d deployment | download → deploy-helmfile → wait → benchmark → cleanup |
| `rhoai-end-to-end-benchmark` | Full lifecycle with RHOAI deployment | download → deploy-rhoai → wait → benchmark → cleanup |
| `rhaiis-end-to-end-benchmark` | Full lifecycle with RHAIIS Pod deployment | download → deploy-rhaiis → wait → benchmark → cleanup |

### Benchmark Pipelines

| Pipeline | Purpose | Tasks |
|----------|---------|-------|
| `guidellm-build-image` | Build custom GuideLLM image | git-clone → buildah-build |
| `guidellm-run-benchmark-pipeline` | Run benchmark only | wait-for-endpoint → run-benchmark |

## Custom Benchmarks

Copy an experiment and edit parameters:

```bash
# Choose a deployment mode (rhoai, llm-d, or rhaiis)
cp pipelineruns/rhoai/qwen-qwen3-06b-example.yaml pipelineruns/rhoai/my-benchmark.yaml
vim pipelineruns/rhoai/my-benchmark.yaml  # Edit TARGET, MODEL, RATE, etc.
oc create -f pipelineruns/rhoai/my-benchmark.yaml -n $NAMESPACE
```

Or use `tkn` CLI for standalone benchmark (no deployment):

```bash
tkn pipeline start guidellm-run-benchmark-pipeline \
  -p TARGET=https://my-model.example.com \
  -p MODEL=Qwen/Qwen3-0.6B \
  -p RATE="1,50,100" \
  -n $NAMESPACE \
  --showlog
```

## Storage Modes

**MLflow** (set `MLFLOW_ENABLED=true`):
- Results logged to MLflow tracking server
- Requires: `mlflow-ui-auth` and `mlflow-s3-secret` secrets

**PVC** (set `MLFLOW_ENABLED=false`):
- Results saved to PVC at `/benchmark-results/`
- Files: `benchmark_output.json`, `benchmark_output_console.log` and HTML reports.

## Debugging

```bash
# View logs
tkn pipelinerun logs <pipelinerun-name> -f -n $NAMESPACE

# View specific task
tkn pipelinerun logs <pipelinerun-name> -t run-benchmark -n $NAMESPACE

# Check status
oc get pipelinerun -n $NAMESPACE
oc describe pipelinerun <pipelinerun-name> -n $NAMESPACE

# Pod logs
oc logs <pod-name> -c step-run-benchmark -n $NAMESPACE
```

## Custom Comparison Report

When using MLFlow, a comparison report will be logged as an artifact. That report is a general one that contains comparison data for a fixed set of versions. In order to get a custom report that contains also results from other MLFlow runs, users can manually execute the script in plot only mode.

Users need to set the MLFlow environment variables needed to rightfully access the runs. To be precise: `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_USERNAME` and `MLFLOW_TRACKING_INSECURE_TLS` set to true. Also, AWS CLI or AWS env variables must be configured too.


```
cd build/src/

python3 -m benchmark.main --plot-only \
  --mlflow-run-ids "abc123,cde456" \
  --versions "foo,bar" \
  --mlflow-tracking-uri https://your-mlflow.tracking.uri

```

This will download the benchmark JSON file for each run to `/tmp`, process them and generate a comparison plot report.


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
oc policy add-role-to-user system:image-builder -z default -n $NAMESPACE
```

This allows the service account to push images to the internal OpenShift registry.

</details>
