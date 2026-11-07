# Fridge Tracker

Biết ai đặt gì vào tủ lạnh chung, ai lấy gì ra, và ai lấy nhầm đồ của người khác.
Tổng quan dự án: [docs/Fridge Tracker – Project Overview.md](docs/Fridge%20Tracker%20–%20Project%20Overview.md)

## Ai sở hữu thư mục nào

Mỗi người **chỉ sửa trong thư mục của mình**. Nhờ vậy merge không bao giờ conflict.

| Thư mục | Chủ | Branch |
| --- | --- | --- |
| `services/person/` | Vai 1 – Nhận diện người | `person` |
| `services/item/` | Vai 2 – Nhận diện món đồ | `item` |
| `services/backend/` | Vai 3 – Backend, matching, MCP (Dang) | `backend` |
| `dashboard/`, `eval/`, `infra/k8s/` | Vai 4 – Dashboard, hạ tầng, video | `dashboard` |
| `contracts/`, `tools/`, `infra/docker-compose.yml`, `README.md`, `.gitignore`, `docs/` | **Chung – chỉ Dang sửa** | `main` |

Muốn đổi file chung (thêm field vào sự kiện, thêm container vào compose…): nhắn Dang, Dang sửa trên `main`, mọi người `git merge main` vào branch mình.

## Bắt đầu (mỗi người)

```bash
git clone https://github.com/ProPhuMy/hackathon.git && cd hackathon
git switch -c <branch-của-bạn>          # person | item | backend | dashboard

docker compose -f infra/docker-compose.yml up -d   # Redpanda (localhost:19092) + Postgres (localhost:5432)
uv run tools/fake_events.py --loop                 # bắn sự kiện giả liên tục
```

Python service (person / item / backend):

```bash
cd services/<tên>
uv sync                 # tạo .venv riêng cho service này
uv add <thư-viện>       # chỉ sửa pyproject.toml + uv.lock của service này
uv run pytest           # PHẢI xanh trước khi mở PR
```

Dashboard:

```bash
cd dashboard && npm install && npm run dev
```

Xem sự kiện đang chạy trên bus:

```bash
docker compose -f infra/docker-compose.yml exec redpanda rpk topic consume person.seen
```

## Hợp đồng sự kiện

`contracts/*.schema.json` là nguồn sự thật duy nhất. Ba topic:

| Topic | Ai publish | Ai đọc |
| --- | --- | --- |
| `person.seen` | Vai 1 | Vai 3 |
| `item.event` | Vai 2 | Vai 3 |
| `fridge.event` | Vai 3 | Dashboard (qua API), MCP |

Quy tắc:
- Dựng sự kiện **chỉ** bằng hàm trong `src/<package>/events.py` của service mình, không tự viết dict ở chỗ khác.
- `tests/test_contract.py` kiểm tra hàm đó khớp schema. Test đỏ = sẽ vỡ khi ghép.
- `ts` luôn là UTC, dạng `2026-11-08T09:15:02.120Z`. `event_id` là uuid, dùng làm idempotency key.

## Quy trình Git

1. Làm trên branch của mình, commit thoải mái.
2. Mỗi khi phần của mình chạy được một bước: `uv run pytest` xanh → push → mở PR vào `main`.
3. Merge vào `main` vài lần trong đêm, đừng dồn đến cuối. Vì thư mục không chồng nhau nên PR không conflict, và `main` luôn có một bản chạy được để quay video dự phòng.
4. Kéo `main` mới về branch mình định kỳ: `git merge main`.

## Không đưa lên Git

Model weights (`*.pt`, `*.onnx`, …), video (`*.mp4`, …), `eval/clips/`, `models/`: đã chặn trong `.gitignore`. Chia sẻ qua Google Drive.
