# Kueue Integration for PipelineRun Management

Kueue manages GPU resource allocation, priority scheduling, and quota enforcement for Tekton PipelineRuns.

## Benefits

- **GPU Quota Management**: Prevent cluster overload
- **Multi-User Coordination**: Fair resource allocation
- **Priority Scheduling**: Production before experimental workloads
- **Queue Visibility**: Monitor queue depth and wait times

## Architecture

```
PipelineRun with Kueue labels
    ↓
TaskRun Pods inherit labels
    ↓
Kueue admission webhook intercepts Pod
    ↓
Enforces quotas and queuing
    ↓
Pod admitted when resources available
```

## Configuration

### Resource Quotas

**Primary**: GPU quotas (most critical)

```
Nominal Quota: 16 GPUs
Borrowing Limit: 8 GPUs
Total Max: 24 GPUs
```

CPU/Memory quotas available but disabled by default.

### Priority Classes

| Priority Class | Value | Queue Name |
|----------------|-------|------------|
| `psap-releases` | 1000 | `psap-releases-queue` |
| `psap-research` | 100 | `psap-research-queue` |

Default: All PipelineRuns use `psap-releases`

### Queue Ordering

**Current**: `StrictFIFO` (submission order)
**Alternative**: `BestEffortFIFO` (priority-based)

## Submitting PipelineRuns

### Standard PipelineRun

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: my-benchmark-
spec:
  pipelineRef:
    name: llm-d-end-to-end-benchmark

  taskRunTemplate:
    serviceAccountName: deploy-model-sa
    podTemplate:
      labels:
        kueue.x-k8s.io/queue-name: psap-releases-queue
        kueue.x-k8s.io/priority-class: psap-releases

  params:
    - name: MODEL_NAME
      value: "meta-llama/Llama-3.1-8B"
```

### Changing Priority

```yaml
podTemplate:
  labels:
    kueue.x-k8s.io/queue-name: psap-research-queue
    kueue.x-k8s.io/priority-class: psap-research
```

## Monitoring

### CLI Commands

```bash
# List workloads
kubectl get workloads -n llm-d-bench

# Workload details
kubectl describe workload <name> -n llm-d-bench

# ClusterQueue status (quota usage)
kubectl get clusterqueue benchmark-cluster-queue -o yaml

# Admitted workloads (running)
kubectl get workloads -n llm-d-bench --field-selector status.admission!=null

# Pending workloads (queued)
kubectl get workloads -n llm-d-bench -o json | \
  jq '.items[] | select(.status.conditions[0].type == "QuotaReserved" and .status.conditions[0].status == "False") | .metadata.name'
```

### Workload Status

- **Admitted**: Running
- **Pending**: Waiting for resources
- **Finished**: Completed
- **Evicted**: Removed from queue

## Cluster-Specific Resource Flavors

### Available Flavors

| Flavor | GPUs/Node | Node Label |
|--------|-----------|------------|
| `h200-cluster` | 8 | `nvidia.com/gpu.product: NVIDIA-H200` |
| `h100-dgx-cluster` | 4 | `nvidia.com/gpu.product: NVIDIA-H100` |
| `gpu-generic` | - | `nvidia.com/gpu: "true"` |

### Selecting Flavor

Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml`:

```yaml
spec:
  resourceGroups:
    - coveredResources: ["nvidia.com/gpu"]
      flavors:
        - name: h200-cluster
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 16  # Adjust: num_nodes × 8
              borrowingLimit: 8
```

Apply:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

## Priority-Based Queuing

Enable `BestEffortFIFO` in `cluster-queue.yaml`:

```yaml
spec:
  queueingStrategy: BestEffortFIFO
```

**Behavior**: Higher priority workloads admitted first across queues.

## Troubleshooting

### PipelineRun Not Starting

```bash
# Check workload exists
kubectl get workloads -n llm-d-bench

# Kueue running
oc get pods -n kueue-system

# Workload status
kubectl describe workload <name> -n llm-d-bench
```

### Workload Stuck in Queue

```bash
# Check quota usage
kubectl get clusterqueue benchmark-cluster-queue -o yaml

# Check GPU availability
kubectl describe nodes | grep -A 10 "Allocatable:"

# List GPU-using pods
kubectl get pods -A -o json | \
  jq '.items[] | select(.spec.containers[].resources.limits."nvidia.com/gpu") | {name: .metadata.name, gpus: .spec.containers[].resources.limits."nvidia.com/gpu"}'
```

**Solutions**:
1. Wait for workloads to complete
2. Cancel lower-priority workloads
3. Increase quota if cluster capacity allows

### Workload Evicted

```bash
kubectl get events -n llm-d-bench --sort-by='.lastTimestamp'
```

**Common causes**:
- Timeout
- Resource mismatch
- Preemption (if enabled)

## Advanced Configuration

### Enable CPU/Memory Quotas

Uncomment in `cluster-queue.yaml`:

```yaml
- coveredResources: ["cpu", "memory"]
  flavors:
    - name: "default-flavor"
      resources:
        - name: "cpu"
          nominalQuota: 100
        - name: "memory"
          nominalQuota: 500Gi
```

### Enable Preemption

```yaml
spec:
  preemption:
    withinClusterQueue: LowerPriority
    reclaimWithinCohort: Any
    borrowWithinCohort:
      policy: LowerPriority
      maxPriorityThreshold: 500
```

### Enable Fair Sharing

```yaml
spec:
  fairSharing:
    enable: true
    weight: 1
```

## References

- [Kueue Documentation](https://kueue.sigs.k8s.io/)
- [Kueue GitHub](https://github.com/kubernetes-sigs/kueue)
- [Tekton Pipelines](https://tekton.dev/)
