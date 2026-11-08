#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

K3S_IMAGE="${K3S_IMAGE:-rancher/k3s:v1.30.6-k3s1}"

mkdir -p "$(dirname "$KUBECONFIG_FILE")"

if k3d cluster list "$CLUSTER_NAME" >/dev/null 2>&1; then
    echo "Cluster '$CLUSTER_NAME' already exists. Refreshing kubeconfig at '$KUBECONFIG_FILE'..."
    k3d kubeconfig get "$CLUSTER_NAME" > "$KUBECONFIG_FILE"
    chmod 600 "$KUBECONFIG_FILE"
    echo "Kubeconfig updated successfully."
    exit 0
fi

echo "Creating k3d cluster '$CLUSTER_NAME' (image: $K3S_IMAGE)..."
k3d cluster create "$CLUSTER_NAME" \
    --image "$K3S_IMAGE" \
    --kubeconfig-update-default=false \
    --kubeconfig-switch-context=false \
    -p "127.0.0.1:18080:30080@server:0" \
    --agents 0 \
    --wait

echo "Writing kubeconfig to '$KUBECONFIG_FILE'..."
k3d kubeconfig get "$CLUSTER_NAME" > "$KUBECONFIG_FILE"
chmod 600 "$KUBECONFIG_FILE"

echo "Cluster '$CLUSTER_NAME' created and ready. Context is isolated to '$CONTEXT_NAME'."
