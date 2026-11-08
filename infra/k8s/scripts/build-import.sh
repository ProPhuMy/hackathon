#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DASHBOARD_IMAGE="${DASHBOARD_IMAGE:-fridge-dashboard:dev}"

echo "Building fridge-backend:dev from repository root ($REPO_ROOT)..."
docker build -f "${REPO_ROOT}/infra/k8s/backend.Dockerfile" -t fridge-backend:dev "${REPO_ROOT}"

echo "Importing fridge-backend:dev into k3d cluster '$CLUSTER_NAME'..."
k3d image import fridge-backend:dev -c "$CLUSTER_NAME"

echo "Checking for dashboard image '$DASHBOARD_IMAGE' locally..."
if docker image inspect "$DASHBOARD_IMAGE" >/dev/null 2>&1; then
    echo "Dashboard image '$DASHBOARD_IMAGE' found. Importing into '$CLUSTER_NAME'..."
    k3d image import "$DASHBOARD_IMAGE" -c "$CLUSTER_NAME"
    echo "Dashboard image import complete."
else
    echo "Notice: Dashboard image '$DASHBOARD_IMAGE' not found locally."
    echo "The dashboard image is built by Role 4 from dashboard/ with '--build-arg VITE_API_BASE=/api'."
    echo "Skipping dashboard image import."
fi
