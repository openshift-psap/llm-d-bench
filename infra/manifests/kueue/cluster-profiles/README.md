# Kueue Cluster Profiles

Kueue manages GPU quota and workload admission for llm-d-bench.

## How It Works

Kueue acts as a gatekeeper - pods with the `kueue.x-k8s.io/queue-name` label are held in `SchedulingGated` state until GPU quota is available.

```

  ┌─────────────────────────────────────────────────────────────────┐
  │                         CLUSTER                                 │
  │                                                                 │
  │   ClusterQueue (gpu-cluster-queue)                              │
  │   ┌───────────────────────────────────────────────────────┐     │
  │   │  ResourceFlavor: h200-flavor                          │     │
  │   │    nodeLabels: nvidia.com/gpu.product=NVIDIA-H200     │     │
  │   │                                                       │     │
  │   │  Quota: 8 GPUs, 200 CPU, 1000Gi memory                │     │
  │   └───────────────────────────────────────────────────────┘     │
  │                             ▲                                   │
  │                             │                                   │
  │   Namespace: llm-d-bench    │                                   │
  │   ┌─────────────────────────┴─────────────────────────────┐     │
  │   │                                                       │     │
  │   │   LocalQueue: psap-benchmark                          │     │
  │   │         │                                             │     │
  │   │         ▼                                             │     │
  │   │   Pod (vLLM)                                          │     │
  │   │     labels:                                           │     │
  │   │       kueue.x-k8s.io/queue-name: psap-benchmark       │     │
  │   │     resources:                                        │     │
  │   │       nvidia.com/gpu: 4                               │     │
  │   │                                                       │     │
  │   └───────────────────────────────────────────────────────┘     │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

```

Admission flow:

```
  Pod Created           Kueue Intercepts          Quota Available?
  ┌──────────┐          ┌──────────────┐          ┌──────────────┐
  │   Pod    │─────────►│    Kueue     │─────────►│ ClusterQueue │
  │  (vLLM)  │          │  Controller  │          │    Check     │
  └──────────┘          └──────────────┘          └──────┬───────┘
                                                         │
                               ┌─────────────────────────┼─────────────────────────┐
                               │                         │                         │
                               ▼                         ▼                         │
                        SchedulingGated               Admitted                     │
                        (wait in queue)            (unsuspend pod)                 │
                               │                         │                         │
                               │                         ▼                         │
                               │                  K8s Scheduler ───► Pod Running   │
                               │                                                   │
                               └───────────────────────────────────────────────────┘
                                        (retry when quota frees up)
```

## Components

**ResourceFlavor** - Selects nodes by GPU type:

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata:
  name: h200-flavor
spec:
  nodeLabels:
    nvidia.com/gpu.product: NVIDIA-H200
```

**ClusterQueue** - Defines quota limits:

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: gpu-cluster-queue
spec:
  resourceGroups:
    - coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
      flavors:
        - name: h200-flavor
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 8
            - name: cpu
              nominalQuota: 200
            - name: memory
              nominalQuota: 1000Gi
```

**LocalQueue** - Namespace-scoped, points to ClusterQueue:

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: psap-benchmark
  namespace: llm-d-bench
spec:
  clusterQueue: gpu-cluster-queue
```

## Profiles

| File | GPUs | Accelerator |
|------|------|-------------|
| `A100-2gpu.yaml` | 2 | NVIDIA A100 |
| `H200-8gpu.yaml` | 8 | NVIDIA H200 |
| `MI300x-8gpu.yaml` | 8 | AMD MI300X |

## Setup

```bash
# Apply profile (requires cluster-admin)
oc apply -f H200-8gpu.yaml

# Verify
oc get resourceflavors
oc get clusterqueues
oc get localqueues -n llm-d-bench
```

## How Pods Get Queued

Pods need this label:

```yaml
metadata:
  labels:
    kueue.x-k8s.io/queue-name: psap-benchmark
```

In llm-d-bench, set `KUEUE_QUEUE_NAME` in your PipelineRun - the deploy task adds the label automatically.

## Checking Status

```bash
# Queue status
oc get clusterqueue gpu-cluster-queue -o yaml

# Pending workloads
oc get workloads -n llm-d-bench

# Pod states
oc get pods -n llm-d-bench
```

## Pod States

- `SchedulingGated` - Waiting in Kueue queue for GPU quota
- `Pending` - Admitted by Kueue, waiting for K8s scheduler
- `Running` - Running

The `wait-for-endpoint` task handles `SchedulingGated` by waiting indefinitely.
