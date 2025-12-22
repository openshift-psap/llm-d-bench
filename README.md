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
| `build-and-benchmark` | Build + benchmark | git-clone → buildah-build → wait-for-endpoint → run-benchmark |

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
