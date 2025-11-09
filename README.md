# llm-d-bench

Automated [llm-d](https://llm-d.ai/) inference benchmarking on OpenShift with MLflow tracking and GitHub Actions integration, by using [GuideLLM](https://github.com/vllm-project/guidellm).

> This might work with any other LLM endpoint but has only been tested with `llm-d` endpoints.

## Components

This repository contains two main components:

### 1. [llm-d-deploy/](./llm-d-deploy/README.md) - Deployment Automation

### 2. [llm-d-bench/](./llm-d-bench) - Benchmarking Suite

Benchmark Helm chart for running GuideLLM load tests against llm-d deployments with MLflow tracking.

## Quick Setup

This project uses the following: 

  - [Reflector](https://github.com/emberstack/kubernetes-reflector) - Secret and ConfigMap mirroring across namespaces
  - [Kueue](https://github.com/kubernetes-sigs/kueue) - For job batching

### 1. Deploy Infrastructure

> [!NOTE]
> AWS IAM Policy is handled by the user, see [`mlflow/AWS_IAM_POLICY.md`](mlflow/AWS_IAM_POLICY.md) for more.

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials

# Deploy MLflow, PostgreSQL, and GitHub runners
./bootstrap.sh

# Dry run
./bootstrap.sh --dry-run
```

This deploys:
- **MLflow** - Experiment tracking with PostgreSQL backend and S3 storage
- **Self-hosted GitHub runners** - Run benchmarks via PR comments
- **Custom benchmark image** - Built and pushed to OpenShift registry
- All needed addons/operators (Kueue, Reflector).

### 2. Run Benchmarks

**Via GitHub Actions (recommended):**
```
# Comment on any PR:
/benchmark qwen-0.6b-baseline

# With parameter overrides:
/benchmark qwen-0.6b-baseline
benchmark.maxSeconds=600
```

> [!WARNING]  
> This repo does not handle llm-d deployment, so you need to make sure which model is running to make sure the benchmark succeeds.

**Via Helm:**
```bash
helm install <your_deployment_name> ./llm-d-bench \
  -f llm-d-bench/experiments/qwen-0.6b-baseline.yaml \
  -n <your_namespace>
```

## Adding Benchmarks

See [`llm-d-bench/ADDING_BENCHMARKS.md`](llm-d-bench/ADDING_BENCHMARKS.md) for adding new benchmark tools.

**Quick summary:**
1. Add benchmark implementation to `llm-d-bench/templates/benchmarks/<tool-name>/`
2. Create experiment config in `llm-d-bench/experiments/`
3. Trigger via `/benchmark <experiment-name>` in PR comments

For new experiments, add them in `llm-d-bench/experiments`.

> [!NOTE]
> Experiment names cannot include `.` for security reasons.

## GitHub Action Workflow

The benchmark workflow (`.github/workflows/benchmark.yaml`) triggers on PR comments:

**How it works:**
1. User comments `/benchmark <experiment>` on a PR
2. Self-hosted runner picks up the job
3. Checks out PR branch
4. Runs Helm install with experiment config
5. Waits for job completion (up to 12 hours)
6. Reacts with 🚀 on success or 😕 on failure

**Requirements:**
- Self-hosted runner with label `openshift`
- GitHub environment named `benchmark`
- OpenShift secrets: `OPENSHIFT_SERVER_URL`, `OPENSHIFT_CA_CERT`, `OPENSHIFT_TOKEN`
- Only repository owner can trigger benchmarks

## Configuration

### Environment Variables (.env)

**MLflow:**
```bash
POSTGRES_PASSWORD=your-password
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
S3_BUCKET_NAME=your-bucket
AWS_REGION=us-east-1
MLFLOW_ADMIN_PASSWORD=your-password
```

**GitHub Runners:**
```bash
GITHUB_TOKEN=ghp_your_token
GITHUB_OWNER=your-org-or-username
GITHUB_REPOSITORY=                    # Empty for org-wide runners
RUNNER_LABELS=openshift,self-hosted
RUNNER_REPLICAS=2
```

### Benchmark Parameters

Key parameters in `llm-d-bench/values.yaml`:
- `benchmark.target` - Target inference endpoint
- `benchmark.model` - Model name
- `benchmark.rate` - Concurrent request rates (e.g., `{1,50,100}`)
- `benchmark.data` - Number of requests or token specs
- `benchmark.maxSeconds` - Max runtime (default: 600s)
- `mlflow.enabled` - Enable MLflow tracking
- `kueue.enabled` - Enable Kueue queues

## Results

- **MLflow** - Experiments tracked if `mlflow.enabled=True`

Access MLflow UI:
```bash
oc get route mlflow -n mlflow -o jsonpath='{.spec.host}'
# Login with credentials from .env
```
