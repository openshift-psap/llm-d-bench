#!/bin/bash
#
# install.sh - Install all Tekton resources for llm-d-bench
#
# This script installs Tasks, Pipelines, and optionally PVCs in the specified namespace.
#
# Usage:
#   ./scripts/install.sh                    # Install in default namespace
#   ./scripts/install.sh -n my-namespace    # Install in specific namespace
#   ./scripts/install.sh -n my-namespace --with-pvcs  # Also create PVCs
#

set -e

NAMESPACE=""
CREATE_PVCS=false

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
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -n, --namespace NAMESPACE   Install in specified namespace"
            echo "  --with-pvcs                 Also create PersistentVolumeClaims"
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

echo "LLM-D-Tekton Installation"
echo "Project root: $PROJECT_ROOT"
echo "Namespace: $NAMESPACE"
echo "Create PVCs: $CREATE_PVCS"
echo ""

echo "Installing RBAC resources..."
for rbac in "$PROJECT_ROOT"/config/rbac/*.yaml; do
    if [ -f "$rbac" ]; then
        echo "  - $(basename "$rbac")"
        oc apply -f "$rbac" $NS_FLAG
    fi
done
echo "✓ RBAC resources installed"
echo ""

echo "Installing Tasks..."
# Find all YAML files in tasks directory and subdirectories
find "$PROJECT_ROOT/tasks" -type f -name "*.yaml" | while read -r task; do
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

if [ "$CREATE_PVCS" = true ]; then
    echo "Creating PersistentVolumeClaims..."
    for pvc in "$PROJECT_ROOT"/config/workspaces/*.yaml; do
        if [ -f "$pvc" ]; then
            # Extract PVC name from the YAML file
            PVC_NAME=$(grep "^  name:" "$pvc" | head -1 | awk '{print $2}')

            if oc get pvc "$PVC_NAME" $NS_FLAG &>/dev/null; then
                echo "  - $(basename "$pvc") (already exists, skipping)"
            else
                echo "  - $(basename "$pvc") (creating)"
                oc apply -f "$pvc" $NS_FLAG
            fi
        fi
    done
    echo "✓ PVCs processed"
    echo ""
fi

echo "Verifying installation..."
echo ""
echo "ServiceAccounts:"
oc get serviceaccount $NS_FLAG | grep -E 'NAME|deploy-model' || true
echo ""
echo "Tasks:"
oc get tasks $NS_FLAG | grep -E 'NAME|buildah-build|wait-for-endpoint|run-benchmark|download-model|deploy-model|cleanup-deployment|deploy-helmfile|cleanup-upstream' || true
echo ""
echo "Pipelines:"
oc get pipelines.tekton.dev $NS_FLAG | grep -E 'NAME|build-image|run-benchmark|downstream-end-to-end-benchmark|upstream-end-to-end-benchmark' || true
echo ""

if [ "$CREATE_PVCS" = true ]; then
    echo "PVCs:"
    oc get pvc $NS_FLAG | grep -E 'NAME|benchmark|models' || true
    echo ""
fi

echo "Installation Complete!"
echo ""
echo "For more information, see README.md"
