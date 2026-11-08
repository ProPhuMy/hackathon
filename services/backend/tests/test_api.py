"""Tests for FastAPI HTTP endpoints, SSE stream, cursor resolution, and error handling."""

import asyncio
import json
import threading
import anyio
import pytest
from io_helpers import MockPostgresConn
from fridge_backend.config import BackendConfig
from fridge_backend.store import PostgresStore

try:
    from fridge_backend.api import create_app
except ImportError:
    create_app = None


def make_sample_event(event_id: str, item_id: str, item_label: str, ev_type: str = "PUT",
                      person_id: str | None = "p_01", owner_id: str | None = "p_01",
                      status: str = "ok", ts: str = "2026-11-08T09:15:00.000Z") -> dict:
    return {
        "event_id": event_id,
        "topic": "fridge.event",
        "type": ev_type,
        "item_id": item_id,
        "item_label": item_label,
        "person_id": person_id,
        "owner_id": owner_id,
        "ts": ts,
        "confidence": 0.90,
        "status": status,
    }


def get_test_client(store: PostgresStore, worker_controller=None):
    assert create_app is not None, "api.py not yet implemented (Stage 2A red test)"
    from fastapi.testclient import TestClient
    cfg = BackendConfig()
    app = create_app(cfg, store, worker_controller=worker_controller)
    return TestClient(app)


