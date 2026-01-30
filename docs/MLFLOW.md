# MLflow Integration Guide

This guide covers MLflow setup, configuration, and usage for experiment tracking with llm-d-bench.

## Overview

MLflow provides centralized experiment tracking, artifact storage, and model comparison capabilities. When enabled, benchmark results are automatically logged to your MLflow tracking server.

## Prerequisites

- MLflow tracking server (deployed separately)
- S3-compatible object storage for artifacts
- Network access from benchmark pods to MLflow server

## Setup

### 1. Create Secrets

llm-d-bench requires two secrets for MLflow integration:

#### MLflow Authentication Secret

```bash
oc create secret generic mlflow-ui-auth \
  --from-literal=username=admin \
  --from-literal=password=your-secure-password \
  --from-literal=tracking-uri=https://mlflow-server.example.com \
  -n llm-d-bench
```

**Fields:**
- `username`: MLflow basic auth username
- `password`: MLflow basic auth password
- `tracking-uri`: Full URL to MLflow tracking server (include protocol)

#### S3 Artifact Storage Secret

```bash
oc create secret generic mlflow-s3-secret \
  --from-literal=access-key=your-s3-access-key \
  --from-literal=secret-key=your-s3-secret-key \
  --from-literal=bucket-name=mlflow-artifacts \
  --from-literal=region=us-east-1 \
  -n llm-d-bench
```

**Fields:**
- `access-key`: S3/MinIO access key
- `secret-key`: S3/MinIO secret key
- `bucket-name`: S3 bucket for storing artifacts
- `region`: AWS region (or `us-east-1` for MinIO)

### 2. Using Secret Templates

Alternatively, create secrets from YAML templates:

```bash
# Copy templates
cp config/cluster/secrets/mlflow-auth.example.yaml config/cluster/secrets/mlflow-auth.yaml
cp config/cluster/secrets/mlflow-s3-creds.example.yaml config/cluster/secrets/mlflow-s3-creds.yaml

# Edit with your credentials
vim config/cluster/secrets/mlflow-auth.yaml
vim config/cluster/secrets/mlflow-s3-creds.yaml

# Remove .example suffix and install script will apply them
./scripts/install.sh -n llm-d-bench
```

Templates are located in: [config/cluster/secrets/](../config/cluster/secrets/)

## Enabling MLflow in Benchmarks

Set `MLFLOW_ENABLED=true` in your PipelineRun:

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  name: my-benchmark
spec:
  pipelineRef:
    name: rhoai-end-to-end-benchmark
  params:
    - name: MODEL
      value: Qwen/Qwen3-0.6B
    - name: MLFLOW_ENABLED
      value: "true"
    - name: MLFLOW_EXPERIMENT_NAME
      value: "rhoai-benchmarks"
```

## What Gets Logged

When MLflow is enabled, the following data is logged:

### Metrics
- Throughput (tokens/sec, requests/sec)
- Latency percentiles (p50, p90, p95, p99)
- Time to First Token (TTFT)
- Inter-Token Latency (ITL)
- Request success/failure rates

### Parameters
- Model name and version
- Deployment mode (rhoai, llm-d, rhaiis)
- Benchmark tool (GuideLLM, MLPerf)
- Request rates and concurrency levels
- GPU configuration

### Artifacts
- `benchmark_output.json`: Raw benchmark results
- `benchmark_comparison.html`: Visual comparison report
- `benchmark_output_console.log`: Console output
- Configuration files

### Tags
- `deployment_mode`: rhoai/llm-d/rhaiis
- `model`: Model identifier
- `benchmark_tool`: guidellm/mlperf
- `gpu_type`: GPU SKU if available

## Custom Comparison Reports

Generate comparison reports across multiple MLflow runs:

### Prerequisites

```bash
# Set MLflow environment variables
export MLFLOW_TRACKING_URI=https://mlflow-server.example.com
export MLFLOW_TRACKING_USERNAME=admin
export MLFLOW_TRACKING_PASSWORD=your-password
export MLFLOW_TRACKING_INSECURE_TLS=true  # if using self-signed certs

# Configure AWS credentials (for S3 artifact access)
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
```

### Generate Report

```bash
cd build/guidellm/src/

