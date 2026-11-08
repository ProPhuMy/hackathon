"""Opt-in live PostgreSQL and Redpanda end-to-end subprocess restart smoke test.

Requires live infrastructure via TEST_POSTGRES_DSN and TEST_KAFKA_BOOTSTRAP_SERVERS.
Default (no live services) skips safely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import urllib.parse
import uuid

import confluent_kafka
import confluent_kafka.admin
import httpx
import psycopg
import pytest


def _make_schema_dsn(base_dsn: str, schema: str) -> str:
    parsed = urllib.parse.urlsplit(base_dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError("TEST_POSTGRES_DSN must be a postgresql:// or postgres:// URI")
    q_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    q_dict = {k: v for k, v in q_pairs if k != "options"}
    q_dict["options"] = f"-csearch_path={schema}"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(q_dict), parsed.fragment))


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_backend(schema_dsn: str, kafka_boot: str, group_id: str, p_topic: str, i_topic: str, port: int, log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["POSTGRES_DSN"] = schema_dsn
    env["KAFKA_BOOTSTRAP_SERVERS"] = kafka_boot
    env["KAFKA_GROUP_ID"] = group_id
    env["PERSON_TOPIC"] = p_topic
    env["ITEM_TOPIC"] = i_topic
    env["API_PORT"] = str(port)
    env["API_HOST"] = "127.0.0.1"
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    cur_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{cur_pp}" if cur_pp else src_dir

    env["PYTHONUNBUFFERED"] = "1"
    with open(log_path, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", "from fridge_backend.main import main_entry; main_entry()"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    try:
        ready = False
        start = time.monotonic()
        while time.monotonic() - start < 45.0:
            if proc.poll() is not None:
                raise RuntimeError(f"Backend exited early (code {proc.returncode}). Log ({log_path}):\n{log_path.read_text(errors='replace')}")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/inventory", timeout=1.0).status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not ready:
            raise TimeoutError(f"Backend failed HTTP readiness within 45s. Log ({log_path}):\n{log_path.read_text(errors='replace')}")

        return proc
    except BaseException:
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5.0)
            except Exception:
                pass
        else:
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
        raise


def test_live_subprocess_restart_smoke(tmp_path: Path) -> None:
    test_dsn = os.environ.get("TEST_POSTGRES_DSN")
    test_kafka = os.environ.get("TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not test_dsn or not test_kafka:
        pytest.skip("Live test requires TEST_POSTGRES_DSN and TEST_KAFKA_BOOTSTRAP_SERVERS")

    run_id = uuid.uuid4().hex
    schema_name = f"test_e2e_{run_id}"
    schema_dsn = _make_schema_dsn(test_dsn, schema_name)
    person_topic = f"person.seen_{run_id}"
    item_topic = f"item.event_{run_id}"
    group_id = f"test_group_{run_id}"
    port = _get_free_port()
    log_path = tmp_path / "backend.log"

    admin_client: confluent_kafka.admin.AdminClient | None = None
    test_conn: psycopg.Connection | None = None
    proc: subprocess.Popen | None = None

    try:
        test_conn = psycopg.connect(test_dsn, autocommit=True)
        with test_conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema_name};")

        admin_client = confluent_kafka.admin.AdminClient({"bootstrap.servers": test_kafka})
        new_topics = [
            confluent_kafka.admin.NewTopic(person_topic, num_partitions=1, replication_factor=1),
            confluent_kafka.admin.NewTopic(item_topic, num_partitions=1, replication_factor=1),
        ]
        for topic, f in admin_client.create_topics(new_topics, operation_timeout=10.0).items():
            f.result(timeout=10.0)

        # 1. First process startup & readiness
        proc = _start_backend(schema_dsn, test_kafka, group_id, person_topic, item_topic, port, log_path)

        # 2. Timing: t0 = now + 75s after readiness so consumer group rebalance/session timeouts survive
        t0_dt = datetime.now(timezone.utc) + timedelta(seconds=75)
        t0 = t0_dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        t1 = (t0_dt + timedelta(seconds=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        t2 = (t0_dt + timedelta(seconds=2)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        t3 = (t0_dt + timedelta(seconds=3)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        p1_id, put_id = f"p_live_1_{run_id}", f"i_live_put_{run_id}"
        p2_id, take_id = f"p_live_2_{run_id}", f"i_live_take_{run_id}"

        p1_ev = {"event_id": p1_id, "topic": "person.seen", "track_id": 1, "person_id": "p_01", "ts": t0, "confidence": 0.94}
        put_ev = {"event_id": put_id, "topic": "item.event", "type": "PUT", "item_id": "item_042", "item_label": "milk carton", "ts": t1, "confidence": 0.90}
        p2_ev = {"event_id": p2_id, "topic": "person.seen", "track_id": 2, "person_id": "p_02", "ts": t2, "confidence": 0.91}
        take_ev = {"event_id": take_id, "topic": "item.event", "type": "TAKE", "item_id": "item_042", "item_label": "milk carton", "ts": t3, "confidence": 0.87}

        last_offsets: dict[tuple[str, int], int] = {}

        def on_delivery(err: Any, msg: Any) -> None:
            if err:
                raise RuntimeError(f"Produce delivery failed: {err}")
            last_offsets[(msg.topic(), msg.partition())] = msg.offset()

        producer = confluent_kafka.Producer({"bootstrap.servers": test_kafka})

        def publish(topic: str, key: str, payload: dict) -> None:
            producer.produce(topic, key=key, value=json.dumps(payload), on_delivery=on_delivery)
            rem = producer.flush(timeout=10.0)
            assert rem == 0, f"Producer flush timed out with {rem} unsent messages"

        def poll_db(sql: str, expected_count: int, timeout: float = 20.0) -> None:
            start = time.monotonic()
            while time.monotonic() - start < timeout:
                with test_conn.cursor() as cur:
                    cur.execute(sql)
                    row = cur.fetchone()
                    if row is not None and row[0] == expected_count:
                        return
                time.sleep(0.3)
            raise TimeoutError(f"DB check timed out after {timeout}s ({sql}). Log ({log_path}):\n{log_path.read_text(errors='replace')}")

        # Publish p1 and wait journaled (initial stage: 20s)
        publish(person_topic, p1_id, p1_ev)
        poll_db(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = '{p1_id}'", 1, timeout=20.0)

        # Publish PUT and wait journaled (initial stage: 20s)
        publish(item_topic, put_id, put_ev)
        poll_db(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = '{put_id}'", 1, timeout=20.0)

        # Verify PUT still pending in window (0 outputs)
        with test_conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events")
            assert cur.fetchone()[0] == 0

        # Abrupt crash (kill -9 equivalent, no graceful terminate)
        proc.kill()
        proc.wait(timeout=10.0)
        proc = None

        # 3. Restart same schema, consumer group, and port
        proc = _start_backend(schema_dsn, test_kafka, group_id, person_topic, item_topic, port, log_path)

        # Publish p2 and wait journaled (restart rebalance can take up to 45s; wait 75s)
        publish(person_topic, p2_id, p2_ev)
        poll_db(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = '{p2_id}'", 1, timeout=75.0)

        # Publish TAKE
        publish(item_topic, take_id, take_ev)

        # Redeliver all four original IDs
        publish(person_topic, p1_id, p1_ev)
        publish(item_topic, put_id, put_ev)
        publish(person_topic, p2_id, p2_ev)
        publish(item_topic, take_id, take_ev)

        # Assert last_offsets covers BOTH unique input partitions before checking committed offsets
        expected_parts = {(person_topic, 0), (item_topic, 0)}
        assert set(last_offsets.keys()) == expected_parts, f"Expected offsets for {expected_parts}, got {set(last_offsets.keys())}"

        # Probe committed offsets without subscribing/joining the group (bound 75s)
        probe = confluent_kafka.Consumer({"bootstrap.servers": test_kafka, "group.id": group_id, "enable.auto.commit": False})
        try:
            p_start = time.monotonic()
            committed_ok = False
            while time.monotonic() - p_start < 75.0:
                tps = [confluent_kafka.TopicPartition(t, p) for (t, p) in last_offsets.keys()]
                checked = probe.committed(tps, timeout=10.0)
                if all(tp.offset is not None and tp.offset > last_offsets[(tp.topic, tp.partition)] for tp in checked):
                    committed_ok = True
                    break
                time.sleep(0.5)
            if not committed_ok:
                raise TimeoutError("Committed offsets did not exceed duplicate messages within 75s")
        finally:
            probe.close()

        # 4. Wait for idle ticks to finalize outputs (~75s + 10s = ~85s total elapsed; bound 150s)
        poll_db(f"SELECT COUNT(*) FROM {schema_name}.fridge_events", 2, timeout=150.0)

        # Verify outbox published
        poll_db(f"SELECT COUNT(*) FROM {schema_name}.outbox WHERE status = 'published'", 2, timeout=15.0)
        with test_conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox")
            assert cur.fetchone()[0] == 2

        # 5. HTTP checks
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as client:
            res_events = client.get("/events")
            res_events.raise_for_status()
            events = res_events.json()
            assert len(events) == 2, f"Expected exactly 2 events in isolated schema, got {len(events)}"
            put_out = next(e for e in events if e["event_id"] == put_id)
            take_out = next(e for e in events if e["event_id"] == take_id)
            assert put_out["person_id"] == "p_01" and put_out["owner_id"] == "p_01" and put_out["status"] == "ok"
            assert abs(put_out["confidence"] - 0.5423) <= 1e-4
            assert take_out["person_id"] == "p_02" and take_out["owner_id"] == "p_01" and take_out["status"] == "wrong_owner"
            assert abs(take_out["confidence"] - 0.8282) <= 1e-4

            res_inv = client.get("/inventory")
            res_inv.raise_for_status()
            assert res_inv.json() == []

            res_alerts = client.get("/alerts")
            res_alerts.raise_for_status()
            alerts = res_alerts.json()
            assert len(alerts) == 1, f"Expected exactly 1 alert in isolated schema, got {len(alerts)}"
            assert alerts[0]["event_id"] == take_id and alerts[0]["status"] == "wrong_owner"

            res_post_p = client.post("/people", json={"person_id": "p_01", "name": "Alice"})
            res_post_p.raise_for_status()
            assert res_post_p.status_code == 201 and res_post_p.json()["enrollment_status"] == "unknown"

            res_get_p = client.get("/people")
            res_get_p.raise_for_status()
            assert any(p["person_id"] == "p_01" for p in res_get_p.json())

        # 6. Broker consumer checks on fridge.event (assign all partitions, filter own IDs)
        reader = confluent_kafka.Consumer({
            "bootstrap.servers": test_kafka,
            "group.id": f"reader_{run_id}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        })
        try:
            meta = reader.list_topics("fridge.event", timeout=10.0)
            t_meta = meta.topics.get("fridge.event")
            assert t_meta is not None, "fridge.event topic not found"
            reader.assign([confluent_kafka.TopicPartition("fridge.event", p, confluent_kafka.OFFSET_BEGINNING) for p in t_meta.partitions.keys()])

            found: dict[str, dict] = {}
            r_start = time.monotonic()
            while time.monotonic() - r_start < 20.0 and len(found) < 2:
                msg = reader.poll(timeout=1.0)
                if msg is None or msg.error():
                    continue
                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                    if payload.get("event_id") in (put_id, take_id):
                        found[payload["event_id"]] = payload
                except Exception:
                    pass
            assert set(found.keys()) == {put_id, take_id}
            assert found[put_id] == put_out
            assert found[take_id] == take_out
        finally:
            reader.close()

        # 7. Deduplication in DB: exactly 1 journal row per input ID and 1 stored output per item ID
        with test_conn.cursor() as cur:
            for eid in (p1_id, put_id, p2_id, take_id):
                cur.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = %s", (eid,))
                assert cur.fetchone()[0] == 1
            cur.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events")
            assert cur.fetchone()[0] == 2
            for out_id in (put_id, take_id):
                cur.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events WHERE event_id = %s", (out_id,))
                assert cur.fetchone()[0] == 1

    finally:
        cleanup_errors: list[str] = []
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5.0)
            except Exception as exc:
                cleanup_errors.append(f"Subprocess kill failed: {exc}")
        if test_conn is not None:
            try:
                with test_conn.cursor() as cur:
                    cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
            except Exception as exc:
                cleanup_errors.append(f"DROP SCHEMA failed: {exc}")
            try:
                test_conn.close()
            except Exception as exc:
                cleanup_errors.append(f"Closing test_conn failed: {exc}")
        if admin_client is not None:
            try:
                fs = admin_client.delete_topics([person_topic, item_topic], operation_timeout=10.0)
                for t_name, f in fs.items():
                    try:
                        f.result(timeout=10.0)
                    except Exception as exc:
                        cleanup_errors.append(f"delete_topic({t_name}) failed: {exc}")
            except Exception as exc:
                cleanup_errors.append(f"delete_topics call failed: {exc}")

        if cleanup_errors:
            print(f"Cleanup errors for {schema_name}:\n" + "\n".join(cleanup_errors), file=sys.stderr)
