#!/bin/bash
#
# install.sh - Install all Tekton resources for llm-d-tekton
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

echo "Installing Tasks..."
for task in "$PROJECT_ROOT"/tasks/*.yaml; do
    if [ -f "$task" ]; then
        echo "  - $(basename "$task")"
        oc apply -f "$task" $NS_FLAG
    fi
done
echo "✓ Tasks installed"
echo ""

echo "Installing Pipelines..."
for pipeline in "$PROJECT_ROOT"/pipelines/*.yaml; do
    if [ -f "$pipeline" ]; then
        echo "  - $(basename "$pipeline")"
        oc apply -f "$pipeline" $NS_FLAG
    fi
done
echo "✓ Pipelines installed"
echo ""

if [ "$CREATE_PVCS" = true ]; then
    echo "Creating PersistentVolumeClaims..."
    for pvc in "$PROJECT_ROOT"/config/workspaces/*.yaml; do
        if [ -f "$pvc" ]; then
            echo "  - $(basename "$pvc")"
            oc apply -f "$pvc" $NS_FLAG
        fi
    done
    echo "✓ PVCs created"
    echo ""
fi

echo "Verifying installation..."
echo ""
echo "Tasks:"
oc get tasks $NS_FLAG | grep -E 'NAME|buildah-build|wait-for-endpoint|run-benchmark' || true
echo ""
echo "Pipelines:"
oc get pipelines $NS_FLAG | grep -E 'NAME|build-image|run-benchmark' || true
echo ""

if [ "$CREATE_PVCS" = true ]; then
    echo "PVCs:"
    oc get pvc $NS_FLAG | grep -E 'NAME|benchmark' || true
    echo ""
fi

echo "Installation Complete!"
echo ""
echo "For more information, see README.md"
