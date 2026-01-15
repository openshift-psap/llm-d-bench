# Kueue Integration for PipelineRun Management

## Overview

This project integrates [Kueue](https://kueue.sigs.k8s.io/) to manage Tekton PipelineRuns for fair GPU resource allocation, priority scheduling, and quota enforcement in a single-cluster environment with multiple users.

### Key Benefits

- **GPU Quota Management**: Prevent cluster overload by enforcing GPU resource quotas
- **Multi-User Coordination**: Fair resource allocation when multiple users submit PipelineRuns
- **Priority Scheduling**: Ensure production workloads run before experimental workloads (optional)
- **Queue Visibility**: Monitor workload queue depth and wait times
- **Fair Sharing**: Equitable GPU allocation across users and teams

### Architecture

Kueue integrates with Tekton Pipelines by managing the Pods created by TaskRuns:

```
User submits PipelineRun
    ↓
PipelineRun has Kueue labels in taskRunTemplate.podTemplate
    ↓
Tekton creates TaskRun Pods with inherited labels
    ↓
Kueue admission webhook intercepts Pod creation
    ↓
Kueue enforces quotas and queuing
    ↓
Pod admitted when resources available
```

**Integration Method**: Tekton TaskRun pod templates with Kueue labels (direct pod-level queuing)

## Configuration

### Resource Quotas

**Primary Resource**: GPU quotas (most critical/expensive resource)

**Current Configuration**:
- **Nominal Quota**: 16 GPUs
- **Borrowing Limit**: 8 additional GPUs (can borrow when available)
- **Total Max**: 24 GPUs (16 + 8 borrowing)

**CPU/Memory**: Quotas available but disabled by default (see [Advanced Configuration](#advanced-configuration))

### Priority Classes

Two priority levels are defined:

| Priority Class | Value | Description | Queue Name |
|----------------|-------|-------------|------------|
| `psap-releases` | 1000 | Release benchmarks and production workloads | `psap-releases-queue` |
| `psap-research` | 100 | Research experiments and testing | `psap-research-queue` |

**Default**: All current PipelineRuns are marked as `psap-releases`

### Queue Ordering

**Current Strategy**: `StrictFIFO`
- Workloads processed in order of submission
- No priority-based preemption

**Alternative**: `BestEffortFIFO` (see [Switching to Priority-Based Queuing](#switching-to-priority-based-queuing))

## Submitting PipelineRuns

### Standard PipelineRun with Kueue Labels

All PipelineRuns include Kueue labels in the `taskRunTemplate.podTemplate.labels` section:

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: my-benchmark-
  labels:
    app: llm-d-bench
    experiment: my-experiment
spec:
  pipelineRef:
    name: llm-d-end-to-end-benchmark

  taskRunTemplate:
    serviceAccountName: deploy-model-sa
    podTemplate:
      labels:
        # Kueue integration for GPU quota management
        kueue.x-k8s.io/queue-name: psap-releases-queue
        kueue.x-k8s.io/priority-class: psap-releases

  params:
    - name: MODEL_NAME
      value: "meta-llama/Llama-3.1-8B"
    # ... other parameters
```

### Changing Priority

To submit a research experiment with lower priority:

```yaml
  taskRunTemplate:
    serviceAccountName: deploy-model-sa
    podTemplate:
      labels:
        kueue.x-k8s.io/queue-name: psap-research-queue
        kueue.x-k8s.io/priority-class: psap-research
```

### Submitting the PipelineRun

```bash
# Create the PipelineRun
oc create -f pipelineruns/llm-d/my-benchmark.yaml -n llm-d-bench

# Check if it was admitted or queued
kubectl get workloads -n llm-d-bench
```

## Monitoring and Observability

### CLI Commands

**List all workloads in the queue**:
```bash
kubectl get workloads -n llm-d-bench
```

**View workload details**:
```bash
kubectl describe workload <workload-name> -n llm-d-bench
```

**Check ClusterQueue status** (see quota usage):
```bash
kubectl get clusterqueue benchmark-cluster-queue -o yaml
```

**View LocalQueue status**:
```bash
kubectl get localqueue -n llm-d-bench
```

**Check admitted workloads** (running):
```bash
kubectl get workloads -n llm-d-bench --field-selector status.admission!=null
```

**Check pending workloads** (queued):
```bash
kubectl get workloads -n llm-d-bench -o json | jq '.items[] | select(.status.conditions[0].type == "QuotaReserved" and .status.conditions[0].status == "False") | .metadata.name'
```

### Understanding Workload Status

A workload can be in several states:

- **Admitted**: Resources allocated, PipelineRun is running
- **Pending**: Waiting for resources due to quota limits
- **Finished**: PipelineRun completed successfully
- **Evicted**: Removed from queue (rare, usually due to timeout)

**Example Output**:
```bash
$ kubectl get workloads -n llm-d-bench
NAME                              QUEUE                   ADMITTED   AGE
qwen-06b-example-abc123          psap-releases-queue     True       5m
llama-8b-benchmark-def456        psap-releases-queue     False      2m
meta-llama-31-8b-ghi789          psap-research-queue     True       10m
```

In this example:
- `qwen-06b-example-abc123` is running (ADMITTED=True)
- `llama-8b-benchmark-def456` is queued, waiting for GPUs (ADMITTED=False)
- `meta-llama-31-8b-ghi789` is running with lower priority

## Cluster-Specific Resource Flavors

### Available Flavors

Three ResourceFlavors are available to match different cluster configurations:

| Flavor Name | Description | Node Label |
|-------------|-------------|------------|
| `h200-cluster` | H200 cluster (8x H200 GPUs per node) | `nvidia.com/gpu.product: NVIDIA-H200` |
| `h100-dgx-cluster` | H100 DGX (4x H100 GPUs per node) | `nvidia.com/gpu.product: NVIDIA-H100` |
| `gpu-generic` | Generic GPU fallback | `nvidia.com/gpu: "true"` |

### Selecting a Flavor

**Current Default**: The ClusterQueue uses `default-flavor` for GPU resources.

**To switch to a cluster-specific flavor** (e.g., H200):

1. Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml`:

```yaml
spec:
  resourceGroups:
    - coveredResources: ["nvidia.com/gpu"]
      flavors:
        - name: h200-cluster  # Changed from default-flavor
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 16  # Adjust based on cluster size
              borrowingLimit: 8
```

2. Adjust `nominalQuota` based on your cluster:
   - **H200 cluster** (8 GPUs/node): `nominalQuota = num_nodes × 8`
   - **H100 DGX** (4 GPUs/node): `nominalQuota = num_nodes × 4`

3. Apply the changes:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

## Switching to Priority-Based Queuing

By default, workloads are processed in FIFO order. To enable priority-based scheduling:

### Enable BestEffortFIFO

1. Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml`:

```yaml
spec:
  queueingStrategy: BestEffortFIFO  # Changed from StrictFIFO
```

2. Apply the changes:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

### Behavior with BestEffortFIFO

- **Within same priority**: Workloads processed in FIFO order
- **Across priorities**: Higher priority workloads (`psap-releases`, value=1000) admitted before lower priority (`psap-research`, value=100)

**Example Scenario**:
```
Time 0: Submit research workload (priority=100) → Queued (no GPUs available)
Time 1: Submit release workload (priority=1000) → Queued behind research
Time 2: GPUs become available → Release workload admitted FIRST (higher priority)
Time 3: More GPUs available → Research workload admitted
```

## Troubleshooting

### PipelineRun Not Starting

**Check if workload was created**:
```bash
kubectl get workloads -n llm-d-bench
```

If no workload exists, check:
- Kueue is enabled: `oc get pods -n kueue-system`
- PipelineRun has correct labels in `taskRunTemplate.podTemplate.labels`

**Check workload status**:
```bash
kubectl describe workload <workload-name> -n llm-d-bench
```

Look for:
- `Admitted: False` with `Reason: QuotaReserved` → Waiting for GPU quota
- `Admitted: False` with `Reason: Inadmissible` → Configuration issue

### Workload Stuck in Queue

**Check quota usage**:
```bash
kubectl get clusterqueue benchmark-cluster-queue -o yaml
```

Look at `status.flavorsUsage` to see current GPU allocation.

**Check if GPUs are actually available**:
```bash
# Check cluster GPU capacity
kubectl describe nodes | grep -A 10 "Allocatable:"

# Check running pods using GPUs
kubectl get pods -A -o json | jq '.items[] | select(.spec.containers[].resources.limits."nvidia.com/gpu") | {name: .metadata.name, namespace: .metadata.namespace, gpus: .spec.containers[].resources.limits."nvidia.com/gpu"}'
```

**Possible Solutions**:
1. Wait for current workloads to complete
2. Cancel lower-priority workloads
3. Increase GPU quota if cluster capacity allows

### Workload Evicted or Failed

**Check events**:
```bash
kubectl get events -n llm-d-bench --sort-by='.lastTimestamp'
```

Common causes:
- **Timeout**: Workload waited too long (default: no timeout)
- **Resource mismatch**: Requested GPUs don't match available flavors
- **Preemption**: Higher priority workload evicted this one (if preemption enabled)

## Advanced Configuration

### Enabling CPU and Memory Quotas

Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml` and uncomment:

```yaml
  resourceGroups:
  # Primary resource constraint: GPU quotas
  - coveredResources: ["nvidia.com/gpu"]
    flavors:
      - name: "default-flavor"
        resources:
          - name: "nvidia.com/gpu"
            nominalQuota: 16
            borrowingLimit: 8

  # Uncomment to enable CPU/memory quotas:
  - coveredResources: ["cpu", "memory"]
    flavors:
      - name: "default-flavor"
        resources:
          - name: "cpu"
            nominalQuota: 100  # Adjust to cluster capacity
          - name: "memory"
            nominalQuota: 500Gi  # Adjust to cluster capacity
```

Apply changes:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

### Enabling Preemption

Preemption allows high-priority workloads to evict low-priority ones.

Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml`:

```yaml
spec:
  preemption:
    withinClusterQueue: LowerPriority
    reclaimWithinCohort: Any
    borrowWithinCohort:
      policy: LowerPriority
      maxPriorityThreshold: 500  # Only preempt priorities < 500
```

**Effect**: `psap-releases` workloads (priority=1000) can preempt `psap-research` (priority=100)

Apply changes:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

### Enabling Fair Sharing

Fair sharing distributes resources equally across LocalQueues.

Edit `infra/manifests/kueue/overlays/management/cluster-queue.yaml`:

```yaml
spec:
  fairSharing:
    enable: true
    weight: 1  # Equal weight for all queues
```

Apply changes:
```bash
oc apply -k infra/manifests/kueue/overlays/management/
```

## Future Enhancements

### Multi-Cluster Federation (Not Currently Enabled)

The infrastructure for MultiKueue exists but is disabled:

**Files**:
- `infra/manifests/kueue/overlays/management/multikueue-config.yaml` (commented out)
- `infra/manifests/kueue/overlays/management/admission-check.yaml` (commented out)
- `infra/manifests/kueue/overlays/management/clusters/` (worker cluster templates)

**To Enable** (future):
1. Uncomment multi-cluster resources in `infra/manifests/kueue/overlays/management/kustomization.yaml`
2. Configure worker clusters
3. Update ClusterQueue with `admissionChecks: [multikueue-admission-check]`

### Per-User or Per-Team Quotas

Implement using Kueue Cohorts and per-team LocalQueues.

**Example Configuration**:
```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: team-ai-queue
  namespace: llm-d-bench
spec:
  clusterQueue: benchmark-cluster-queue
  resourceQuotas:
    - name: nvidia.com/gpu
      nominalQuota: 8  # Team AI gets 8 GPUs max
```

## References

- [Kueue Documentation](https://kueue.sigs.k8s.io/)
- [Kueue GitHub](https://github.com/kubernetes-sigs/kueue)
- [Tekton Pipelines](https://tekton.dev/)
- [Project README](../README.md)

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review Kueue logs: `kubectl logs -n kueue-system -l control-plane=controller-manager`
3. Open an issue in the project repository
