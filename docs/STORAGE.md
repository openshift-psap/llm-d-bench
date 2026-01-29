# Storage Configuration Guide

This guide covers storage configuration for llm-d-bench, including PVC access modes, storage classes, and troubleshooting.

## PVC Access Modes

llm-d-bench requires shared storage for model caching and benchmark results. The access mode depends on your deployment:

### ReadWriteOnce (RWO)

Use for single-pod deployments or single-node clusters:
- RHAIIS deployments (single Pod per model)
- Single-node OpenShift clusters
- Storage classes that only support RWO (e.g., `lvms-vg1`)

```bash
cp config/workspaces/models-storage-pvc-rwo.yaml config/workspaces/models-storage-pvc.yaml
```

### ReadWriteMany (RWX)

Use for multi-pod deployments:
- RHOAI deployments (multiple replicas possible)
- llm-d deployments (distributed inference)
- Multi-node clusters with RWX-capable storage

```bash
cp config/workspaces/models-storage-pvc-rwx.example.yaml config/workspaces/models-storage-pvc.yaml
```

**Important:** Verify your storage class supports RWX before using this mode:
```bash
oc get storageclass -o custom-columns=NAME:.metadata.name,VOLUME-BINDING:.volumeBindingMode,PROVISIONER:.provisioner
```

## Default Storage Class

Setting a default storage class avoids explicitly specifying `storageClassName` in PVC templates:

```bash
# Set your preferred storage class as default
oc patch storageclass lvms-vg1 -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

# Verify
oc get storageclass
# Should show: lvms-vg1 (default)
```

If multiple storage classes are marked as default, PVCs will use the most recently created one. To remove default annotation:

```bash
oc patch storageclass lvms-vg1 -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'
```

## Storage Requirements

### Model Storage PVC
- **Purpose:** Caches downloaded models from HuggingFace
- **Recommended size:** 100Gi minimum (models can be 5-50GB each)
- **Access mode:** Depends on deployment mode (see above)
- **Reclaim policy:** Retain (to preserve downloaded models)

### Benchmark Results PVC
- **Purpose:** Stores benchmark outputs when MLflow is disabled
- **Recommended size:** 10Gi
- **Access mode:** RWO (single pipeline writes at a time)
- **Path:** `/benchmark-results/`
- **Contents:** JSON outputs, HTML reports, console logs

## Troubleshooting

### PVC Stuck in Pending

**Symptoms:**
- `oc get pvc` shows `Pending` status
- Pipeline fails to start with volume mount errors

**Solutions:**

1. **Check storage class exists:**
   ```bash
   oc get storageclass
   ```

2. **Verify PVC access mode is supported:**
   ```bash
   oc describe storageclass <name> | grep "Volume Mode"
   ```

3. **Check provisioner logs:**
   ```bash
   oc get events -n llm-d-bench --sort-by='.lastTimestamp' | grep -i pvc
   ```

4. **For RWX issues:** Ensure storage class supports multi-attach
   - `lvms-vg1`: Only supports RWO
   - `nfs-client`: Supports RWX
   - `cephfs`: Supports RWX

### Access Mode Mismatch

**Symptoms:**
- Pod fails with: `Multi-Attach error for volume`
- Multiple pods trying to use RWO PVC

**Solution:**
Switch to RWX mode (if supported) or ensure only one pod uses the PVC:
```bash
cp config/workspaces/models-storage-pvc-rwx.example.yaml config/workspaces/models-storage-pvc.yaml
./scripts/install.sh -n llm-d-bench --with-pvcs
```

### Insufficient Storage

**Symptoms:**
- Downloads fail with "no space left on device"
- Pod evicted due to disk pressure

**Solution:**
Increase PVC size:
```bash
oc patch pvc models-storage -n llm-d-bench -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'
```

**Note:** Storage class must support volume expansion (`allowVolumeExpansion: true`).

## Manual PVC Creation

If not using `./scripts/install.sh --with-pvcs`, create PVCs manually:

```bash
# Model storage
oc apply -f config/workspaces/models-storage-pvc.yaml -n llm-d-bench

# Benchmark results
oc apply -f config/workspaces/benchmark-results-pvc.yaml -n llm-d-bench

# Verify
oc get pvc -n llm-d-bench
```

## Best Practices

1. **Use default storage class** for simpler PVC management
2. **Start with RWO** unless you specifically need multi-pod access
3. **Monitor PVC usage** to avoid running out of space:
   ```bash
   oc exec -n llm-d-bench deployment/<pod> -- df -h /mnt/models
   ```
4. **Clean up old models** periodically to reclaim space
5. **Use PVC snapshots** (if supported) before major changes
