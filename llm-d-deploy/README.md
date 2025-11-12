# llm-d-deploy

Templated Helmfile deployment for llm-d with automatic configuration based on model and parallelism settings.

## Prerequisites

- OpenShift 4.14+
- GPU nodes with NVIDIA GPU Operator
- [Helmfile](https://helmfile.readthedocs.io/) installed
- Gateway API provider (Istio recommended)
- HuggingFace token secret (Already available if provisioned with [bootstrap.sh](../bootstrap.sh))
- Red Hat OpenShift AI Operator

## Install

**1. Create namespace and secret:**
```bash
oc create namespace <your namespace>
oc create secret generic llm-d-hf-token \
  --from-literal=HF_TOKEN=your_token -n <your namespace>
```

**2. Deploy with preset or custom config:**
```bash
# Preset environment
helmfile apply -e qwen-0.6b -n <your namespace>

# Custom configuration
helmfile apply -n <your namespace> \
  --state-values-set model.name=meta-llama/Llama-3.1-8B-Instruct \
  --state-values-set model.tensorParallel=2 \
  --state-values-set decode.replicas=4
```

## Upgrade

Re-run `helmfile apply` with updated parameters:
```bash
helmfile apply -e llama-8b -n <your namespace> \
  --state-values-set model.size=50Gi
```

## Uninstall

```bash
helmfile destroy -n <your namespace>
```

## Preset Environments

| Environment | Model | TP | Replicas | Total GPUs |
|------------|-------|----|---------:|----------:|
| `qwen-0.6b` | Qwen/Qwen3-0.6B | 1 | 1 | 1 |
| `llama-3.3b-70b-instruct-fp8-dynamic` | RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic | 4 | 1 | 4 |
| `llama-4-maverick-17b-128e-instruct-fp8` | RedHatAI/Llama-4-Maverick-17B-128E-Instruct-FP8 | 8 | 1 | 8 |
| `qwen3-235b-a22b-fp8-dynamic` | RedHatAI/Qwen3-235B-A22B-FP8-dynamic | 4 | 1 | 4 |
| `gpt-oss-120b` | openai/gpt-oss-120b | 1 | 1 | 1 |
| `default` | Qwen/Qwen3-0.6B | 1 | 2 | 2 |

## Configuration Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `model.name` | HuggingFace model name | `Qwen/Qwen3-0.6B` |
| `model.uri` | Model URI | `hf://<model.name>` |
| `model.size` | PVC size | `20Gi` |
| `model.tensorParallel` | Tensor parallelism | `1` |
| `decode.replicas` | Decode replicas | `2` |
| `prefill.replicas` | Prefill replicas (0=disabled) | `0` |
| `gateway.className` | Gateway class | `istio` |

Helmfile automatically:
1. Sets `CUDA_VISIBLE_DEVICES` based on TP (e.g., `"0,1,2,3"` for TP=4)
2. Sets GPU resources (`nvidia.com/gpu: <TP>`)
3. Switches to P/D scheduler when `prefill.replicas > 0`
4. Validates chart versions and dependencies

## Limitations

- **No prefill configuration**: Prefill TP and resources are not templated (only `prefill.replicas` is supported)
- **Fixed chart versions**: Chart versions are hardcoded in helmfile.yaml.gotmpl:82-103
- **No multi-model support**: Single model per deployment
- **Gateway class only**: Only `gateway.className` is configurable, other gateway settings require editing base.yaml
