#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/k8s/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

echo "[SYNTHETIC] Generating batch of 4 synthetic events with fixed 1.0s timestamp offsets..."

# Generate all 4 events in ONE python3 invocation so timestamps have exact 1s offsets:
# t0: person p_01 (track 1, conf 0.94)
# t0 + 1s: PUT item_042 "milk carton" (conf 0.90)
# t0 + 2s: person p_02 (track 2, conf 0.91)
# t0 + 3s: TAKE item_042 "milk carton" (conf 0.87)
EVENTS=$(python3 -c '
import json, uuid
from datetime import datetime, timezone, timedelta

t0 = datetime.now(timezone.utc)

def format_ts(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

events = [
    (
        "person.seen",
        {
            "event_id": str(uuid.uuid4()),
            "topic": "person.seen",
            "track_id": 1,
            "person_id": "p_01",
            "ts": format_ts(t0),
            "confidence": 0.94,
        },
    ),
    (
        "item.event",
        {
            "event_id": str(uuid.uuid4()),
            "topic": "item.event",
            "type": "PUT",
            "item_id": "item_042",
            "item_label": "milk carton",
            "ts": format_ts(t0 + timedelta(seconds=1)),
            "confidence": 0.90,
        },
    ),
    (
        "person.seen",
        {
            "event_id": str(uuid.uuid4()),
            "topic": "person.seen",
            "track_id": 2,
            "person_id": "p_02",
            "ts": format_ts(t0 + timedelta(seconds=2)),
            "confidence": 0.91,
        },
    ),
    (
        "item.event",
        {
            "event_id": str(uuid.uuid4()),
            "topic": "item.event",
            "type": "TAKE",
            "item_id": "item_042",
            "item_label": "milk carton",
            "ts": format_ts(t0 + timedelta(seconds=3)),
            "confidence": 0.87,
        },
    ),
]

for topic, ev in events:
    print(f"{topic}\t{json.dumps(ev)}")
')

echo "[SYNTHETIC] Producing synthetic events to Redpanda in sequence..."

while IFS=$'\t' read -r topic payload; do
    [ -z "$topic" ] && continue
    event_id=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["event_id"])' "$payload")

    echo "[SYNTHETIC] Producing $topic (event_id: $event_id): $payload"
    echo "$payload" | kc exec -i redpanda-0 -- rpk topic produce "$topic" -X brokers=localhost:9092
    echo "[SYNTHETIC] Published event_id: $event_id"
done <<< "$EVENTS"

echo "[SYNTHETIC] Synthetic event seeding complete."
