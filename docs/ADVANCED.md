# Advanced Guide

Quick reference for advanced topics. Engineers should already know Tekton/Kubernetes basics.

## Table of Contents

- [Repository Structure](#repository-structure)
- [PD Disaggregation](#pd-disaggregation)
- [Parameter Inheritance](#parameter-inheritance)
- [Model Name Sanitization](#model-name-sanitization)
- [Custom EPP/GAIE Configurations](#custom-eppgaie-configurations)
- [Creating Custom Tasks](#creating-custom-tasks)
- [Creating Custom Pipelines](#creating-custom-pipelines)
- [MLflow Integration](#mlflow-integration)
- [Image Registry Setup](#image-registry-setup)
- [Building Custom Images](#building-custom-images)
- [Adding Benchmark Tools](#adding-benchmark-tools)
- [Troubleshooting](#troubleshooting)

---

## Repository Structure

```
llm-d-bench/
├── build/                    # Custom benchmark image source
├── config/                   # Configuration resources
│   ├── cluster/              # RBAC, secrets, PVCs
│   └── profiles/             # Workload configuration profiles
├── pipelineruns/             # Pipeline execution definitions
├── pipelines/                # Pipeline definitions (orchestration)
├── tasks/                    # Task definitions (atomic operations)
└── scripts/                  # install.sh
```

---

## PD Disaggregation

Prefill/Decode disaggregation separates inference phases into specialized worker pools for 70B+ models.

### Requirements

- **Minimum 8 GPUs** total
- **RDMA networking** (recommended)
- **llm-d 0.4+**
- Large models (70B+), long sequences (10k+ tokens)

### Worker Configuration

**Total GPUs = (PREFILL_REPLICAS × PREFILL_TP) + (DECODE_REPLICAS × DECODE_TP)**

```yaml
# 8 GPU configuration
DEPLOYMENT_MODE: "pd-disaggregation"
PREFILL_REPLICAS: "4"
PREFILL_TP: "1"
DECODE_REPLICAS: "1"
DECODE_TP: "4"
PD_THRESHOLD: "0"          # Always disaggregate
HASH_BLOCK_SIZE: "5"
ENABLE_RDMA: "true"
```

### Example

See `pipelineruns/llm-d/redhatai-llama-3.3-70b-instruct-fp8-dynamic-pd-disagg.yaml`

### Verification

```bash
kubectl get pods -n llm-d-bench -l llm-d.ai/inferenceServing=true
kubectl get inferencepool -n llm-d-bench gaie-$RELEASE_NAME
```

### Troubleshooting

**Workers not starting**: Check GPU availability
```bash
kubectl describe nodes | grep -A 5 "nvidia.com/gpu"
```

**KV cache transfer failures**: Verify RDMA
```bash
kubectl logs ms-<release>-prefill-0 -n llm-d-bench | grep -i "nixl\|rdma"
```

---

## Custom EPP/GAIE Configurations

Predefined EPP profiles for intelligent inference scheduling.

### Available Profiles

| Profile | Description | Requirements |
|---------|-------------|--------------|
| `default` | Standard load-aware | None |
| `precise-cache` | KV-events precise caching | ZMQ port 5557, prefix caching |
| `cache-aware` | Approximate cache awareness | Prefix caching |
| `custom` | User-provided config | Advanced use |

### Usage

```yaml
params:
  - name: EPP_PROFILE
    value: "precise-cache"
  - name: VLLM_ARGS
    value:
      - "--enable-prefix-caching"
```

### Custom Configuration

```yaml
params:
  - name: EPP_PROFILE
    value: "custom"
  - name: EPP_CUSTOM_CONFIG
    value: |
      apiVersion: inference.networking.x-k8s.io/v1alpha1
      kind: EndpointPickerConfig
      plugins:
        - type: prefix-cache-scorer
          parameters:
            autoTune: true
```

### Verification

```bash
kubectl logs -l inferencepool=gaie-<release>-epp -n llm-d-bench
kubectl get svc -n llm-d-bench | grep 5557  # For precise-cache
```

---

## Parameter Inheritance

Parameters flow: **Task → Pipeline → PipelineRun**

```
Task:        GUIDELLM_MAX_SECONDS = "600"  (default)
Pipeline:    GUIDELLM_MAX_SECONDS = "600"  (override)
PipelineRun: GUIDELLM_MAX_SECONDS = "1200" (final value)
```

Only specify parameters that differ from defaults.

---

## Model Name Sanitization

Kubernetes deployment names are auto-sanitized:

```bash
DEPLOYMENT_NAME=$(echo "$MODEL_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/\//-/g' | sed 's/\.//g' | sed 's/-$//' | cut -c1-42)
```

---

## Creating Custom Tasks

### Template

```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: my-custom-task
spec:
  params:
    - name: INPUT_PARAM
      type: string
      default: "default-value"

  steps:
    - name: main-step
      image: registry.access.redhat.com/ubi9/ubi:latest
      script: |
        #!/bin/bash
        set -e
        echo "Input: $(params.INPUT_PARAM)"
```

### Best Practices

- Use descriptive parameter names
- Provide defaults when sensible
- Use `set -e` for fail-fast
- Log progress for debugging
- Handle idempotency

---

## Creating Custom Pipelines

### Template

```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: my-custom-pipeline
spec:
  params:
    - name: MODEL_NAME
      type: string

  workspaces:
    - name: shared-workspace

  tasks:
    - name: task-1
      taskRef:
        name: first-task
      params:
        - name: INPUT
          value: $(params.MODEL_NAME)

    - name: task-2
      runAfter:
        - task-1
      taskRef:
        name: second-task
```

### Patterns

**Conditional Execution:**
```yaml
when:
  - input: "$(params.SKIP_ME)"
    operator: in
    values: ["false"]
```

**Array Parameters:**
```yaml
params:
  - name: VLLM_ARGS
    value: $(params.VLLM_ARGS[*])
```

---

## MLflow Integration

### Auto-Logged Parameters

- `target`, `model`, `backend_type`, `rate_type`
- `prompt_tokens`, `output_tokens`
- `tp`, `accelerator`

### Metrics (per concurrency level)

**Throughput:** `throughput_requests_per_sec`, `total_tokens_per_second`
**Latency:** `latency_p50_sec`, `latency_p95_sec`, `latency_p99_sec`
**TTFT:** `ttft_mean_ms`, `ttft_p95_ms`, `ttft_p99_ms`
**ITL:** `itl_mean_ms`, `itl_p95_ms`
**TPOT:** `tpot_mean_ms`, `tpot_p95_ms`

### Custom Tags

```yaml
params:
  - name: MLFLOW_TAGS
    value:
      - "llm-d-version=RHOAI-3.0"
      - "environment=production"
```

### Artifacts

- `results/benchmark_sweep.json`
- `logs/benchmark_sweep_console.log`
- `reports/*.html`

---

## Image Registry Setup

Enable OpenShift internal registry:

```bash
./scripts/install.sh --setup-image-registry
```

Registry endpoint: `image-registry.openshift-image-registry.svc:5000`

For RWO storage (single-node), replicas automatically set to 1.

---

## Building Custom Images

### Directory Structure

```
build/
├── guidellm/              # GuideLLM with MLflow
│   ├── Containerfile
│   └── src/
└── mlperf/                # MLPerf wrapper
    ├── Containerfile
    └── src/
```

### Build via Pipeline

```bash
oc create -f pipelineruns/benchmark/guidellm/build-image-run.yaml -n llm-d-bench
tkn pipelinerun logs -f -n llm-d-bench
```

Image: `image-registry.openshift-image-registry.svc:5000/llm-d-bench/guidellm-custom:latest`

### Best Practices

1. Use specific base image versions (not `latest`)
2. Multi-stage builds for smaller images
3. Pin dependency versions
4. Layer caching: copy dependencies before code

---

## MLPerf Benchmark Tool

### Dataset Requirements

MLPerf benchmarks require datasets to be manually uploaded to the `models-storage` PVC before running benchmarks. The pipeline does not download datasets automatically.

**Dataset location:** `/datasets/` on the `models-storage` PVC

### Uploading Datasets

1. **Create a debug pod with PVC mounted:**
   ```bash
   cat <<EOF | oc apply -f -
   apiVersion: v1
   kind: Pod
   metadata:
     name: dataset-upload
     namespace: llm-d-bench
   spec:
     containers:
     - name: uploader
       image: registry.access.redhat.com/ubi9/ubi:latest
       command: ["/bin/bash", "-c", "sleep infinity"]
       volumeMounts:
       - name: models-storage
         mountPath: /mnt/models
     volumes:
     - name: models-storage
       persistentVolumeClaim:
         claimName: models-storage
   EOF
   ```

2. **Upload datasets:**
   ```bash
   # Copy datasets to the pod
   oc cp /local/path/to/datasets dataset-upload:/mnt/models/datasets -n llm-d-bench

   # Verify upload
   oc exec dataset-upload -n llm-d-bench -- ls -lh /mnt/models/datasets
   ```

3. **Clean up:**
   ```bash
   oc delete pod dataset-upload -n llm-d-bench
   ```

### Running MLPerf Benchmarks

```bash
# Build MLPerf image (if not already built)
oc create -f pipelineruns/benchmark/mlperf/build-image-run.yaml -n llm-d-bench

# Run MLPerf benchmark
oc create -f pipelineruns/llm-d/meta-llama-3.1-8b-mlperf.yaml -n llm-d-bench
```

---

## Adding Benchmark Tools

### Quick Guide

1. **Create build directory**: `build/<tool-name>/`
   - Containerfile
   - Dependencies (requirements.txt or pyproject.toml)
   - Optional wrapper code in `src/`

2. **Create task**: `tasks/benchmark/<tool-name>/run-benchmark.yaml`
   - Use prefixed parameters (e.g., `LOCUST_RATE`)

3. **Create pipelines**: `pipelines/benchmark/<tool-name>/`
   - `build-image.yaml`
   - `run-benchmark.yaml`

4. **Create examples**: `pipelineruns/benchmark/<tool-name>/`

5. **Install**: `./scripts/install.sh` (auto-discovers new files)

### Standard Parameters

All tools must support:
- `IMAGE`, `TARGET`, `MODEL`
- `MLFLOW_ENABLED`, `TAGS`

Tool-specific parameters use prefixes:
- GuideLLM: `GUIDELLM_*`
- MLPerf: `MLPERF_*`
- Custom: `TOOLNAME_*`

---

## Troubleshooting

### Pipeline Stuck in Pending

```bash
oc get pvc -n llm-d-bench
oc get sa deploy-model-sa -n llm-d-bench
oc describe nodes | grep -A 5 "Allocated resources"
```

### Download Task Fails

```bash
oc get secret huggingface-token -n llm-d-bench
oc get secret huggingface-token -n llm-d-bench -o jsonpath='{.data.HF_TOKEN}' | base64 -d
```

### Deployment Task Fails

```bash
oc get rolebinding deploy-model-rolebinding -n llm-d-bench
oc describe role deploy-model-role -n llm-d-bench
```

### Wait-for-Endpoint Times Out

```bash
oc logs -l serving.kserve.io/inferenceservice=<deployment> -n llm-d-bench
oc get events -n llm-d-bench --sort-by='.lastTimestamp'
```

### HTTPRoute Backend Not Recognized (llm-d)

**Symptoms:**
- llm-d deployment completes successfully
- HTTPRoute is created and shows no errors
- Gateway is running
- Requests to the inference endpoint return 404 or timeout
- InferencePool pods are running but receive no traffic

**Cause:**

Some versions of the Gateway API or cluster configurations expect the `x-k8s.io` experimental API group for InferencePool backends instead of the standard `k8s.io` group.

**Solution:**

Patch the HTTPRoute to use the experimental API group:

```bash
NAMESPACE=llm-d-bench
RELEASE_NAME=your-release-name

oc patch httproute llm-d-$RELEASE_NAME -n $NAMESPACE --type='json' -p='[
  {"op": "replace", "path": "/spec/rules/0/backendRefs/0/group", "value": "inference.networking.x-k8s.io"}
]'
```

**Verify:**

```bash
# Check the HTTPRoute configuration
oc get httproute llm-d-$RELEASE_NAME -n $NAMESPACE -o yaml | grep -A5 backendRefs

# Test the endpoint
curl -s http://infra-$RELEASE_NAME-inference-gateway-istio.$NAMESPACE.svc.cluster.local/v1/models
```

### MLflow Artifacts Not Logged

```bash
oc exec -it <benchmark-pod> -- curl -k $MLFLOW_TRACKING_URI/health
oc get secret mlflow-s3-secret -n llm-d-bench
```

### Debugging Tips

```bash
# View task logs
tkn pipelinerun logs <run> -t <task> -n llm-d-bench

# Check pod status
oc get pods -l tekton.dev/pipelineRun=<run> -n llm-d-bench
oc describe pod <pod> -n llm-d-bench

# Inspect resources
oc get llminferenceservice -n llm-d-bench
oc describe pvc models-storage -n llm-d-bench
```

---

## Additional Resources

- [Tekton Documentation](https://tekton.dev/docs/)
- [GuideLLM](https://github.com/vllm/guidellm)
- [MLflow](https://mlflow.org/docs/latest/index.html)
- [vLLM](https://docs.vllm.ai/)