def test_get_events_bare_list_and_limit_validation():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    for i in range(1, 4):
        fe = make_sample_event(f"e_{i}", f"item_{i}", f"label_{i}")
        store._insert_fridge_event(fe)
        store._insert_outbox(fe)

    client = get_test_client(store)

    # 1. Successful fetch: bare list, newest emitted first
    resp = client.get("/events?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), "Response must be a bare list"
    assert len(data) == 2
    assert data[0]["event_id"] == "e_3"
    assert data[1]["event_id"] == "e_2"
    # Ensure no extra wrapper fields or modified keys
    assert "event_id" in data[0]
    assert "cursor" not in data[0]

    # 2. Limit boundary validation (1..500)
    assert client.get("/events?limit=0").status_code == 422
    assert client.get("/events?limit=501").status_code == 422
    assert client.get("/events?limit=-5").status_code == 422


def test_get_alerts_filters_wrong_owner_and_uncertain():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    e_ok = make_sample_event("e_ok", "item_1", "Milk", status="ok")
    e_wrong = make_sample_event("e_wrong", "item_1", "Milk", ev_type="TAKE",
                                person_id="p_02", owner_id="p_01", status="wrong_owner")
    e_unc = make_sample_event("e_unc", "item_2", "Juice", person_id=None,
                              owner_id=None, status="uncertain")

    for e in (e_ok, e_wrong, e_unc):
        store._insert_fridge_event(e)
        store._insert_outbox(e)

    client = get_test_client(store)
    resp = client.get("/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), "Alerts must be a bare list"
    assert len(data) == 2
    # Newest emitted first
    assert data[0]["event_id"] == "e_unc"
    assert data[0]["status"] == "uncertain"
    assert data[1]["event_id"] == "e_wrong"
    assert data[1]["status"] == "wrong_owner"

    # Validation on limit
    assert client.get("/alerts?limit=0").status_code == 422
    assert client.get("/alerts?limit=501").status_code == 422


def test_get_inventory_bare_list_and_metadata_rules():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    # 1. PUT item1
    e1 = make_sample_event("e1", "milk_01", "Whole Milk", ts="2026-11-08T09:15:00.000Z")
    store._insert_fridge_event(e1)
    store._insert_outbox(e1)

    # 2. PUT item2
    e2 = make_sample_event("e2", "cheese_02", "Cheddar", ts="2026-11-08T09:15:02.000Z")
    store._insert_fridge_event(e2)
    store._insert_outbox(e2)

    # 3. Duplicate PUT item1 with different label/ts (preserves original metadata)
    e3 = make_sample_event("e3", "milk_01", "Almond Milk", status="uncertain",
                           ts="2026-11-08T09:15:05.000Z")
    store._insert_fridge_event(e3)
    store._insert_outbox(e3)

    # 4. TAKE item2 (clears cheese_02 and metadata)
    e4 = make_sample_event("e4", "cheese_02", "Cheddar", ev_type="TAKE",
                           person_id="p_02", owner_id="p_01", status="wrong_owner",
                           ts="2026-11-08T09:15:10.000Z")
    store._insert_fridge_event(e4)
    store._insert_outbox(e4)

    client = get_test_client(store)
    resp = client.get("/inventory")
    assert resp.status_code == 200
    inv = resp.json()
    assert isinstance(inv, list)
    assert len(inv) == 1
    item = inv[0]
    assert item["item_id"] == "milk_01"
    assert item["item_label"] == "Whole Milk"  # preserved original label
    assert item["since_ts"] == "2026-11-08T09:15:00.000Z"  # preserved original ts
    assert item["owner_id"] == "p_01"


def test_worker_failed_causes_api_to_fail_closed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    class DummyFailedWorker:
        worker_failed = True

    client = get_test_client(store, worker_controller=DummyFailedWorker())
    # When worker has failed, API fails closed visibly
    resp = client.get("/inventory")
    assert resp.status_code == 503


async def _run_asgi_request(
    app,
    headers: dict[str, str] | None = None,
    disconnect_after_chunks: int = 1,
    timeout: float = 2.0,
) -> dict:
    header_list = [
        (k.lower().encode("latin1"), v.encode("latin1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/stream",
        "raw_path": b"/stream",
        "query_string": b"",
        "headers": header_list,
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 54321),
    }

    response_start = {}
    response_chunks = []
    chunk_count = 0
    disconnect_event = asyncio.Event()

    async def receive():
        if not hasattr(receive, "_requested"):
            receive._requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal chunk_count
        m_type = message.get("type")
        if m_type == "http.response.start":
            response_start.update(message)
        elif m_type == "http.response.body":
            body = message.get("body", b"")
            if body:
                response_chunks.append(body)
                chunk_count += 1
                if chunk_count >= disconnect_after_chunks:
                    disconnect_event.set()

    app_task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(asyncio.shield(app_task), timeout=timeout)
    except asyncio.TimeoutError:
        disconnect_event.set()
        app_task.cancel()
        with anyio.CancelScope(shield=True):
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass
        raise TimeoutError(f"ASGI app task did not terminate within {timeout}s timeout")
    except BaseException:
        disconnect_event.set()
        app_task.cancel()
        with anyio.CancelScope(shield=True):
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass
        raise
    finally:
        disconnect_event.set()

    return {
        "status": response_start.get("status"),
        "headers": response_start.get("headers", []),
        "body": b"".join(response_chunks).decode("utf-8", errors="replace"),
        "chunks": [c.decode("utf-8", errors="replace") for c in response_chunks],
    }


def test_sse_stream_unknown_last_event_id_returns_400():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)
        cfg = BackendConfig()
        app = create_app(cfg, store)

        res = await _run_asgi_request(app, headers={"Last-Event-ID": "non-existent-uuid"})
        assert res["status"] == 400
        assert "Unknown or invalid Last-Event-ID" in res["body"]

    asyncio.run(_test())


def test_sse_stream_crlf_injection_returns_400():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)
        cfg = BackendConfig()
        app = create_app(cfg, store)

        res = await _run_asgi_request(app, headers={"Last-Event-ID": "uuid_1\r\nInjected-Header: bad"})
        assert res["status"] == 400

    asyncio.run(_test())


def test_sse_stream_initial_and_reconnection():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)

        e1 = make_sample_event("uuid_1", "item_1", "Milk")
        e2 = make_sample_event("uuid_2", "item_2", "Juice")
        for e in (e1, e2):
            store._insert_fridge_event(e)
            store._insert_outbox(e)

        cfg = BackendConfig()
        app = create_app(cfg, store)

        # Initial stream without Last-Event-ID requests exactly 2 chunks to receive both events
        res1 = await _run_asgi_request(app, disconnect_after_chunks=2)
        assert res1["status"] == 200
        assert any(b"text/event-stream" in h[1] for h in res1["headers"] if h[0] == b"content-type")
        assert "id: uuid_1" in res1["body"]
        assert "id: uuid_2" in res1["body"]
        assert "event: fridge.event" in res1["body"]

        # Reconnection with Last-Event-ID: uuid_1 receives strictly greater events (uuid_2)
        res2 = await _run_asgi_request(app, headers={"Last-Event-ID": "uuid_1"}, disconnect_after_chunks=1)
        assert res2["status"] == 200
        assert "id: uuid_2" in res2["body"]
        assert "id: uuid_1" not in res2["body"]

    asyncio.run(_test())


