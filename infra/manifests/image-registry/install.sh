#!/bin/bash
#
# install.sh - Setup OpenShift internal image registry for llm-d-bench
#
# This script configures the OpenShift internal image registry with persistent storage.
# It handles both single-node (RWO) and multi-node (RWX) cluster configurations.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORAGE_SIZE="${STORAGE_SIZE:-50Gi}"
STORAGE_CLASS="${STORAGE_CLASS:-lvms-vg1}"
REGISTRY_REPLICAS="${REGISTRY_REPLICAS:-1}"

echo "OpenShift Internal Image Registry Setup"
echo "========================================"
echo ""
echo "Configuration:"
echo "  Storage Size: $STORAGE_SIZE"
echo "  Storage Class: $STORAGE_CLASS"
echo "  Registry Replicas: $REGISTRY_REPLICAS"
echo ""

# Check if oc is available
if ! command -v oc &> /dev/null; then
    echo "Error: oc CLI not found. Please install OpenShift CLI."
    exit 1
fi

# Check if logged in
if ! oc whoami &> /dev/null; then
    echo "Error: Not logged into OpenShift cluster. Please run 'oc login' first."
    exit 1
fi

# Check current registry state
echo "Checking current registry state..."
CURRENT_STATE=$(oc get configs.imageregistry.operator.openshift.io cluster -o jsonpath='{.spec.managementState}' 2>/dev/null || echo "Unknown")
echo "  Current state: $CURRENT_STATE"
echo ""

if [ "$CURRENT_STATE" = "Managed" ]; then
    echo "✓ Registry is already enabled (managementState: Managed)"
    
    # Check if registry is running
    if oc get deployment image-registry -n openshift-image-registry &>/dev/null; then
        READY=$(oc get deployment image-registry -n openshift-image-registry -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "$READY" -gt 0 ]; then
            echo "✓ Registry is running and healthy"
            echo ""
            oc get svc image-registry -n openshift-image-registry
            echo ""
            echo "Registry endpoint: image-registry.openshift-image-registry.svc:5000"
            exit 0
        fi
    fi
fi

# Enable registry
echo "Step 1: Enabling image registry..."
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"managementState":"Managed"}}'
echo "✓ Registry enabled"
echo ""

# Set replica count
echo "Step 2: Configuring replica count..."
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch "{\"spec\":{\"replicas\":$REGISTRY_REPLICAS}}"
echo "✓ Replicas set to $REGISTRY_REPLICAS"
echo ""

# Configure storage
echo "Step 3: Configuring storage..."
oc patch configs.imageregistry.operator.openshift.io cluster --type merge \
  --patch '{"spec":{"storage":{"pvc":{"claim":""}}}}'

# Check if PVC already exists
if oc get pvc image-registry-storage -n openshift-image-registry &>/dev/null; then
    echo "  ⚠ PVC 'image-registry-storage' already exists"
    PVC_STATUS=$(oc get pvc image-registry-storage -n openshift-image-registry -o jsonpath='{.status.phase}')
    echo "  PVC Status: $PVC_STATUS"
else
    echo "  Creating PVC with:"
    echo "    - Storage: $STORAGE_SIZE"
    echo "    - StorageClass: $STORAGE_CLASS"
    echo "    - AccessMode: ReadWriteOnce"
    
    # Create PVC with configured values
    cat <<EOFPVC | oc create -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: image-registry-storage
  namespace: openshift-image-registry
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: ${STORAGE_SIZE}
  storageClassName: ${STORAGE_CLASS}
EOFPVC
    
    echo "✓ PVC created"
fi
echo ""

# Wait for registry to be ready
echo "Step 4: Waiting for registry to be ready..."
echo "  (This may take 1-2 minutes)"

for i in {1..60}; do
    if oc get deployment image-registry -n openshift-image-registry &>/dev/null; then
        READY=$(oc get deployment image-registry -n openshift-image-registry -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "$READY" -gt 0 ]; then
            echo "✓ Registry is ready!"
            break
        fi
    fi
    
    if [ $i -eq 60 ]; then
        echo "⚠ Timeout waiting for registry to be ready"
        echo ""
        echo "Check status with:"
        echo "  oc get pods -n openshift-image-registry"
        echo "  oc describe pvc image-registry-storage -n openshift-image-registry"
        exit 1
    fi
    
    echo -n "."
    sleep 2
done
echo ""

# Verify and display results
echo ""
echo "✓ Setup Complete!"
echo ""
echo "Registry Service:"
oc get svc image-registry -n openshift-image-registry
echo ""
echo "Registry Pods:"
oc get pods -n openshift-image-registry | grep image-registry
echo ""
echo "Registry PVC:"
oc get pvc -n openshift-image-registry
echo ""
echo "Registry endpoint: image-registry.openshift-image-registry.svc:5000"
echo ""
echo "You can now build and push images using llm-d-bench pipelines!"
