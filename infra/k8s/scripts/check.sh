#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

echo "Setting up port-forward to svc/backend (18000:8000)..."
kc port-forward svc/backend 18000:8000 >/dev/null 2>&1 &
PF_PID=$!

cleanup() {
    if [ -n "${PF_PID:-}" ]; then
        kill "$PF_PID" 2>/dev/null || true
        wait "$PF_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Wait for port-forward to become responsive
READY=0
for _ in $(seq 1 30); do
    if curl -s -f http://127.0.0.1:18000/events?limit=1 >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" -ne 1 ]; then
    echo "FAIL: Backend port-forward on http://127.0.0.1:18000 did not become ready in 30s." >&2
    exit 1
fi
echo "Backend port-forward active."

echo "Polling /alerts for item_042 wrong_owner alert (up to 60s)..."
ALERT_DETECTED=0
for i in $(seq 1 60); do
    ALERTS_JSON=$(curl -s http://127.0.0.1:18000/alerts || echo "[]")
    FOUND=$(python3 -c '
import json, sys
data = json.loads(sys.argv[1])
for a in data:
    if a.get("item_id") == "item_042" and a.get("status") == "wrong_owner":
        print("yes")
        sys.exit(0)
print("no")
' "$ALERTS_JSON")
    if [ "$FOUND" = "yes" ]; then
        ALERT_DETECTED=1
        break
    fi
    sleep 1
done

FAILED=0

if [ "$ALERT_DETECTED" -eq 1 ]; then
    echo "PASS: /alerts contains wrong_owner alert for item_042"
else
    echo "FAIL: /alerts did not receive wrong_owner alert for item_042 within 60s"
    FAILED=1
fi

EVENTS_JSON=$(curl -s http://127.0.0.1:18000/events?limit=100 || echo "[]")

PUT_OK=$(python3 -c '
import json, sys
data = json.loads(sys.argv[1])
for ev in data:
    if ev.get("type") == "PUT" and ev.get("item_id") == "item_042" and ev.get("person_id") == "p_01" and ev.get("status") == "ok":
        print("yes")
        sys.exit(0)
print("no")
' "$EVENTS_JSON")

if [ "$PUT_OK" = "yes" ]; then
    echo "PASS: /events contains PUT of item_042 by p_01 with status ok"
else
    echo "FAIL: /events missing PUT of item_042 by p_01 with status ok"
    FAILED=1
fi

TAKE_WRONG_OWNER=$(python3 -c '
import json, sys
data = json.loads(sys.argv[1])
for ev in data:
    if ev.get("type") == "TAKE" and ev.get("item_id") == "item_042" and ev.get("person_id") == "p_02" and ev.get("status") == "wrong_owner":
        print("yes")
        sys.exit(0)
print("no")
' "$EVENTS_JSON")

if [ "$TAKE_WRONG_OWNER" = "yes" ]; then
    echo "PASS: /events contains TAKE of item_042 by p_02 with status wrong_owner"
else
    echo "FAIL: /events missing TAKE of item_042 by p_02 with status wrong_owner"
    FAILED=1
fi

INVENTORY_JSON=$(curl -s http://127.0.0.1:18000/inventory || echo "[]")

INVENTORY_CLEARED=$(python3 -c '
import json, sys
data = json.loads(sys.argv[1])
for item in data:
    if item.get("item_id") == "item_042":
        print("no")
        sys.exit(0)
print("yes")
' "$INVENTORY_JSON")

if [ "$INVENTORY_CLEARED" = "yes" ]; then
    echo "PASS: /inventory no longer contains item_042"
else
    echo "FAIL: /inventory still contains item_042 after TAKE"
    FAILED=1
fi

# Check dashboard endpoint if dashboard is deployed
if kc get deployment dashboard >/dev/null 2>&1; then
    echo "Checking dashboard /healthz endpoint at http://127.0.0.1:18080/healthz..."
    DASHBOARD_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/healthz || echo "000")
    if [ "$DASHBOARD_CODE" = "200" ]; then
        echo "PASS: Dashboard /healthz responded with HTTP 200"
    else
        echo "FAIL: Dashboard /healthz responded with HTTP $DASHBOARD_CODE (expected 200)"
        FAILED=1
    fi
else
    echo "SKIP: Dashboard deployment not present in cluster (skipping http://127.0.0.1:18080/healthz check)"
fi

if [ "$FAILED" -ne 0 ]; then
    echo "Verification FAILED."
    exit 1
fi

echo "All verification checks PASSED."
exit 0