def test_sse_stream_tied_or_backward_timestamps_ordered_by_outbox_id():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)

        # Event 1 with ts in future
        e1 = make_sample_event("uuid_future", "item_1", "Milk", ts="2026-11-08T09:20:00.000Z")
        # Event 2 with ts earlier or tied
        e2 = make_sample_event("uuid_past", "item_2", "Juice", ts="2026-11-08T09:10:00.000Z")

        store._insert_fridge_event(e1)
        store._insert_outbox(e1)
        store._insert_fridge_event(e2)
        store._insert_outbox(e2)

        cfg = BackendConfig()
        app = create_app(cfg, store)

        res = await _run_asgi_request(app, disconnect_after_chunks=1)
        assert res["status"] == 200
        pos1 = res["body"].find("id: uuid_future")
        pos2 = res["body"].find("id: uuid_past")
        assert pos1 != -1 and pos2 != -1
        assert pos1 < pos2, "Stream must order by outbox.id, not event timestamp"

    asyncio.run(_test())


def test_sse_stream_client_disconnect_cleanup_and_in_flight_lock(monkeypatch):
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)
        cfg = BackendConfig()
        app = create_app(cfg, store)

        started = threading.Event()
        release = threading.Event()
        read_calls = [0]
        orig_get_stream = store.get_stream_events

        def blocked_get_stream(after_id, limit=50):
            read_calls[0] += 1
            started.set()
            release.wait(timeout=5.0)
            return orig_get_stream(after_id, limit)

        monkeypatch.setattr(store, "get_stream_events", blocked_get_stream)

        # 1. Test direct task cancellation on safe_read
        safe_read_task = asyncio.create_task(app.state.safe_read(store.get_stream_events, 0, 50))
        assert await asyncio.to_thread(started.wait, 2.0)
        assert app.state.read_lock.locked()

        # Cancel the async reader task
        safe_read_task.cancel()
        await asyncio.sleep(0.01)
        # Task has not finished because safe_read is shielded waiting for OS thread
        assert not safe_read_task.done()
        assert app.state.read_lock.locked()

        # Release blocked query
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await safe_read_task

        # Lock is now released
        assert not app.state.read_lock.locked()

        # 2. Test stream cancellation while read query is in-flight
        started.clear()
        release.clear()
        try:
            stream_task = asyncio.create_task(_run_asgi_request(app, disconnect_after_chunks=1, timeout=3.0))
            assert await asyncio.to_thread(started.wait, 2.0)
            assert app.state.read_lock.locked()

            # Send disconnect / cancellation while thread is still blocked
            stream_task.cancel()
            await asyncio.sleep(0.01)
            # Lock remains held while OS thread is still executing query
            assert app.state.read_lock.locked()
        finally:
            # Release blocked query to prevent hang
            release.set()

        with pytest.raises((asyncio.CancelledError, TimeoutError)):
            await stream_task

        # Lock is released after OS thread finishes
        assert not app.state.read_lock.locked()

        # Verify no further reads occur
        calls_count = read_calls[0]
        await asyncio.sleep(0.05)
        assert read_calls[0] == calls_count

    asyncio.run(_test())


def test_sse_stream_heartbeat_ping():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)
        cfg = BackendConfig()

        curr_time = [0.0]

        def fake_clock():
            return curr_time[0]

        app = create_app(cfg, store, clock_fn=fake_clock)

        async def advance_clock():
            await asyncio.sleep(0.02)
            curr_time[0] = 16.0

        asyncio.create_task(advance_clock())
        res = await _run_asgi_request(app, disconnect_after_chunks=1, timeout=2.0)
        assert res["status"] == 200
        assert ": ping\n\n" in res["body"]

    asyncio.run(_test())


