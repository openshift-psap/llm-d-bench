# llm-d-bench

Tekton pipelines for running LLM inference benchmarks on OpenShift with multiple deployment modes and benchmark tools.

> [!WARNING]
> This repository is archived and it is not maintained. For the time being, it is deprecated in favor of [Benchflow](httpts://github.com/albertoperdomo2/benchflow).

## What is llm-d-bench?

llm-d-bench provides automated end-to-end benchmarking pipelines for LLM inference workloads. It supports:

- **Multiple deployment platforms**: llm-d, RHOAI (KServe), RHAIIS (Pods)
- **Benchmark tools**: GuideLLM (load testing), MLPerf (standardized)
- **Advanced features**: PD Disaggregation, Precise Prefix Caching, Inference Scheduling
- **MLflow integration**: Automated experiment tracking and metrics storage

## Quick Start

### Prerequisites

- OpenShift 4.14+
- Tekton Pipelines v0.50+
- `oc` CLI

### 1. Install

```bash
# Install Tekton Pipelines operator
oc apply -f https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml

# Create namespace
oc create namespace llm-d-bench

# Install pipelines and tasks
./scripts/install.sh -n llm-d-bench --with-pvcs

# Optional: Install Kueue for GPU quota management
# ./scripts/install.sh -n llm-d-bench --with-infra --with-pvcs
```

See [Storage Configuration](docs/STORAGE.md) for PVC setup details.

### 2. Create Secrets

```bash
# HuggingFace token (required)
oc create secret generic huggingface-token \
  --from-literal=HF_TOKEN=hf_xxxxxxxxxxxxx \
  -n llm-d-bench

# MLflow credentials (optional)
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

Or use templates from [config/cluster/secrets/](config/cluster/secrets/).

### 3. Run a Benchmark

```bash
# RHOAI example (KServe)
oc create -f pipelineruns/rhoai/qwen-qwen3-06b-example.yaml -n llm-d-bench

# llm-d example (Helmfile deployment)
oc create -f pipelineruns/llm-d/redhatai-llama-3.3-70b-instruct-fp8-dynamic-1k-1k.yaml -n llm-d-bench

# Watch logs
tkn pipelinerun logs -f -n llm-d-bench
```

More examples: [pipelineruns/llm-d/](pipelineruns/llm-d/), [pipelineruns/rhoai/](pipelineruns/rhoai/), [pipelineruns/rhaiis/](pipelineruns/rhaiis/)

## Deployment Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **llm-d** | Helmfile-based deployment with EPP/GAIE | Advanced scheduling, PD disaggregation, prefix caching |
| **RHOAI** | KServe LLMInferenceService | Production RHOAI environments (3.0+) |
| **RHAIIS** | Direct Pod deployment | Simple testing, development |

See [docs/ADVANCED.md](docs/ADVANCED.md) for detailed configuration.

## Benchmark Tools

Pre-built container images are available from GitHub Container Registry:

- **GuideLLM**: `ghcr.io/openshift-psap/llm-d-bench/guidellm:latest`
  - Load testing with configurable concurrency levels
  - Detailed latency and throughput metrics

- **MLPerf**: `ghcr.io/openshift-psap/llm-d-bench/mlperf:latest`
  - Standardized benchmark scenarios (Offline, Server)
  - Requires dataset upload to PVC

Images are automatically built via GitHub Actions when changes are merged to `main`. See [docs/ADVANCED.md#building-images-locally](docs/ADVANCED.md#building-images-locally) for local development.

## Results Storage

- **MLflow** (`MLFLOW_ENABLED=true`): Centralized tracking with S3 storage → [Setup Guide](docs/MLFLOW.md)
- **PVC** (`MLFLOW_ENABLED=false`): Local storage at `/benchmark-results/` (JSON, HTML, logs)
- **Tekton Results** (cluster-wide): Long-term PipelineRun/TaskRun storage with queryable API → [Setup Guide](docs/TEKTON.md)

## Documentation

- **[docs/ADVANCED.md](docs/ADVANCED.md)** - Detailed configuration, PD disaggregation, custom tasks, troubleshooting
- **[docs/STORAGE.md](docs/STORAGE.md)** - PVC configuration and access modes
- **[docs/MLFLOW.md](docs/MLFLOW.md)** - MLflow integration and experiment tracking
- **[docs/KUEUE.md](docs/KUEUE.md)** - GPU quota management with Kueue
- **[docs/TEKTON.md](docs/TEKTON.md)** - Tekton Dashboard and Tekton Results installation and S3 log storage
- **[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md)** - CI/CD integration and GitHub Runners

## Pipelines Overview

### End-to-End Pipelines

| Pipeline | Tasks |
|----------|-------|
| `llm-d-end-to-end-benchmark` | download → deploy-llm-d → wait → benchmark → cleanup |
| `rhoai-end-to-end-benchmark` | download → deploy-rhoai → wait → benchmark → cleanup |
| `rhaiis-end-to-end-benchmark` | download → deploy-rhaiis → wait → benchmark → cleanup |

### Benchmark-Only Pipelines

| Pipeline | Tasks |
|----------|-------|
| `guidellm-run-benchmark-pipeline` | wait-for-endpoint → run-benchmark |
| `mlperf-run-benchmark-pipeline` | wait-for-endpoint → run-benchmark |

## Common Commands

```bash
# View pipeline runs
oc get pipelinerun -n llm-d-bench

# View logs
tkn pipelinerun logs <pipelinerun-name> -f -n llm-d-bench

# View specific task logs
tkn pipelinerun logs <pipelinerun-name> -t run-benchmark -n llm-d-bench

# Check pod status
oc get pods -n llm-d-bench

# Describe failed pipeline
oc describe pipelinerun <pipelinerun-name> -n llm-d-bench
```

## Optional: Tekton CLI

**macOS:**
```bash
brew install tektoncd-cli
```

**Linux:**
```bash
curl -LO https://github.com/tektoncd/cli/releases/download/v0.38.0/tkn_0.38.0_Linux_x86_64.tar.gz
tar xvzf tkn_0.38.0_Linux_x86_64.tar.gz -C /usr/local/bin/ tkn
```

## Contributing

See [docs/ADVANCED.md](docs/ADVANCED.md) for information on:
- Creating custom tasks and pipelines
- Adding new benchmark tools
- Repository structure

## License

Apache 2.0
