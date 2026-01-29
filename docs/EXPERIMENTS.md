# Experiments Infrastructure Guide

This guide covers the optional experiments infrastructure for automated benchmarking, CI/CD integration, and multi-cluster management.

## Overview

llm-d-bench can be used standalone for manual benchmarking, but includes optional infrastructure for:

- **MLflow**: Centralized experiment tracking and model registry
- **GitHub Actions Runners**: Self-hosted runners for CI/CD automation
- **Kueue Multi-Cluster**: Federated queue management across clusters

This infrastructure is designed for teams running continuous benchmarking experiments and needing production-grade orchestration.

## When to Use This Infrastructure

**Use the experiments infra if you:**
- Run benchmarks automatically on code/model changes
- Need centralized tracking across multiple teams/clusters
- Want to compare experiments over time
- Require queue management for shared GPU resources
- Need CI/CD integration for benchmark pipelines

**Skip the experiments infra if you:**
- Only run manual, ad-hoc benchmarks
- Prefer local result storage (PVC mode)
- Have a single developer/cluster setup
- Don't need historical experiment comparison

## Components

### MLflow Stack

Centralized experiment tracking with:
- MLflow Tracking Server (experiment logging)
- PostgreSQL backend (metadata storage)
- S3/MinIO (artifact storage)
- Nginx reverse proxy (TLS termination)

**Deployment:**
```bash
# Review and customize secrets
cd infra/manifests/mlflow
vim mlflow-secrets.yaml

# Deploy stack
oc apply -k .
```

**Configuration:**
- Edit `mlflow-secrets.yaml` with database and S3 credentials
- Adjust resource limits in `mlflow-deployment.yaml`
- Configure ingress/route in `mlflow-route.yaml`

See [MLflow Integration Guide](MLFLOW.md) for benchmark integration.

### GitHub Actions Runners

Self-hosted runners for executing benchmark pipelines from GitHub Actions workflows.

**Features:**
- Auto-scaling based on job queue
- Isolated runner pods per job
- Pre-configured with `oc`, `tkn`, and cluster access
- Supports private repositories

**Deployment:**
```bash
cd infra/manifests/github-runners
vim runner-secrets.yaml  # Add GitHub token and repo URL

oc apply -k .
```

**GitHub Workflow Example:**
```yaml
name: Benchmark on PR
on: pull_request

jobs:
  benchmark:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v3
      - name: Run benchmark
        run: |
          oc create -f pipelineruns/rhoai/qwen-qwen3-06b-example.yaml -n llm-d-bench
          tkn pipelinerun logs -f -n llm-d-bench
```

**Configuration:**
- `GITHUB_TOKEN`: Personal Access Token with repo scope
- `GITHUB_REPO_URL`: Repository URL (e.g., `https://github.com/org/repo`)
- `RUNNER_LABELS`: Custom labels for runner targeting

### Kueue Multi-Cluster

Federated queue management for distributing workloads across clusters.

**Features:**
- GPU quota management per team/project
- Fair sharing with priority levels
- Preemption for high-priority jobs
- Multi-cluster job distribution

**Deployment:**
```bash
cd infra/manifests/kueue
oc apply -k .
```

**Configuration:**

1. **Define Resource Flavors** (GPU types):
   ```yaml
   apiVersion: kueue.x-k8s.io/v1beta1
   kind: ResourceFlavor
   metadata:
     name: nvidia-a100
   spec:
     nodeSelector:
       nvidia.com/gpu.product: NVIDIA-A100-SXM4-40GB
   ```

2. **Create Cluster Queue** (global quota):
   ```yaml
   apiVersion: kueue.x-k8s.io/v1beta1
   kind: ClusterQueue
   metadata:
     name: gpu-cluster-queue
   spec:
     resourceGroups:
     - flavors:
       - name: nvidia-a100
         resources:
         - name: nvidia.com/gpu
           nominalQuota: 8
   ```

3. **Setup Local Queue** (namespace-specific):
   ```yaml
   apiVersion: kueue.x-k8s.io/v1beta1
   kind: LocalQueue
   metadata:
     name: llm-d-bench-queue
     namespace: llm-d-bench
   spec:
     clusterQueue: gpu-cluster-queue
   ```

