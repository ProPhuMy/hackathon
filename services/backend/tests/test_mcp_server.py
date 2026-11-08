"""Unit, protocol, and opt-in live tests for the Fridge Tracker read-only FastMCP server."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.parse
import uuid

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError
import psycopg
import pytest

import fridge_backend.mcp_server
from fridge_backend.mcp_server import (
    TokenBucket,
    create_server,
    validate_backend_url,
)
from io_helpers import get_real_kafka_bootstrap, get_real_postgres_dsn


def decode_mcp_result(result: Any) -> Any:
    """Helper to decode FastMCP server.call_tool (tuple) or ClientSession result."""
    # Direct server.call_tool returns (unstructured_content, structured_content)
    if isinstance(result, tuple) and len(result) == 2:
        structured = result[1]
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    # ClientSession CallToolResult
    if hasattr(result, "structuredContent") and result.structuredContent:
        sc = result.structuredContent
        if isinstance(sc, dict) and "result" in sc:
            return sc["result"]
        return sc
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "result" in parsed:
                    return parsed["result"]
                return parsed
            except Exception:
                return text
    return result


# ---------------------------------------------------------------------------
# 1. URL and IPv6 / Port validation tests
# ---------------------------------------------------------------------------

def test_validate_backend_url():
    # Valid URLs
    assert validate_backend_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert validate_backend_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert validate_backend_url("https://example.com") == "https://example.com"
    assert validate_backend_url("http://localhost:5000") == "http://localhost:5000"

    # Valid IPv6 with preserved brackets
    assert validate_backend_url("http://[::1]:8000") == "http://[::1]:8000"
    assert validate_backend_url("http://[::1]:8000/") == "http://[::1]:8000"
    assert validate_backend_url("https://[2001:db8::1]:443") == "https://[2001:db8::1]:443"

    # Invalid URLs: non-string / empty
    with pytest.raises(ValueError, match="non-empty string"):
        validate_backend_url("")
    with pytest.raises(ValueError, match="non-empty string"):
        validate_backend_url("   ")

    # Invalid scheme
    with pytest.raises(ValueError, match="scheme must be http or https"):
        validate_backend_url("ftp://127.0.0.1:8000")

    # Missing host
    with pytest.raises(ValueError, match="valid host"):
        validate_backend_url("http://")
    with pytest.raises(ValueError, match="valid host"):
        validate_backend_url("http://:8000")
    with pytest.raises(ValueError, match="valid host"):
        validate_backend_url("http://:80/")

    # Credentials rejected without leaking
    with pytest.raises(ValueError, match="user credentials"):
        validate_backend_url("http://user:secret@127.0.0.1:8000")

    # Port out of range / invalid
    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        validate_backend_url("http://127.0.0.1:0")
    with pytest.raises(ValueError, match="Port must be between 1 and 65535|invalid port"):
        validate_backend_url("http://127.0.0.1:65536")
    with pytest.raises(ValueError, match="invalid port"):
        validate_backend_url("http://127.0.0.1:abc")

    # Query strings and fragments rejected
    with pytest.raises(ValueError, match="query parameters or fragments"):
        validate_backend_url("http://127.0.0.1:8000?foo=bar")
    with pytest.raises(ValueError, match="query parameters or fragments"):
        validate_backend_url("http://127.0.0.1:8000#section")

    # Path rejected
    with pytest.raises(ValueError, match="path component"):
        validate_backend_url("http://127.0.0.1:8000/api/v1")


# ---------------------------------------------------------------------------
# 2. Shared cross-tool limiter unit tests
# ---------------------------------------------------------------------------

def test_shared_cross_tool_limiter(monkeypatch):
    async def _test():
        current_time = [1000.0]

        def fake_monotonic() -> float:
            return current_time[0]

        monkeypatch.setattr(fridge_backend.mcp_server, "monotonic", fake_monotonic)

        http_requests = []

        class MockResponse:
            def __init__(self, data: Any):
                self.status_code = 200
                self._data = data

            def json(self) -> Any:
                return self._data

        async def mock_get(self, url, params=None):
            http_requests.append((url, params))
            if "/inventory" in url:
                return MockResponse([])
            if "/events" in url or "/alerts" in url:
                return MockResponse([])
            if "/trends" in url:
                return MockResponse({
                    "start_ts": "2026-11-01T00:00:00.000Z",
                    "end_ts": "2026-11-08T00:00:00.000Z",
                    "owner_id": None,
                    "event_count": 0,
                    "put_count": 0,
                    "take_count": 0,
                    "wrong_owner_count": 0,
                    "uncertain_count": 0,
                    "wrong_owner_by_pair": [],
                    "rankings_truncated": False,
                })
            return MockResponse({})

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        server = create_server("http://127.0.0.1:8000")

        # Ten valid calls across all 4 tools succeed
        await server.call_tool("get_inventory", {})
        await server.call_tool("get_inventory", {})
        await server.call_tool("get_history", {"limit": 10})
        await server.call_tool("get_history", {"limit": 20})
        await server.call_tool("get_alerts", {"limit": 10})
        await server.call_tool("get_alerts", {"limit": 20})
        await server.call_tool("get_trends", {"start_ts": "2026-11-01T00:00:00Z", "end_ts": "2026-11-08T00:00:00Z"})
        await server.call_tool("get_trends", {"start_ts": "2026-11-01T00:00:00Z", "end_ts": "2026-11-08T00:00:00Z"})
        await server.call_tool("get_inventory", {})
        await server.call_tool("get_history", {"limit": 50})

        assert len(http_requests) == 10

        # 11th call rejected immediately with ToolError; NO backend request made
        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await server.call_tool("get_inventory", {})

        assert len(http_requests) == 10  # request count must not increment

        # Advance clock by 0.5s -> 1 token refilled (2 * 0.5 = 1.0)
        current_time[0] += 0.5
        await server.call_tool("get_inventory", {})
        assert len(http_requests) == 11

        # Immediately exhausted again
        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await server.call_tool("get_alerts", {"limit": 10})
        assert len(http_requests) == 11

        # Advance clock by 100s -> capped at 10
        current_time[0] += 100.0
        for _ in range(10):
            await server.call_tool("get_inventory", {})
        assert len(http_requests) == 21

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await server.call_tool("get_trends", {"start_ts": "2026-11-01T00:00:00Z", "end_ts": "2026-11-08T00:00:00Z"})
        assert len(http_requests) == 21

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 3. Tool annotations and schema inspection
# ---------------------------------------------------------------------------

def test_mcp_tool_annotations_and_schemas():
    async def _test():
        server = create_server("http://127.0.0.1:8000")
        tools = await server.list_tools()
        assert len(tools) == 4
        tool_map = {t.name: t for t in tools}

        expected_names = {"get_inventory", "get_history", "get_alerts", "get_trends"}
        assert set(tool_map.keys()) == expected_names

        for name, tool in tool_map.items():
            ann = tool.annotations
            assert ann is not None, f"Tool {name} missing annotations"
            assert ann.readOnlyHint is True
            assert ann.destructiveHint is False
            assert ann.idempotentHint is True
            assert ann.openWorldHint is False

        # Schema checks for StrictInt with ge=1, le=500
        hist_props = tool_map["get_history"].inputSchema.get("properties", {})
        assert "limit" in hist_props
        assert hist_props["limit"].get("minimum") == 1
        assert hist_props["limit"].get("maximum") == 500

        alerts_props = tool_map["get_alerts"].inputSchema.get("properties", {})
        assert "limit" in alerts_props
        assert alerts_props["limit"].get("minimum") == 1
        assert alerts_props["limit"].get("maximum") == 500

        trends_schema = tool_map["get_trends"].inputSchema
        props = trends_schema.get("properties", {})
        assert "start_ts" in props
        assert "end_ts" in props
        assert "owner_id" in props
        assert set(trends_schema.get("required", [])) == {"start_ts", "end_ts"}

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 4. Strict argument validation before network (no HTTP calls)
# ---------------------------------------------------------------------------

def test_tool_strict_validation_before_network(monkeypatch):
    async def _test():
        http_called = []

        async def fail_get(self, url, params=None):
            http_called.append(url)
            raise AssertionError(f"Unexpected HTTP call made to {url}")

        monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)

        server = create_server("http://127.0.0.1:8000")

        # Boolean rejected by StrictInt / validator
        with pytest.raises(ToolError):
            await server.call_tool("get_history", {"limit": True})
        with pytest.raises(ToolError):
            await server.call_tool("get_alerts", {"limit": False})

        # Float rejected by StrictInt / validator
        with pytest.raises(ToolError):
            await server.call_tool("get_history", {"limit": 1.5})

        # Numeric string rejected by StrictInt / validator
        with pytest.raises(ToolError):
            await server.call_tool("get_history", {"limit": "50"})

        # Out-of-bounds limit rejected
        with pytest.raises(ToolError):
            await server.call_tool("get_history", {"limit": 0})
        with pytest.raises(ToolError):
            await server.call_tool("get_history", {"limit": 501})

        # Trends validation
        with pytest.raises(ToolError):
            await server.call_tool("get_trends", {"start_ts": "naive", "end_ts": "2026-11-08T00:00:00Z"})
        with pytest.raises(ToolError):
            await server.call_tool("get_trends", {"start_ts": "2026-11-08T00:00:00Z", "end_ts": "2026-11-01T00:00:00Z"})
        with pytest.raises(ToolError):
            await server.call_tool("get_trends", {"start_ts": "2026-11-01T00:00:00Z", "end_ts": "2026-11-08T00:00:00Z", "owner_id": "bad owner!"})

        assert len(http_called) == 0, "No HTTP requests should have been made for invalid arguments"

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 5. Response sanitization: extras stripped & corrupt types rejected
# ---------------------------------------------------------------------------

def test_response_sanitization_and_field_allowlist(monkeypatch):
    async def _test():
        server = create_server("http://127.0.0.1:8000")

        class MockResponse:
            def __init__(self, status_code: int, data: Any):
                self.status_code = status_code
                self._data = data

            def json(self) -> Any:
                return self._data

        async def mock_get(self, url, params=None):
            if "/inventory" in url:
                return MockResponse(200, [
                    {
                        "item_id": "milk_01",
                        "item_label": "Whole Milk",
                        "owner_id": "p_01",
                        "since_ts": "2026-11-01T00:00:00.000Z",
                        "face_embedding": [0.123, 0.456, 0.789],
                        "face_image": "base64encodedbytes==",
                    }
                ])
            if "/events" in url:
                return MockResponse(200, [
                    {
                        "event_id": "e_1",
                        "topic": "fridge.event",
                        "type": "PUT",
                        "item_id": "milk_01",
                        "item_label": "Whole Milk",
                        "person_id": "p_01",
                        "owner_id": "p_01",
                        "ts": "2026-11-01T00:00:00.000Z",
                        "confidence": 0.92,
                        "status": "ok",
                        "face_crop": "blob...",
                    }
                ])
            if "/trends" in url:
                return MockResponse(200, {
                    "start_ts": "2026-11-01T00:00:00.000Z",
                    "end_ts": "2026-11-08T00:00:00.000Z",
                    "owner_id": None,
                    "event_count": 1,
                    "put_count": 1,
                    "take_count": 0,
                    "wrong_owner_count": 0,
                    "uncertain_count": 0,
                    "wrong_owner_by_pair": [
                        {"person_id": "p_02", "owner_id": "p_01", "count": 1, "extra_biometric": "leak"}
                    ],
                    "rankings_truncated": False,
                    "server_version": "secret_v1",
                })
            return MockResponse(404, {})

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        # Call get_inventory with required empty args dict
        res_inv_raw = await server.call_tool("get_inventory", {})
        inv_items = decode_mcp_result(res_inv_raw)
        assert len(inv_items) == 1
        item = inv_items[0]
        assert set(item.keys()) == {"item_id", "item_label", "owner_id", "since_ts"}
        assert "face_embedding" not in item
        assert "face_image" not in item

        # Call get_history
        res_hist_raw = await server.call_tool("get_history", {"limit": 10})
        events = decode_mcp_result(res_hist_raw)
        ev = events[0]
        assert set(ev.keys()) == {
            "event_id", "topic", "type", "item_id", "item_label",
            "person_id", "owner_id", "ts", "confidence", "status"
        }
        assert "face_crop" not in ev

        # Call get_trends
        res_trends_raw = await server.call_tool("get_trends", {
            "start_ts": "2026-11-01T00:00:00Z",
            "end_ts": "2026-11-08T00:00:00Z",
        })
        trends = decode_mcp_result(res_trends_raw)
        assert "server_version" not in trends
        assert set(trends["wrong_owner_by_pair"][0].keys()) == {"person_id", "owner_id", "count"}

    asyncio.run(_test())


def test_corrupt_nested_response_rejected_without_secret_leak(monkeypatch):
    async def _test():
        server = create_server("http://127.0.0.1:8000")

        secret_marker = "SUPER_SECRET_EMBEDDING_MARKER_12345"

        class MockResponse:
            def __init__(self, data: Any):
                self.status_code = 200
                self._data = data

            def json(self) -> Any:
                return self._data

        # Upstream returns dict with secret marker instead of string for scalar item_label
        corrupt_inventory = [
            {
                "item_id": "milk_01",
                "item_label": {"nested": secret_marker},
                "owner_id": "p_01",
                "since_ts": "2026-11-01T00:00:00.000Z",
            }
        ]

        async def mock_get(self, url, params=None):
            return MockResponse(corrupt_inventory)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        with pytest.raises(ToolError) as exc_info:
            await server.call_tool("get_inventory", {})

        err_msg = str(exc_info.value)
        assert "unexpected inventory structure" in err_msg
        assert secret_marker not in err_msg, "Error message must not dump corrupted response payload"

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 6. AsyncClient lifecycle: closes on success, error, and cancellation
# ---------------------------------------------------------------------------

def test_async_client_lifecycle_closes(monkeypatch):
    async def _test():
        server = create_server("http://127.0.0.1:8000")
        clients_seen = []

        orig_init = httpx.AsyncClient.__init__

        def spy_init(self, *args, **kwargs):
            clients_seen.append(self)
            orig_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)

        # 1. Success case
        async def mock_get_ok(self, url, params=None):
            return httpx.Response(200, json=[])

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_ok)
        await server.call_tool("get_inventory", {})
        assert len(clients_seen) == 1
        assert clients_seen[0].is_closed

        # 2. HTTP error case
        clients_seen.clear()

        async def mock_get_500(self, url, params=None):
            return httpx.Response(500, json={"error": "server error"})

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_500)
        with pytest.raises(ToolError):
            await server.call_tool("get_inventory", {})
        assert len(clients_seen) == 1
        assert clients_seen[0].is_closed

        # 3. Cancellation case
        clients_seen.clear()

        async def mock_get_slow(self, url, params=None):
            await asyncio.sleep(10.0)
            return httpx.Response(200, json=[])

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_slow)
        task = asyncio.create_task(server.call_tool("get_inventory", {}))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(clients_seen) == 1
        assert clients_seen[0].is_closed

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 7. Real STDIO subprocess test using official MCP SDK client
# ---------------------------------------------------------------------------

class FixtureHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/inventory":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([
                {"item_id": "item_1", "item_label": "Milk", "owner_id": "p_01", "since_ts": "2026-11-01T00:00:00.000Z"}
            ]).encode("utf-8"))
        elif parsed.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([
                {"event_id": "e_1", "topic": "fridge.event", "type": "PUT", "item_id": "item_1", "item_label": "Milk", "person_id": "p_01", "owner_id": "p_01", "ts": "2026-11-01T00:00:00.000Z", "confidence": 0.9, "status": "ok"}
            ]).encode("utf-8"))
        elif parsed.path == "/alerts":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([
                {"event_id": "e_2", "topic": "fridge.event", "type": "TAKE", "item_id": "item_1", "item_label": "Milk", "person_id": "p_02", "owner_id": "p_01", "ts": "2026-11-02T00:00:00.000Z", "confidence": 0.85, "status": "wrong_owner"}
            ]).encode("utf-8"))
        elif parsed.path == "/trends":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "start_ts": "2026-11-01T00:00:00.000Z",
                "end_ts": "2026-11-08T00:00:00.000Z",
                "owner_id": None,
                "event_count": 2,
                "put_count": 1,
                "take_count": 1,
                "wrong_owner_count": 1,
                "uncertain_count": 0,
                "wrong_owner_by_pair": [
                    {"person_id": "p_02", "owner_id": "p_01", "count": 1, "hidden_vector": [1, 2, 3]}
                ],
                "rankings_truncated": False,
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        # Fixture server does NOT accept POST; assert unknown tools do not POST
        self.send_response(405)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_stdio_subprocess_protocol_official_client():
    async def _test():
        fixture_server = http.server.HTTPServer(("127.0.0.1", 0), FixtureHTTPHandler)
        port = fixture_server.server_port
        th = threading.Thread(target=fixture_server.serve_forever, daemon=True)
        th.start()

        env = os.environ.copy()
        src_dir = str(Path(__file__).resolve().parents[1] / "src")
        cur_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{cur_pp}" if cur_pp else src_dir
        env["PYTHONUNBUFFERED"] = "1"

        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "fridge_backend.mcp_server", "--backend-url", f"http://127.0.0.1:{port}"],
                env=env,
            )

            # Bounded scope for subprocess stdio client
            async with asyncio.timeout(15.0):
                async with stdio_client(params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        init_res = await session.initialize()
                        assert init_res is not None

                        tools_res = await session.list_tools()
                        tool_map = {t.name: t for t in tools_res.tools}
                        assert set(tool_map.keys()) == {"get_inventory", "get_history", "get_alerts", "get_trends"}

                        # Verify schema limits (minimum 1, maximum 500)
                        hist_limit_schema = tool_map["get_history"].inputSchema["properties"]["limit"]
                        assert hist_limit_schema.get("minimum") == 1
                        assert hist_limit_schema.get("maximum") == 500

                        # 1. get_inventory
                        inv_res = await session.call_tool("get_inventory")
                        assert not inv_res.isError
                        inv_data = decode_mcp_result(inv_res)
                        assert len(inv_data) == 1
                        assert inv_data[0]["item_id"] == "item_1"

                        # 2. get_history
                        hist_res = await session.call_tool("get_history", {"limit": 10})
                        assert not hist_res.isError
                        hist_data = decode_mcp_result(hist_res)
                        assert len(hist_data) == 1
                        assert hist_data[0]["event_id"] == "e_1"

                        # 3. get_alerts
                        alerts_res = await session.call_tool("get_alerts", {"limit": 10})
                        assert not alerts_res.isError
                        alerts_data = decode_mcp_result(alerts_res)
                        assert len(alerts_data) == 1
                        assert alerts_data[0]["status"] == "wrong_owner"

                        # 4. get_trends with sub-field sanitization
                        trends_res = await session.call_tool("get_trends", {
                            "start_ts": "2026-11-01T00:00:00Z",
                            "end_ts": "2026-11-08T00:00:00Z",
                        })
                        assert not trends_res.isError
                        trends_data = decode_mcp_result(trends_res)
                        assert "hidden_vector" not in trends_data["wrong_owner_by_pair"][0]
                        assert set(trends_data["wrong_owner_by_pair"][0].keys()) == {"person_id", "owner_id", "count"}

                        # 5. Invalid boolean argument -> isError is True
                        err_res1 = await session.call_tool("get_history", {"limit": True})
                        assert err_res1.isError

                        err_res2 = await session.call_tool("get_alerts", {"limit": False})
                        assert err_res2.isError

                        # 6. Unknown tool call -> isError is True
                        err_res3 = await session.call_tool("nonexistent_write_tool", {})
                        assert err_res3.isError
        finally:
            fixture_server.shutdown()
            fixture_server.server_close()
            th.join(timeout=2.0)

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 8. Opt-in live MCP-to-real-backend test
# ---------------------------------------------------------------------------

def test_live_mcp_to_backend(tmp_path: Path):
    test_dsn = get_real_postgres_dsn()
    test_kafka = get_real_kafka_bootstrap()
    if not test_dsn or not test_kafka:
        pytest.skip("Live test requires TEST_POSTGRES_DSN and TEST_KAFKA_BOOTSTRAP_SERVERS")

    from test_live_end_to_end import _make_schema_dsn, _get_free_port, _start_backend
    import confluent_kafka.admin
    from fridge_backend.store import PostgresStore
    from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION

    # Full UUID for own schema and unique test topics
    run_id = uuid.uuid4().hex
    schema_name = f"test_mcp_{run_id}"
    schema_dsn = _make_schema_dsn(test_dsn, schema_name)
    person_topic = f"person.seen_mcp_{run_id}"
    item_topic = f"item.event_mcp_{run_id}"
    group_id = f"test_mcp_group_{run_id}"
    backend_port = _get_free_port()
    log_path = tmp_path / "backend_mcp.log"

    admin_client: confluent_kafka.admin.AdminClient | None = None
    proc: subprocess.Popen | None = None

    try:
        # Create isolated schema
        with psycopg.connect(test_dsn, autocommit=True) as setup_conn:
            with setup_conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema_name};")

        admin_client = confluent_kafka.admin.AdminClient({"bootstrap.servers": test_kafka})
        new_topics = [
            confluent_kafka.admin.NewTopic(person_topic, num_partitions=1, replication_factor=1),
            confluent_kafka.admin.NewTopic(item_topic, num_partitions=1, replication_factor=1),
        ]
        for topic, f in admin_client.create_topics(new_topics, operation_timeout=10.0).items():
            f.result(timeout=10.0)

        # PRE-SEED schema BEFORE starting backend using real Matcher + store.handle_input/tick
        # This guarantees full journal/events.py recovery consistency without an active second writer
        with psycopg.connect(test_dsn, autocommit=True) as setup_conn:
            preseed_store = PostgresStore(setup_conn, schema=schema_name)
            preseed_store.init_db()
            preseed_store.check_or_init_version(MATCHER_VERSION)
            preseed_store.create_person("p_01", "Alice")

            real_matcher = Matcher(MatcherConfig())

            t0 = "2026-11-02T10:00:00.000Z"
            t1 = "2026-11-02T10:00:01.000Z"
            t2 = "2026-11-02T10:00:02.000Z"
            t3 = "2026-11-02T10:00:03.000Z"
            t_tick = "2026-11-02T10:00:11.000Z"

            p1_ev = {"event_id": f"p1_{run_id}", "topic": "person.seen", "track_id": 1, "person_id": "p_01", "ts": t0, "confidence": 0.94}
            put_ev = {"event_id": f"put_{run_id}", "topic": "item.event", "type": "PUT", "item_id": "item_042", "item_label": "milk carton", "ts": t1, "confidence": 0.90}
            p2_ev = {"event_id": f"p2_{run_id}", "topic": "person.seen", "track_id": 2, "person_id": "p_02", "ts": t2, "confidence": 0.91}
            take_ev = {"event_id": f"take_{run_id}", "topic": "item.event", "type": "TAKE", "item_id": "item_042", "item_label": "milk carton", "ts": t3, "confidence": 0.87}

            preseed_store.handle_input("person", p1_ev, real_matcher)
            preseed_store.handle_input("item", put_ev, real_matcher)
            preseed_store.handle_input("person", p2_ev, real_matcher)
            preseed_store.handle_input("item", take_ev, real_matcher)
            preseed_store.handle_tick(t_tick, real_matcher)

        # Start ONE backend subprocess; it replays the valid journal, publishes outbox, and serves HTTP
        proc = _start_backend(schema_dsn, test_kafka, group_id, person_topic, item_topic, backend_port, log_path)

        # Await outbox published before baseline snapshot (require pending count 0 AND published count 2)
        deadline = time.monotonic() + 30.0
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            outbox_ready = False
            pending_cnt = -1
            published_cnt = -1
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    log_content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
                    raise RuntimeError(f"Backend exited prematurely with code {proc.returncode}:\n{log_content}")
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox WHERE status = 'pending'")
                    pending_cnt = cur.fetchone()[0]
                    cur.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox WHERE status = 'published'")
                    published_cnt = cur.fetchone()[0]
                    if pending_cnt == 0 and published_cnt == 2:
                        outbox_ready = True
                        break
                time.sleep(0.5)

            if not outbox_ready:
                log_content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
                raise TimeoutError(
                    f"Outbox did not reach 0 pending and 2 published before timeout (pending={pending_cnt}, published={published_cnt}):\n{log_content}"
                )

            # Capture complete baseline rows (SELECT * ordered by PK for all stable tables)
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {schema_name}.fridge_events ORDER BY event_id")
                fe_baseline = cur.fetchall()
                cur.execute(f"SELECT * FROM {schema_name}.outbox ORDER BY id")
                outbox_baseline = cur.fetchall()
                cur.execute(f"SELECT * FROM {schema_name}.people ORDER BY person_id")
                people_baseline = cur.fetchall()
                cur.execute(f"SELECT * FROM {schema_name}.matcher_version ORDER BY id")
                version_baseline = cur.fetchall()
                cur.execute(f"SELECT * FROM {schema_name}.matcher_journal WHERE kind != 'tick' ORDER BY seq")
                nontick_journal_baseline = cur.fetchall()

            assert len(people_baseline) == 1
            assert len(fe_baseline) == 2

        async def _run_mcp_client():
            env = os.environ.copy()
            src_dir = str(Path(__file__).resolve().parents[1] / "src")
            cur_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{cur_pp}" if cur_pp else src_dir
            env["PYTHONUNBUFFERED"] = "1"

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "fridge_backend.mcp_server", "--backend-url", f"http://127.0.0.1:{backend_port}"],
                env=env,
            )

            async with asyncio.timeout(30.0):
                async with stdio_client(params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()

                        # Compare inventory
                        inv_res = await session.call_tool("get_inventory")
                        assert not inv_res.isError
                        mcp_inv = decode_mcp_result(inv_res)
                        http_inv = httpx.get(f"http://127.0.0.1:{backend_port}/inventory", timeout=5.0).json()
                        assert http_inv == []
                        assert mcp_inv == http_inv

                        # Compare history
                        hist_res = await session.call_tool("get_history", {"limit": 50})
                        assert not hist_res.isError
                        mcp_hist = decode_mcp_result(hist_res)
                        http_hist = httpx.get(f"http://127.0.0.1:{backend_port}/events?limit=50", timeout=5.0).json()
                        assert len(http_hist) == 2
                        assert http_hist[0]["type"] == "TAKE"
                        assert http_hist[0]["person_id"] == "p_02"
                        assert http_hist[0]["owner_id"] == "p_01"
                        assert http_hist[0]["status"] == "wrong_owner"
                        assert http_hist[1]["type"] == "PUT"
                        assert http_hist[1]["person_id"] == "p_01"
                        assert http_hist[1]["owner_id"] == "p_01"
                        assert http_hist[1]["status"] == "ok"
                        assert mcp_hist == http_hist

                        # Compare alerts
                        alerts_res = await session.call_tool("get_alerts", {"limit": 50})
                        assert not alerts_res.isError
                        mcp_alerts = decode_mcp_result(alerts_res)
                        http_alerts = httpx.get(f"http://127.0.0.1:{backend_port}/alerts?limit=50", timeout=5.0).json()
                        assert len(http_alerts) == 1
                        assert http_alerts[0]["status"] == "wrong_owner"
                        assert http_alerts[0]["person_id"] == "p_02"
                        assert http_alerts[0]["owner_id"] == "p_01"
                        assert mcp_alerts == http_alerts

                        # Compare trends
                        trends_res = await session.call_tool("get_trends", {
                            "start_ts": "2026-11-01T00:00:00Z",
                            "end_ts": "2026-11-08T00:00:00Z",
                        })
                        assert not trends_res.isError
                        mcp_trends = decode_mcp_result(trends_res)
                        http_trends = httpx.get(
                            f"http://127.0.0.1:{backend_port}/trends?start_ts=2026-11-01T00:00:00Z&end_ts=2026-11-08T00:00:00Z",
                            timeout=5.0,
                        ).json()
                        assert http_trends["event_count"] == 2
                        assert http_trends["wrong_owner_count"] == 1
                        assert http_trends["wrong_owner_by_pair"] == [
                            {"person_id": "p_02", "owner_id": "p_01", "count": 1}
                        ]
                        assert mcp_trends == http_trends

        asyncio.run(_run_mcp_client())

        # Verify read-only guarantee: row-for-row match against baseline snapshot
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {schema_name}.fridge_events ORDER BY event_id")
                assert cur.fetchall() == fe_baseline

                cur.execute(f"SELECT * FROM {schema_name}.outbox ORDER BY id")
                assert cur.fetchall() == outbox_baseline

                cur.execute(f"SELECT * FROM {schema_name}.people ORDER BY person_id")
                assert cur.fetchall() == people_baseline

                cur.execute(f"SELECT * FROM {schema_name}.matcher_version ORDER BY id")
                assert cur.fetchall() == version_baseline

                # Non-tick journal rows remain untouched (idle ticks may append during run)
                cur.execute(f"SELECT * FROM {schema_name}.matcher_journal WHERE kind != 'tick' ORDER BY seq")
                assert cur.fetchall() == nontick_journal_baseline

    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except Exception:
                pass

        # Clean up and await topic delete futures on own UUID input topics only
        if admin_client is not None:
            delete_futures = admin_client.delete_topics([person_topic, item_topic], operation_timeout=10.0)
            for topic, f in delete_futures.items():
                try:
                    f.result(timeout=10.0)
                except Exception:
                    pass

        with psycopg.connect(test_dsn, autocommit=True) as cleanup_conn:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