python3 -m benchmark.main --plot-only \
  --mlflow-run-ids "abc123def456,ghi789jkl012" \
  --versions "baseline,optimized" \
  --mlflow-tracking-uri https://mlflow-server.example.com
```

**Parameters:**
- `--plot-only`: Skip benchmark execution, only generate plots
- `--mlflow-run-ids`: Comma-separated list of MLflow run IDs to compare
- `--versions`: Human-readable labels for each run (same order as run IDs)
- `--mlflow-tracking-uri`: MLflow server URL (can also use env var)

**Output:**
- Downloads benchmark JSON files from each run to `/tmp/`
- Generates `comparison_report.html` with side-by-side metrics
- Creates charts comparing throughput, latency, and TTFT across runs

### Finding Run IDs

```bash
# List recent runs in an experiment
curl -X POST "https://mlflow-server.example.com/api/2.0/mlflow/runs/search" \
  -H "Content-Type: application/json" \
  -u admin:password \
  -d '{"experiment_ids": ["1"], "max_results": 10}'

# Or use MLflow UI
# Navigate to your experiment and copy run IDs from the table
```

## Troubleshooting

### Connection Errors

**Symptoms:**
- Benchmark completes but no data in MLflow
- Errors: `Connection refused` or `Name or service not known`

**Solutions:**

1. **Verify tracking URI is accessible from cluster:**
   ```bash
   oc run -it --rm debug --image=curlimages/curl --restart=Never -- \
     curl -v https://mlflow-server.example.com/health
   ```

2. **Check secret values:**
   ```bash
   oc get secret mlflow-ui-auth -n llm-d-bench -o jsonpath='{.data.tracking-uri}' | base64 -d
   ```

3. **Verify DNS resolution:**
   ```bash
   oc run -it --rm debug --image=busybox --restart=Never -- \
     nslookup mlflow-server.example.com
   ```

### Authentication Failures

**Symptoms:**
- HTTP 401 Unauthorized errors
- MLflow logs show authentication failures

**Solutions:**

1. **Verify credentials:**
   ```bash
   oc get secret mlflow-ui-auth -n llm-d-bench -o jsonpath='{.data.username}' | base64 -d
   ```

2. **Test authentication manually:**
   ```bash
   curl -u admin:password https://mlflow-server.example.com/api/2.0/mlflow/experiments/list
   ```

### S3 Upload Failures

**Symptoms:**
- Metrics logged but artifacts missing
- Errors: `Access Denied` or `NoSuchBucket`

**Solutions:**

1. **Verify S3 credentials:**
   ```bash
   oc get secret mlflow-s3-secret -n llm-d-bench -o jsonpath='{.data.access-key}' | base64 -d
   ```

2. **Check bucket exists and is accessible:**
   ```bash
   aws s3 ls s3://mlflow-artifacts/ --endpoint-url https://your-s3-endpoint
   ```

3. **Verify bucket permissions:**
   - Ensure access key has `s3:PutObject` and `s3:GetObject` permissions
   - Check bucket policy allows writes from MLflow server

### Missing Comparison Reports

**Symptoms:**
- Benchmark completes and logs to MLflow
- Comparison HTML report not generated

**Cause:**
- Comparison report generation may fail silently if dependencies are missing

**Solution:**

Run comparison manually (see [Custom Comparison Reports](#custom-comparison-reports) above).

## Best Practices

1. **Use experiment names** to organize benchmarks by project/model family
2. **Tag runs consistently** for easier filtering and comparison
3. **Clean up old runs** periodically to reduce storage costs
4. **Backup artifacts** if using ephemeral S3 storage
5. **Use TLS** for production MLflow servers (set `MLFLOW_TRACKING_INSECURE_TLS=false`)

## Deploying MLflow (Optional)

llm-d-bench includes optional MLflow deployment manifests:

```bash
# Review and customize secrets
vim infra/manifests/mlflow/*.yaml

# Deploy MLflow stack
oc apply -k infra/manifests/mlflow/
```

See [infra/manifests/mlflow/README.md](../infra/manifests/mlflow/README.md) for details.
