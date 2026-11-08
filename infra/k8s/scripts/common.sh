#!/usr/bin/env bash
set -euo pipefail

KUBECONFIG_FILE="${FRIDGE_KUBECONFIG:-$HOME/.config/fridge-k3d/kubeconfig}"
CLUSTER_NAME="fridge-dev"
CONTEXT_NAME="k3d-fridge-dev"
NAMESPACE="fridge"

kc() {
    kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$CONTEXT_NAME" -n "$NAMESPACE" "$@"
}