See [Kueue Documentation](KUEUE.md) for detailed configuration.

## Additional Infrastructure

### RHOAI Deployment Manifests

Pre-configured manifests for deploying Red Hat OpenShift AI:

```bash
cd infra/rhoai
oc apply -k .
```

Includes:
- DataScienceCluster configuration
- Serving runtime definitions
- Model serving examples

### Distributed Inference (RHCL)

Configurations for Compose-on-Kubernetes distributed inference:

```bash
cd infra/rhcl
oc apply -k .
```

Includes:
- Multi-node vLLM configurations
- Ray cluster setup for distributed serving
- GPU scheduling policies

## Full Installation

Deploy all infrastructure components:

```bash
# 1. Create secrets for all components
cd infra/manifests
cp mlflow/mlflow-secrets.example.yaml mlflow/mlflow-secrets.yaml
cp github-runners/runner-secrets.example.yaml github-runners/runner-secrets.yaml
cp kueue/kueue-config.example.yaml kueue/kueue-config.yaml

# Edit secrets with your credentials
vim mlflow/mlflow-secrets.yaml
vim github-runners/runner-secrets.yaml
vim kueue/kueue-config.yaml

# 2. Deploy infrastructure
cd infra/
oc apply -k .

# 3. Verify deployments
oc get pods -n mlflow-system
oc get pods -n github-runners
oc get pods -n kueue-system
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│  (Triggers benchmarks on PR/commit)                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  Self-Hosted Runners │
            │   (Execute oc/tkn)   │
            └──────────┬───────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenShift Cluster                          │
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Kueue     │───▶│   Tekton     │───▶│   Workload   │   │
│  │ (Queue Mgmt)│    │  (Pipelines) │    │  (Benchmark) │   │
│  └─────────────┘    └──────┬───────┘    └──────┬───────┘   │
│                             │                   │           │
│                             ▼                   ▼           │
│                      ┌─────────────────────────────┐        │
│                      │      MLflow Tracking        │        │
│                      │   (Logs metrics/artifacts)  │        │
│                      └─────────────┬───────────────┘        │
└────────────────────────────────────┼────────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │   S3 Storage    │
                            │   (Artifacts)   │
                            └─────────────────┘
```

## Troubleshooting

### MLflow Not Accessible

**Check service and route:**
```bash
oc get svc -n mlflow-system
oc get route mlflow -n mlflow-system
```

**Verify pod logs:**
```bash
oc logs deployment/mlflow-server -n mlflow-system
```

### GitHub Runners Not Registering

**Check runner logs:**
```bash
oc logs deployment/github-runner -n github-runners
```

**Verify token has correct scopes:**
- Token needs `repo` scope for private repos
- Organization runners need `admin:org` scope

**Re-register runners:**
```bash
oc delete pods -l app=github-runner -n github-runners
```

### Kueue Jobs Not Starting

**Check cluster queue status:**
```bash
oc get clusterqueue
oc describe clusterqueue gpu-cluster-queue
```

**Verify workload status:**
```bash
oc get workloads -n llm-d-bench
oc describe workload <name> -n llm-d-bench
```

**Common issues:**
- Insufficient quota: Increase `nominalQuota` in ClusterQueue
- Wrong flavor: Check `nodeSelector` matches available nodes
- Missing LocalQueue: Create LocalQueue in target namespace

## Best Practices

1. **Separate environments**: Use different clusters/namespaces for dev/staging/prod experiments
2. **Resource quotas**: Set appropriate GPU quotas per team to prevent hogging
3. **Retention policies**: Configure MLflow to archive old experiments
4. **Security**: Use RBAC to restrict access to runner tokens and MLflow credentials
5. **Monitoring**: Set up alerts for queue backlogs and failed pipelines
6. **Backup**: Regularly backup MLflow database and S3 artifacts

## References

- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [Kueue Documentation](https://kueue.sigs.k8s.io/)
- [GitHub Actions Self-Hosted Runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Tekton Pipelines](https://tekton.dev/docs/pipelines/)
