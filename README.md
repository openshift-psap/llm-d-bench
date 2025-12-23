# llm-d-bench

Tekton pipelines for running llm-d inference benchmarks using GuideLLM.

> This might work with any other LLM endpoint but has only been tested with `llm-d` endpoints.

## Prerequisites

- Tekton Pipelines v0.50+
- OpenShift 4.14+
- `oc` CLI

## Quick Start

### 0. Set Namespace

```bash
export NAMESPACE=downstream-llm-d
```

### 1. Install Tekton Resources

```bash
./scripts/install.sh -n $NAMESPACE
```

### 2. Create Secrets

```bash
# HuggingFace token (required)
oc create secret generic huggingface-token \
  --from-literal=HF_CLI_TOKEN=hf_xxxxxxxxxxxxx \
  -n $NAMESPACE

# MLflow credentials (optional - only if using MLflow)
oc create secret generic mlflow-ui-auth \
  --from-literal=username=admin \
  --from-literal=password=your-password \
  -n $NAMESPACE

oc create secret generic mlflow-s3-secret \
  --from-literal=access-key=your-access-key \
  --from-literal=secret-key=your-secret-key \
  --from-literal=bucket-name=mlflow-artifacts \
  --from-literal=region=us-east-1 \
  -n $NAMESPACE
```

See [config/secrets/](config/secrets/) for YAML templates.

### 3. Build Custom Image

```bash
oc create -f pipelineruns/build-image-run.yaml -n $NAMESPACE
```

### 4. Run Benchmark

```bash
# Use a pre-configured experiment
oc create -f pipelineruns/meta-llama-3.1-8b-1k-1k.yaml -n $NAMESPACE

# Watch logs
tkn pipelinerun logs -f -n $NAMESPACE
```

## Pipelines

| Pipeline | Purpose | Tasks |
|----------|---------|-------|
| `build-image` | Build custom GuideLLM image | git-clone → buildah-build |
| `run-benchmark` | Run benchmark | wait-for-endpoint → run-benchmark |

## Custom Benchmarks

Copy an experiment and edit parameters:

```bash
cp pipelineruns/meta-llama-3.1-8b-1k-1k.yaml pipelineruns/my-benchmark.yaml
vi pipelineruns/my-benchmark.yaml  # Edit TARGET, MODEL, RATE, etc.
oc create -f pipelineruns/my-benchmark.yaml -n $NAMESPACE
```

Or use `tkn` CLI:

```bash
tkn pipeline start run-benchmark \
  -p TARGET=https://my-model.example.com \
  -p MODEL=meta-llama/Llama-3.1-8B \
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

## Troubleshooting

### Tekton Controllers Not Starting

<details>
<summary>Tekton pipeline pods fail to start with SCC violations</summary>

**Symptoms:**
- PipelineRuns remain in pending state indefinitely
- Tekton controller pods show status: `0/1`
- Events show: `unable to validate against any security context constraint`

**Solution:**

Grant the privileged SCC to Tekton service accounts:

```bash
oc create clusterrolebinding tekton-controller-privileged \
  --clusterrole=system:openshift:scc:privileged \
  --serviceaccount=tekton-pipelines:tekton-pipelines-controller

oc create clusterrolebinding tekton-webhook-privileged \
  --clusterrole=system:openshift:scc:privileged \
  --serviceaccount=tekton-pipelines:tekton-pipelines-webhook

oc create clusterrolebinding tekton-events-privileged \
  --clusterrole=system:openshift:scc:privileged \
  --serviceaccount=tekton-pipelines:tekton-events-controller

oc create clusterrolebinding tekton-resolvers-privileged \
  --clusterrole=system:openshift:scc:privileged \
  --serviceaccount=tekton-pipelines-resolvers:tekton-pipelines-remote-resolvers
```

Verify controllers are running:
```bash
oc get pods -n tekton-pipelines
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
oc policy add-role-to-user system:image-builder -z default -n $NAMESPACE
```

This allows the service account to push images to the internal OpenShift registry.

</details>
