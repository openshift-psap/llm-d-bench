# Configuration Profiles

Configuration profiles for llm-d-bench. Engineers should understand Kubernetes ConfigMaps and Tekton parameters.

## Overview

### Design Principles

1. Single source of truth
2. Composable (mix vLLM + deployment + benchmark)
3. Version controlled
4. Declarative ConfigMaps

### Directory Structure

```
config/profiles/
├── vllm/                     # vLLM engine arguments
├── deployments/              # Platform-specific configs
│   ├── llm-d/
│   │   └── epp/             # EPP/GAIE scheduler configs
│   ├── rhoai/
│   └── rhaiis/
└── benchmarks/               # Benchmark workload configs
    ├── guidellm/
    └── mlperf/
```

## Quick Start

### Install Profiles

```bash
./scripts/install.sh -n llm-d-bench --with-pvcs
```

Or manually:
```bash
kubectl apply -k config/profiles/ -n llm-d-bench
```

### List Profiles

```bash
kubectl get cm -n llm-d-bench -l config-type=vllm
kubectl get cm -n llm-d-bench -l config-type=deployment
kubectl get cm -n llm-d-bench -l config-type=benchmark
kubectl get cm -n llm-d-bench -l config-type=scheduler
```

### Use in PipelineRun

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: my-benchmark-
spec:
  pipelineRef:
    name: llm-d-end-to-end-benchmark
  params:
    - name: MODEL_NAME
      value: "meta-llama/Llama-3.1-8B"
    - name: VLLM_CONFIG
      value: "vllm-standard"
    - name: DEPLOYMENT_CONFIG
      value: "deployment-llm-d-inference-scheduling"
    - name: BENCHMARK_CONFIG
      value: "guidellm-high-concurrency"
```

### Customizing vLLM

**Option 1: Create custom profile**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-my-custom
  namespace: llm-d-bench
  labels:
    config-type: vllm
data:
  VLLM_ARGS: |
    --max-model-len=16384
    --gpu-memory-utilization=0.90
```

**Option 2: Override in PipelineRun**

```yaml
params:
  - name: VLLM_CONFIG
    value: "vllm-standard"
  - name: VLLM_ARGS  # Overrides ConfigMap
    value:
      - "--max-model-len=16384"
```

### Common Arguments

| Argument | Values |
|----------|--------|
| `--max-model-len` | 4096, 8192, 16384, 131072 |
| `--gpu-memory-utilization` | 0.85-0.95 |
| `--enable-prefix-caching` | flag |
| `--quantization` | awq, gptq, fp8 |
| `--max-num-seqs` | 256, 512, 1024 |

## Benchmark Profiles

### Customizing GuideLLM

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: guidellm-custom
  namespace: llm-d-bench
  labels:
    config-type: benchmark
data:
  GUIDELLM_RATE: "10,50,100"
  GUIDELLM_DATA: "prompt_tokens=2000,output_tokens=500"
  GUIDELLM_MAX_SECONDS: "300"
```

## Managing Profiles

### Update Profile

```bash
vim config/profiles/vllm/vllm-standard.yaml
kubectl apply -f config/profiles/vllm/vllm-standard.yaml -n llm-d-bench
```

### Delete Profile

```bash
kubectl delete cm vllm-custom -n llm-d-bench
```

### View Profile

```bash
kubectl get cm vllm-standard -n llm-d-bench -o yaml
kubectl get cm vllm-standard -n llm-d-bench -o jsonpath='{.data.VLLM_ARGS}'
```

---

## Creating Custom Profiles

### Step-by-Step

1. Copy existing profile
```bash
cp config/profiles/vllm/vllm-standard.yaml config/profiles/vllm/vllm-custom.yaml
```

2. Edit metadata and data
```yaml
metadata:
  name: vllm-custom
  annotations:
    description: "Custom configuration"
data:
  VLLM_ARGS: |
    --max-model-len=16384
```

3. Add to kustomization
```yaml
# config/profiles/vllm/kustomization.yaml
resources:
  - vllm-standard.yaml
  - vllm-custom.yaml
```

4. Apply
```bash
kubectl apply -k config/profiles/ -n llm-d-bench
```

### Best Practices

1. Version profiles with labels: `config-version: "v1.2"`
2. Document changes in git commits
3. Create `-test` variants for experiments
4. Use annotations for discoverability
5. Follow naming conventions:
   - vLLM: `vllm-<purpose>`
   - Deployments: `deployment-<platform>-<mode>`
   - Benchmarks: `<tool>-<profile>`
   - Schedulers: `scheduler-<algorithm>`

---

## Troubleshooting

### Profile Not Found

```bash
kubectl get cm -n llm-d-bench -l config-type=vllm
kubectl apply -k config/profiles/ -n llm-d-bench
```

### Profile Changes Not Taking Effect

ConfigMaps are read at runtime. Start a new PipelineRun (don't rerun existing).

### Invalid Configuration

```bash
kubectl logs <vllm-pod> -n llm-d-bench | grep "unrecognized argument"
```

### EPP Scheduler Not Working

```bash
kubectl get cm scheduler-cache-aware -n llm-d-bench
kubectl logs <vllm-pod> -n llm-d-bench | grep "enable-prefix-caching"
kubectl get svc -n llm-d-bench | grep 5557  # For precise-cache
kubectl logs <gaie-pod> -n llm-d-bench | grep -i error
```