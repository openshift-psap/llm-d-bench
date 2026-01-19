#!/bin/bash
#
# install.sh - Install all Tekton resources for llm-d-bench
#
# This script installs Tasks, Pipelines, and optionally infrastructure components
# and PVCs in the specified namespace.
#
# Usage:
#   ./scripts/install.sh                                    # Install in default namespace
#   ./scripts/install.sh -n my-namespace                    # Install in specific namespace
#   ./scripts/install.sh -n my-namespace --with-pvcs        # Also create PVCs
#   ./scripts/install.sh --with-infra                       # Install infrastructure (Kueue, etc.)
#   ./scripts/install.sh --setup-image-registry             # Setup internal image registry
#   ./scripts/install.sh -n my-namespace --with-infra --with-pvcs --setup-image-registry  # Full installation
#

set -e

NAMESPACE=""
CREATE_PVCS=false
INSTALL_INFRA=false
SETUP_REGISTRY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --with-pvcs)
            CREATE_PVCS=true
            shift
            ;;
        --with-infra|--with-infrastructure)
            INSTALL_INFRA=true
            shift
            ;;
        --setup-image-registry)
            SETUP_REGISTRY=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -n, --namespace NAMESPACE   Install in specified namespace"
            echo "  --with-pvcs                 Also create PersistentVolumeClaims"
            echo "  --with-infra                Install infrastructure components (Kueue, etc.)"
            echo "  --setup-image-registry      Setup OpenShift internal image registry with persistent storage"
            echo "  -h, --help                  Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

NS_FLAG=""
if [ -n "$NAMESPACE" ]; then
    NS_FLAG="-n $NAMESPACE"
    echo "Installing in namespace: $NAMESPACE"
else
    NAMESPACE=$(oc project -q 2>/dev/null || echo "default")
    echo "Installing in current namespace: $NAMESPACE"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "llm-d-bench Installation"
echo "Project root: $PROJECT_ROOT"
echo "Namespace: $NAMESPACE"
echo "Create PVCs: $CREATE_PVCS"
echo "Install Infrastructure: $INSTALL_INFRA"
echo "Setup Image Registry: $SETUP_REGISTRY"
echo ""

echo "Configuring Tekton Pipelines Security Context Constraints..."
# Grant privileged SCC to Tekton service accounts to allow them to run
# This is required because Tekton controllers use non-standard user IDs (65532)
# and seccomp annotations that don't match the default namespace restrictions
if oc get namespace tekton-pipelines &>/dev/null; then
    echo "  - Granting privileged SCC to tekton-pipelines-controller"
    oc adm policy add-scc-to-user privileged -z tekton-pipelines-controller -n tekton-pipelines 2>/dev/null || true
    echo "  - Granting privileged SCC to tekton-events-controller"
    oc adm policy add-scc-to-user privileged -z tekton-events-controller -n tekton-pipelines 2>/dev/null || true
    echo "  - Granting privileged SCC to tekton-pipelines-webhook"
    oc adm policy add-scc-to-user privileged -z tekton-pipelines-webhook -n tekton-pipelines 2>/dev/null || true
    echo "✓ Tekton SCC configured"
else
    echo "  ⚠ tekton-pipelines namespace not found - skipping SCC configuration"
fi
echo ""

