# Internal Image Registry Setup

This directory contains manifests and scripts to configure the OpenShift internal image registry for llm-d-bench.

## Why This Is Needed

The llm-d-bench pipelines build custom container images that need to be pushed to a registry. The OpenShift internal registry provides a cluster-internal endpoint that doesn't require external registry credentials or network access.

## Prerequisites

- OpenShift cluster with internal image registry capability
- Available StorageClass (default: `lvms-vg1`)
- Cluster admin permissions

## Quick Setup

Run the setup script:

```bash
cd /Users/{username}/workspace/llm-d-bench
./scripts/setup-image-registry.sh
```

Or use the install script from infra/manifests/image-registry:

```bash
cd infra/manifests/image-registry
./install.sh
```

## Manual Setup

If you prefer manual setup or need to customize:

### 1. Check Current Registry Status

```bash
oc get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.spec.managementState}'
```

### 2. Enable the Registry

```bash
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"managementState":"Managed"}}'
```

### 3. Configure Storage

For single-node clusters or RWO storage:

```bash
# Set replicas to 1
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"replicas":1}}'

# Create PVC (customize storage size and class as needed)
oc create -f pvc.yaml
```

For multi-node clusters with RWX storage:

```bash
# Modify pvc.yaml to use ReadWriteMany
# Set appropriate replica count (default is 2)
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"replicas":2}}'
```

### 4. Configure Registry to Use PVC

```bash
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"storage":{"pvc":{"claim":"image-registry-storage"}}}}'
```

### 5. Verify Registry is Running

```bash
oc get pods -n openshift-image-registry
oc get svc image-registry -n openshift-image-registry
```

## Configuration Options

### Storage Size

Edit `pvc.yaml` and modify the storage request:

```yaml
spec:
  resources:
    requests:
      storage: 100Gi  # Adjust as needed
```

### Storage Class

Edit `pvc.yaml` to use a different storage class:

```yaml
spec:
  storageClassName: your-storage-class
```

Common storage classes:
- `lvms-vg1` - Local Volume Manager Storage
- `ocs-storagecluster-ceph-rbd` - OpenShift Container Storage
- `thin` - VMware thin provisioning
- `gp2` / `gp3` - AWS EBS

### Registry Endpoint

The internal registry is accessible at:
```
image-registry.openshift-image-registry.svc:5000
```

This is the default endpoint used in llm-d-bench pipelines.

## Troubleshooting

### Registry Pods Not Starting

Check PVC status:
```bash
oc get pvc -n openshift-image-registry
oc describe pvc image-registry-storage -n openshift-image-registry
```

Common issues:
- **No storage class set**: Add `storageClassName` to PVC
- **RWX on RWO storage**: Set registry replicas to 1
- **Insufficient storage**: Check available capacity in storage class

### Push/Pull Failures

1. Verify registry service exists:
```bash
oc get svc -n openshift-image-registry | grep image-registry
```

2. Check registry logs:
```bash
oc logs deployment/image-registry -n openshift-image-registry
```

3. Verify service account has access:
```bash
oc adm policy add-scc-to-user privileged -z default -n llm-d-bench
```

### DNS Resolution Issues

If buildah can't resolve `image-registry.openshift-image-registry.svc`:

1. Check CoreDNS is running:
```bash
oc get pods -n openshift-dns
```

2. Test DNS resolution from a pod:
```bash
oc run test-dns --image=alpine --rm -it -- nslookup image-registry.openshift-image-registry.svc
```

## Cleanup

To remove the registry configuration:

```bash
# Disable registry
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"managementState":"Removed"}}'

# Delete PVC
oc delete pvc image-registry-storage -n openshift-image-registry
```
