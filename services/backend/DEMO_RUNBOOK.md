# Demo runbook: run the whole Fridge Tracker chain

Start order and exact commands for demo day. Each command was checked against the service's CLI on `main` (`0c1ce47`, 2026-11-08). The full chain has not been run end to end yet; step 10 is that test.

## Machines

| Machine | Runs |
| :- | :- |
| Mac | Redpanda + Postgres (Docker), backend, person service, dashboard, recorder |
| GPU server | item service (reached through an SSH tunnel from the Mac) |
| Phone 1 (faces people) | video for the person service |
| Phone 2 (on top of the fridge) | video for the item service |

## 0. Once, before demo day

1. Agree one ID list, for example `p_01` = Viet, `p_02` = Alice. Use exactly these IDs in person enrollment (step 0.2) and backend registration (step 5).
2. Person service (`services/person/SETUP.md`): enroll each person with `uv run python -m src enroll --person-id p_01 --session-id enroll-p01-01 --source <phone1> --rotate <r>`, and calibrate a policy to `models/baseline-policy.json`. Use the same `--rotate` value everywhere.
3. Item service (`services/item/README.md`): `uv run python -m src calibrate <phone2-url> --out config.json` to set the door line.
4. Mac port 5432 must be free for the Compose Postgres (`lsof -i :5432`). Stop a native Postgres if one is running.

## 1. Check the clocks (Mac and GPU server)

The backend matches a face to an item by timestamp. Person stamps the Mac's clock and item stamps the GPU server's clock, so a skew between them shifts every match. The matcher tolerates about ±1.5 s in total, and network latency already uses part of that.

```bash
# Mac: offset from network time, must be under 0.1 s
sntp time.apple.com
# GPU server: must say "System clock synchronized: yes"
ssh <user>@<gpu-host> timedatectl
```

If either clock is not synced, fix it before going on (`sudo sntp -sS time.apple.com` on the Mac; `sudo timedatectl set-ntp true` on Linux).

## 2. Start Redpanda and Postgres (Mac, repo root)

```bash
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml exec redpanda rpk topic create person.seen item.event fridge.event
```

`rpk topic create` reports `TOPIC_ALREADY_EXISTS` on a rerun; that is fine.

## 3. Start the backend (Mac)

```bash
cd services/backend
uv run fridge-backend
```

Defaults: Postgres `localhost:5432` (user/password/db `fridge`), Kafka `localhost:19092`, API on port 8000. Migrations run at startup. Check it from another terminal:

```bash
curl -s 'http://localhost:8000/events?limit=1'   # expect []
```

If the backend refuses to start with a matcher version error, the database holds a journal from an older `MATCHER_VERSION` (now `4-person-marginal`). For a demo with no history to keep: `docker compose -f infra/docker-compose.yml down -v` (deletes all stored events), then go back to step 2.

## 4. Optional: start the recorder (Mac)

Captures both input topics for the stage 4 latency measurement. Wait for `READY` on stderr before the first action. Stop with Ctrl+C.

```bash
cd services/backend
mkdir -p ../../recordings   # the recorder does not create the folder
uv run python -m fridge_backend.recorder ../../recordings/rehearsal.jsonl
```

While it runs, write down who did each PUT and TAKE.

## 5. Register the people in the backend (Mac)

Use the IDs from step 0.1. The display name is what the dashboard shows.

```bash
curl -s -X POST localhost:8000/people -H 'Content-Type: application/json' -d '{"person_id":"p_01","name":"Viet"}'
curl -s -X POST localhost:8000/people -H 'Content-Type: application/json' -d '{"person_id":"p_02","name":"Alice"}'
```

A `409` means the person already exists; that is fine.

## 6. Open the SSH tunnel to the GPU server (Mac)

Phone 2 and the Mac must be on the same Wi-Fi or hotspot. Keep this terminal open.

```bash
ssh -N -R 8080:<phone2-ip>:8080 -R 19092:localhost:19092 <user>@<gpu-host>
```

## 7. Start the item service (GPU server)

```bash
cd services/item
uv run python -m src run --source http://localhost:8080/video --config config.json --gallery data/gallery.json --broker localhost:19092 --embed
```

Do not pass `--dry-run`: it prints events and does not publish them. Keep `data/gallery.json` between PUT and TAKE; it is what makes a TAKE carry the same `item_id` as its PUT.

## 8. Start the person service (Mac)

```bash
cd services/person
uv run python -m src run --source <phone1-url-or-0> --policy models/baseline-policy.json --broker localhost:19092 --rotate <r>
```

`--broker` has no default. Without it the service prints events to the terminal and publishes nothing.

## 9. Start the dashboard (Mac)

Follow `dashboard/README.md` (`npm ci`, `npm run dev`). The dashboard must point at the backend on port 8000; the live API connection is Role 4's work in progress.

## 10. Smoke test

1. p_01 stands at the fridge, faces phone 1, and puts an item in.
2. p_02 does the same, then takes that item out.
3. Within about 10 s:

```bash
curl -s localhost:8000/events    # PUT by p_01 status ok, then TAKE by p_02 status wrong_owner
curl -s localhost:8000/alerts    # one wrong_owner alert
```

To see raw inputs while debugging:

```bash
docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume person.seen
docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume item.event
```

## Fallback: synthetic demo

If a camera or model fails on stage, run the fake scenario instead (repo root). It always gives PUT ok, then TAKE wrong_owner, with an alert:

```bash
uv run tools/fake_events.py
```

Say on stage that this is synthetic data.

## Known behavior and troubleshooting

| Symptom | Cause | Fix |
| :- | :- | :- |
| Events appear about 7 s after the action | The person service publishes nothing while no face is visible, so the backend closes each match on its idle timeout (2 + 2 + 3 s) | Expected. Mention it, or keep a face in view of phone 1 |
| PUT or TAKE shows `uncertain` | No face within about 3 s of the hand, or confidence under 0.5 (real item confidence is detector score × embedding score) | Face phone 1 while using the fridge |
| `person_id` is null on every event | `person.seen` is not reaching the broker | Check `--broker` on the person service; consume `person.seen` |
| No `item.event` at all | Tunnel down, or item started with `--dry-run` | Check the tunnel terminal; restart item without `--dry-run` |
| Wrong person credited on every event | Clock skew between the Mac and the GPU server | Step 1 |
| Backend exits at start with a version error | Old journal in Postgres | See step 3 |
| Postgres container fails on port 5432 | A native Postgres is running on the Mac | Stop it (step 0.4) |

The item service pairs door crossings in order, so it assumes one person at the fridge at a time. Do the PUT and TAKE as two separate visits.