def test_sse_stream_corrupt_event_id_terminates_cleanly():
    async def _test():
        conn = MockPostgresConn()
        store = PostgresStore(conn)

        # Directly populate corrupt event in mock database
        corrupt_ev = make_sample_event("bad\r\nid", "item_1", "Milk")
        conn._committed_fridge_events["bad\r\nid"] = corrupt_ev
        conn._committed_outbox.append({
            "id": 1, "event_id": "bad\r\nid", "topic": "fridge.event",
            "payload": corrupt_ev, "status": "pending", "published_at": None
        })

        cfg = BackendConfig()
        app = create_app(cfg, store)

        res = await _run_asgi_request(app, disconnect_after_chunks=1, timeout=2.0)
        assert res["status"] == 200
        assert "bad\r\nid" not in res["body"]
        assert "Injected" not in res["body"]

    asyncio.run(_test())


def test_get_people_empty_list():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    client = get_test_client(store)

    resp = client.get("/people")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_person_success_and_truthful_unknown_status():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    client = get_test_client(store)

    resp = client.post("/people", json={"person_id": "p_01", "name": "Alice Smith"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["person_id"] == "p_01"
    assert data["name"] == "Alice Smith"
    assert data["enrollment_status"] == "unknown"
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")


def test_create_person_duplicate_returns_409():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    client = get_test_client(store)

    resp1 = client.post("/people", json={"person_id": "p_01", "name": "Alice"})
    assert resp1.status_code == 201

    resp2 = client.post("/people", json={"person_id": "p_01", "name": "Duplicate Alice"})
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"]


def test_create_person_validation_rejects_malformed_and_enrollment_claims():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    client = get_test_client(store)

    # Rejection of un-allowed enrollment claims
    resp = client.post("/people", json={"person_id": "p_01", "name": "Alice", "enrollment_status": "enrolled"})
    assert resp.status_code == 422

    # Invalid person_id
    assert client.post("/people", json={"person_id": "invalid id with space", "name": "Alice"}).status_code == 422
    assert client.post("/people", json={"person_id": 123, "name": "Alice"}).status_code == 422
    assert client.post("/people", json={"person_id": True, "name": "Alice"}).status_code == 422
    assert client.post("/people", json={"person_id": "p_01\n", "name": "Alice"}).status_code == 422

    # Invalid name
    assert client.post("/people", json={"person_id": "p_02", "name": "   "}).status_code == 422
    assert client.post("/people", json={"person_id": "p_02", "name": 456}).status_code == 422
    assert client.post("/people", json={"person_id": "p_02", "name": "Alice\0"}).status_code == 422


def test_get_person_by_id_and_404():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.create_person("p_01", "Alice")
    client = get_test_client(store)

    resp = client.get("/people/p_01")
    assert resp.status_code == 200
    assert resp.json()["person_id"] == "p_01"
    assert resp.json()["name"] == "Alice"
    assert resp.json()["enrollment_status"] == "unknown"

    # Non-existent
    assert client.get("/people/p_99").status_code == 404

    # Invalid path parameter
    assert client.get("/people/invalid%20id").status_code == 422


def test_update_person_name_and_immutable_fields():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.create_person("p_01", "Alice")
    client = get_test_client(store)

    # Successful update
    resp = client.put("/people/p_01", json={"name": "Alice Smith"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice Smith"
    assert resp.json()["person_id"] == "p_01"
    assert resp.json()["enrollment_status"] == "unknown"

    # Cannot update enrollment_status
    resp_bad = client.put("/people/p_01", json={"name": "Alice", "enrollment_status": "enrolled"})
    assert resp_bad.status_code == 422

    # Invalid name
    assert client.put("/people/p_01", json={"name": "  "}).status_code == 422

    # Non-existent
    assert client.put("/people/p_99", json={"name": "Nobody"}).status_code == 404


def test_get_people_deterministic_ordering():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.create_person("p_03", "Charlie")
    store.create_person("p_01", "Alice")
    store.create_person("p_02", "Bob")
    client = get_test_client(store)

    resp = client.get("/people")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert [p["person_id"] for p in data] == ["p_01", "p_02", "p_03"]


def test_people_endpoints_fail_closed_on_worker_failure():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    class DummyFailedWorker:
        worker_failed = True

    client = get_test_client(store, worker_controller=DummyFailedWorker())

    assert client.get("/people").status_code == 503
    assert client.post("/people", json={"person_id": "p_01", "name": "Alice"}).status_code == 503
    assert client.get("/people/p_01").status_code == 503
    assert client.put("/people/p_01", json={"name": "Alice"}).status_code == 503