echo "Installing RBAC resources..."
for rbac in "$PROJECT_ROOT"/config/rbac/*.yaml; do
    if [ -f "$rbac" ]; then
        echo "  - $(basename "$rbac")"
        # Replace namespace in ClusterRoleBinding to match target namespace
        sed "s/namespace: llm-d-bench/namespace: $NAMESPACE/g" "$rbac" | oc apply $NS_FLAG -f -
    fi
done
echo "✓ RBAC resources installed"
echo ""

echo "Configuring image registry permissions..."
echo "  - Granting system:image-builder to default service account"
oc policy add-role-to-user system:image-builder -z default $NS_FLAG 2>/dev/null || true
echo "✓ Image registry permissions configured"
echo ""

echo "Installing Secrets..."
SECRET_COUNT=0
for secret in "$PROJECT_ROOT"/config/secrets/*.yaml; do
    # Skip .example.yaml files and check if file exists (not just glob pattern)
    if [ -f "$secret" ] && [[ ! "$secret" =~ \.example\.yaml$ ]]; then
        echo "  - $(basename "$secret")"
        oc apply -f "$secret" $NS_FLAG
        SECRET_COUNT=$((SECRET_COUNT + 1))
    fi
done
if [ $SECRET_COUNT -eq 0 ]; then
    echo "  No secrets found to install"
fi
echo "✓ Secrets processed"
echo ""

echo "Installing Tasks..."
# Find all YAML files in tasks directory and subdirectories, excluding config directories
find "$PROJECT_ROOT/tasks" -type f -name "*.yaml" ! -path "*/config/*" | while read -r task; do
    if [ -f "$task" ]; then
        # Get relative path from tasks directory for display
        rel_path="${task#$PROJECT_ROOT/tasks/}"
        echo "  - $rel_path"
        oc apply -f "$task" $NS_FLAG
    fi
done
echo "✓ Tasks installed"
echo ""

echo "Installing Pipelines..."
# Find all YAML files in pipelines directory and subdirectories
find "$PROJECT_ROOT/pipelines" -type f -name "*.yaml" | while read -r pipeline; do
    if [ -f "$pipeline" ]; then
        # Get relative path from pipelines directory for display
        rel_path="${pipeline#$PROJECT_ROOT/pipelines/}"
        echo "  - $rel_path"
        oc apply -f "$pipeline" $NS_FLAG
    fi
done
echo "✓ Pipelines installed"
echo ""

if [ "$INSTALL_INFRA" = true ]; then
    echo "Installing Infrastructure components..."
    echo ""

    # Check if kustomize is available
    if ! command -v kustomize &> /dev/null; then
        echo "Warning: kustomize not found. Using 'oc apply -k' instead."
        KUSTOMIZE_CMD="oc apply -k"
    else
        KUSTOMIZE_CMD="kustomize build"
    fi

    # Deploy infrastructure using kustomize
    if [ -d "$PROJECT_ROOT/infra" ]; then
        echo "  Installing Kueue and other infrastructure components..."

        if [ "$KUSTOMIZE_CMD" = "kustomize build" ]; then
            kustomize build "$PROJECT_ROOT/infra" | oc apply -f -
        else
            oc apply -k "$PROJECT_ROOT/infra"
        fi

        echo ""
        echo "  Waiting for Kueue to be ready..."
        # Wait for Kueue deployment to be ready (with timeout)
        if oc wait --for=condition=available --timeout=120s deployment/kueue-controller-manager -n kueue-system 2>/dev/null; then
            echo "  ✓ Kueue controller is ready"
        else
            echo "  ⚠ Kueue controller may still be starting (timeout waiting for ready state)"
            echo "    Check status with: oc get pods -n kueue-system"
        fi

        echo ""
        echo "  Verifying infrastructure components:"
        echo "    ClusterQueues:"
        oc get clusterqueue 2>/dev/null | grep -E 'NAME|benchmark-cluster-queue' || echo "      No ClusterQueues found"
        echo ""
        echo "    LocalQueues in $NAMESPACE:"
        oc get localqueue $NS_FLAG 2>/dev/null | grep -E 'NAME|psap' || echo "      No LocalQueues found"
        echo ""
        echo "    WorkloadPriorityClasses:"
        oc get workloadpriorityclass 2>/dev/null | grep -E 'NAME|psap' || echo "      No WorkloadPriorityClasses found"
        echo ""

    else
        echo "  Warning: infra/ directory not found. Skipping infrastructure installation."
    fi

    echo "✓ Infrastructure components installed"
    echo ""
    echo "  For more information on Kueue configuration, see docs/kueue.md"
    echo ""
fi

if [ "$CREATE_PVCS" = true ]; then
    echo "Creating PersistentVolumeClaims..."

    # Check if models-storage-pvc.yaml exists (user must copy from template)
    if [ ! -f "$PROJECT_ROOT/config/workspaces/models-storage-pvc.yaml" ]; then
        echo "  models-storage-pvc.yaml not found!"
        echo "  Please copy the appropriate template based on your deployment:"
        echo "    For RHAIIS/single-node: cp config/workspaces/models-storage-pvc-rwo.yaml config/workspaces/models-storage-pvc.yaml"
        echo "    For RHOAI/llm-d multi-pod: cp config/workspaces/models-storage-pvc-rwx.example.yaml config/workspaces/models-storage-pvc.yaml"
        echo ""
    fi

    PVC_COUNT=0
    for pvc in "$PROJECT_ROOT"/config/workspaces/*.yaml; do
        # Skip .example.yaml files and template files (those with -rwo or -rwx in the name)
        if [ -f "$pvc" ] && [[ ! "$pvc" =~ \.example\.yaml$ ]] && [[ ! "$pvc" =~ -rwo\.yaml$ ]] && [[ ! "$pvc" =~ -rwx\.yaml$ ]]; then
            # Extract PVC name from the YAML file
            PVC_NAME=$(grep "^  name:" "$pvc" | head -1 | awk '{print $2}')

            if oc get pvc "$PVC_NAME" $NS_FLAG &>/dev/null; then
                echo "  - $(basename "$pvc") (already exists, skipping)"
            else
                echo "  - $(basename "$pvc") (creating)"
                oc apply -f "$pvc" $NS_FLAG
            fi
            PVC_COUNT=$((PVC_COUNT + 1))
        fi
    done

    if [ $PVC_COUNT -eq 0 ]; then
        echo "  No PVCs found to create (templates are skipped)"
    fi

    echo "✓ PVCs processed"
    echo ""
fi

if [ "$SETUP_REGISTRY" = true ]; then
    echo "Setting up OpenShift internal image registry..."
    echo ""

    # Run the registry setup script
    if [ -f "$PROJECT_ROOT/infra/manifests/image-registry/install.sh" ]; then
        "$PROJECT_ROOT/infra/manifests/image-registry/install.sh"
    else
        echo "  ⚠ Registry setup script not found at infra/manifests/image-registry/install.sh"
        echo "  Skipping registry setup."
    fi
    echo ""
fi

echo "Verifying installation..."
echo ""
echo "ServiceAccounts:"
oc get serviceaccount $NS_FLAG | grep -E 'NAME|deploy-model' || true
echo ""
echo "Tasks:"
oc get tasks $NS_FLAG | grep -E 'NAME|guidellm|wait-for-endpoint|download-model|deploy-llm-d|cleanup-llm-d|deploy-rhoai|cleanup-rhoai|deploy-rhaiis|cleanup-rhaiis' || true
echo ""
echo "Pipelines:"
oc get pipelines.tekton.dev $NS_FLAG | grep -E 'NAME|guidellm|llm-d-end-to-end|rhoai-end-to-end|rhaiis-end-to-end' || true
echo ""

if [ "$CREATE_PVCS" = true ]; then
    echo "PVCs:"
    oc get pvc $NS_FLAG | grep -E 'NAME|benchmark|models' || true
    echo ""
fi

echo "Installation Complete!"
echo ""
echo "For more information, see README.md"
