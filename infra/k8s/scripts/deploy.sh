#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

BASE_DIR="${SCRIPT_DIR}/../base"

echo "Applying namespace..."
kc apply -f "${BASE_DIR}/namespace.yaml"

echo "Applying Postgres and Redpanda StatefulSets..."
kc apply -f "${BASE_DIR}/postgres.yaml"
kc apply -f "${BASE_DIR}/redpanda.yaml"

echo "Waiting for Postgres StatefulSet rollout..."
kc rollout status statefulset/postgres --timeout=120s

echo "Waiting for Redpanda StatefulSet rollout..."
kc rollout status statefulset/redpanda --timeout=120s

echo "Preparing topics-bootstrap Job..."
kc delete job topics-bootstrap --ignore-not-found=true

echo "Applying topics-bootstrap Job..."
kc apply -f "${BASE_DIR}/topics-job.yaml"

echo "Waiting for topics-bootstrap Job completion..."
if ! kc wait --for=condition=complete job/topics-bootstrap --timeout=180s; then
    echo "Error: topics-bootstrap Job failed or timed out. Fetching Job logs:" >&2
    kc logs job/topics-bootstrap || true
    exit 1
fi
echo "Topic bootstrap succeeded."

echo "Applying backend Deployment..."
kc apply -f "${BASE_DIR}/backend.yaml"

echo "Waiting for backend Deployment rollout..."
kc rollout status deployment/backend --timeout=300s
echo "Backend deployment successfully rolled out."

SERVER_NODE="k3d-${CLUSTER_NAME}-server-0"
echo "Checking if dashboard image is imported in cluster node '$SERVER_NODE'..."
if docker exec "$SERVER_NODE" crictl images 2>/dev/null | grep -q "fridge-dashboard"; then
    echo "Dashboard image detected. Applying dashboard Deployment and Service..."
    kc apply -f "${BASE_DIR}/dashboard.yaml"
    echo "Waiting for dashboard Deployment rollout..."
    kc rollout status deployment/dashboard --timeout=120s
    echo "Dashboard deployment complete."
else
    echo "Notice: Dashboard image not found in '$SERVER_NODE' image store."
    echo "Skipping dashboard deployment."
fi

echo "Deployment finished successfully."
