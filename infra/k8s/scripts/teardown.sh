#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

CONFIRMED=0
for arg in "$@"; do
    if [ "$arg" = "--yes" ]; then
        CONFIRMED=1
    fi
done

if [ "$CONFIRMED" -ne 1 ]; then
    echo "WARNING: Teardown will delete k3d cluster '$CLUSTER_NAME' and remove '$KUBECONFIG_FILE'." >&2
    echo "DATA LOSS NOTICE: This permanently removes all persistent cluster volumes (PostgreSQL data and Redpanda message storage)." >&2
    echo "This operation does not affect local Docker images, Docker Compose volumes, or other k3d clusters." >&2
    echo "To proceed, run: $0 --yes" >&2
    exit 1
fi

echo "Deleting k3d cluster '$CLUSTER_NAME'..."
if k3d cluster list "$CLUSTER_NAME" >/dev/null 2>&1; then
    k3d cluster delete "$CLUSTER_NAME"
    echo "Cluster '$CLUSTER_NAME' deleted."
else
    echo "Cluster '$CLUSTER_NAME' does not exist."
fi

if [ -f "$KUBECONFIG_FILE" ]; then
    echo "Removing kubeconfig file '$KUBECONFIG_FILE'..."
    rm -f "$KUBECONFIG_FILE"
fi

echo "Teardown complete."
