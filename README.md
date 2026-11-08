# Fridge Tracker

Know who put what into a shared fridge, who took what out, and who took someone else's food.
Project overview: [docs/Fridge Tracker – Project Overview.md](docs/Fridge%20Tracker%20–%20Project%20Overview.md)

## Who owns which folder

Each person **only edits their own folder**. That way merges never conflict.

| Folder | Owner | Branch |
| --- | --- | --- |
| `services/person/` | Role 1 – Person recognition (Viet) | `person` |
| `services/item/` | Role 2 – Item recognition (Dang) | `item` |
| `services/backend/` | Role 3 – Backend, matching, MCP (Phong) | `backend` |
| `dashboard/`, `eval/`, `infra/k8s/` | Role 4 – Dashboard, infra, video (Khang) | `dashboard` |
| `contracts/`, `tools/`, `infra/docker-compose.yml`, `README.md`, `.gitignore`, `docs/` | **Shared – only Dang edits** | `main` |

Need to change a shared file (add a field to an event, add a container to compose, …)? Ask Dang. Dang changes it on `main`, then everyone runs `git merge main` into their branch.

## Getting started (everyone)

```bash
git clone https://github.com/ProPhuMy/hackathon.git && cd hackathon
git switch -c <your-branch>          # person | item | backend | dashboard

docker compose -f infra/docker-compose.yml up -d   # Redpanda (localhost:19092) + Postgres (localhost:5432)
uv run tools/fake_events.py --loop                 # publish fake events continuously
```

Python services (person / item / backend):

```bash
cd services/<name>
uv sync                 # creates this service's own .venv
uv add <package>        # only touches this service's pyproject.toml + uv.lock
uv run pytest           # MUST pass before opening a PR
```

Dashboard:

```bash
cd dashboard && npm install && npm run dev
```

Watch events on the bus:

```bash
docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume person.seen
```

## Event contracts

`contracts/*.schema.json` is the single source of truth. Three topics:

| Topic | Published by | Consumed by |
| --- | --- | --- |
| `person.seen` | Role 1 | Role 3 |
| `item.event` | Role 2 | Role 3 |
| `fridge.event` | Role 3 | Dashboard (via API), MCP |

Rules:
- Build events **only** with the function in your service's `src/<package>/events.py`; never hand-write the dict elsewhere.
- `tests/test_contract.py` checks that function against the schema. A red test means it will break at integration.
- `ts` is always UTC, formatted like `2026-11-08T09:15:02.120Z`. `event_id` is a uuid used as the idempotency key.

## Git workflow

1. Work on your own branch, commit as often as you like.
2. Whenever your part works one step further: `uv run pytest` passes → push → open a PR into `main`.
3. Merge into `main` several times during the night; don't save it all for the end. Folders don't overlap, so PRs don't conflict, and `main` always has a working build for a backup video.
4. Pull the latest `main` into your branch regularly: `git merge main`.

## Never commit

Model weights (`*.pt`, `*.onnx`, …), videos (`*.mp4`, …), `eval/clips/`, `models/`: already blocked in `.gitignore`. Share them via Google Drive.
