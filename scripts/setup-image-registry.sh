#!/bin/bash
#
# setup-image-registry.sh - Wrapper script to setup image registry
#
# This script calls the main install script from infra/manifests/image-registry
# with customizable parameters.
#
# Usage:
#   ./scripts/setup-image-registry.sh
#   STORAGE_SIZE=100Gi ./scripts/setup-image-registry.sh
#   STORAGE_CLASS=ocs-storagecluster-ceph-rbd STORAGE_SIZE=100Gi ./scripts/setup-image-registry.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values (can be overridden by environment variables)
export STORAGE_SIZE="${STORAGE_SIZE:-50Gi}"
export STORAGE_CLASS="${STORAGE_CLASS:-lvms-vg1}"
export REGISTRY_REPLICAS="${REGISTRY_REPLICAS:-1}"

# Run the main install script
exec "$PROJECT_ROOT/infra/manifests/image-registry/install.sh"
