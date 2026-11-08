"""End-to-end integration tests: fake_events scenario, pending-window restart,
dedup redelivery, and separated opt-in live Postgres tests.
"""

import copy
import json
from pathlib import Path
import sys
import uuid
import pytest

from io_helpers import (
    MockKafkaConsumer,
    MockKafkaProducer,
    MockKafkaMessage,
    MockPostgresConn,
    get_real_postgres_dsn,
)
from fridge_backend.config import BackendConfig
from fridge_backend.store import PostgresStore, VersionMismatchError
from fridge_backend.main import EngineController
from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION


def _import_fake_events_module():
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "tools" / "fake_events.py"
        if cand.is_file():
            sys.path.insert(0, str(parent / "tools"))
            import fake_events
            return fake_events
    raise FileNotFoundError("Could not find tools/fake_events.py")


def test_e2e_fake_events_scenario_deterministic():
    """Runs the exact tools/fake_events.py scenario with true 1-second cadence
    (p1 at t0, PUT at t1, p2 at t2, TAKE at t3) through EngineController with Claude's
    real Matcher and idle tick at t11. Verifies:
      1. Canonical output count is exactly 2.
      2. First output is PUT milk carton by p_01, status 'ok'.
      3. Second output is TAKE milk carton by p_02, status 'wrong_owner'.
      4. Final inventory is empty ([]).
      5. Alerts endpoint returns exactly 1 alert ('wrong_owner').
    """
    fake_events = _import_fake_events_module()

    cfg = BackendConfig(tick_interval_ms=1000)
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    producer = MockKafkaProducer()

    # Collect fake events from scenario
    scenario_events = list(fake_events.scenario())
    assert len(scenario_events) == 4

    p1_ev, item1_ev, p2_ev, item2_ev = scenario_events
    # Exact 1-second cadence
    p1_ev["ts"] = "2026-11-08T09:15:00.000Z"     # t0
    item1_ev["ts"] = "2026-11-08T09:15:01.000Z"  # t1
    p2_ev["ts"] = "2026-11-08T09:15:02.000Z"     # t2
    item2_ev["ts"] = "2026-11-08T09:15:03.000Z"  # t3

    messages = [
        MockKafkaMessage(topic=p1_ev["topic"], value=json.dumps(p1_ev), offset=1),
        MockKafkaMessage(topic=item1_ev["topic"], value=json.dumps(item1_ev), offset=2),
        MockKafkaMessage(topic=p2_ev["topic"], value=json.dumps(p2_ev), offset=3),
        MockKafkaMessage(topic=item2_ev["topic"], value=json.dumps(item2_ev), offset=4),
    ]
    consumer = MockKafkaConsumer(messages)

    simulated_now = ["2026-11-08T09:15:00.000Z"]
    mono_time = [0.0]

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
        now_ts_fn=lambda: simulated_now[0],
        clock_fn=lambda: mono_time[0],
    )

    # Step 1: person 1 arrives at t0
    mono_time[0] = 0.0
    simulated_now[0] = "2026-11-08T09:15:00.000Z"
    controller.step(poll_timeout=0.01)

    # Step 2: item 1 (PUT) arrives at t1 - pending in window!
    mono_time[0] = 1.0
    simulated_now[0] = "2026-11-08T09:15:01.000Z"
    controller.step(poll_timeout=0.01)
    assert len(producer.published_messages) == 0

    # Step 3: person 2 arrives at t2 (person_wm = 09:15:02 < item1.ts + 4000ms = 09:15:05)
    # PUT remains pending in window!
    mono_time[0] = 2.0
    simulated_now[0] = "2026-11-08T09:15:02.000Z"
    controller.step(poll_timeout=0.01)
    assert len(producer.published_messages) == 0

    # Step 4: item 2 (TAKE) arrives at t3 - pending in window!
    mono_time[0] = 3.0
    simulated_now[0] = "2026-11-08T09:15:03.000Z"
    controller.step(poll_timeout=0.01)
    assert len(producer.published_messages) == 0

    # Step 5: advance clock to t11 (now >= item1.ts + 7000ms and now >= item2.ts + 7000ms)
    # Idle tick finalizes ready items in sorted (ts, event_id) order: PUT then TAKE!
    mono_time[0] = 11.0
    simulated_now[0] = "2026-11-08T09:15:11.000Z"
    controller.step(poll_timeout=0.01)

    # Assert exactly 2 canonical outputs emitted
    assert len(producer.published_messages) == 2

    put_out = producer.published_messages[0][2]
    assert put_out["type"] == "PUT"
    assert put_out["item_id"] == "item_042"
    assert put_out["owner_id"] == "p_01"
    assert put_out["person_id"] == "p_01"
    assert put_out["status"] == "ok"

    take_out = producer.published_messages[1][2]
    assert take_out["type"] == "TAKE"
    assert take_out["item_id"] == "item_042"
    assert take_out["person_id"] == "p_02"
    assert take_out["owner_id"] == "p_01"
    assert take_out["status"] == "wrong_owner"

    # Verify inventory is completely empty (item was taken out)
    inv = store.get_inventory()
    assert inv == []

    # Verify alerts contains exactly 1 alert (wrong_owner)
    alerts = store.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["status"] == "wrong_owner"
    assert alerts[0]["event_id"] == take_out["event_id"]


def test_restart_mid_run_pending_window_preserves_outputs():
    """Verify that restarting mid-run with an item still pending in the Matcher window
    preserves state across journal replay and finalizes correctly with zero duplicate emissions,
    asserting on public observable outputs.
    """
    cfg = BackendConfig(tick_interval_ms=1000)
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    producer1 = MockKafkaProducer()

    p1 = {
        "event_id": "p_mid_1", "topic": "person.seen", "track_id": 1,
        "person_id": "p_01", "ts": "2026-11-08T09:15:00.000Z", "confidence": 0.94
    }
    i1 = {
        "event_id": "i_mid_1", "topic": "item.event", "type": "PUT",
        "item_id": "item_042", "item_label": "milk carton", "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.90
    }

    consumer1 = MockKafkaConsumer([
        MockKafkaMessage(topic="person.seen", value=json.dumps(p1), offset=1),
        MockKafkaMessage(topic="item.event", value=json.dumps(i1), offset=2),
    ])

    mono_time = [0.0]
    sim_now = ["2026-11-08T09:15:00.000Z"]

    controller1 = EngineController(
        config=cfg,
        store=store,
        consumer=consumer1,
        producer=producer1,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
        now_ts_fn=lambda: sim_now[0],
        clock_fn=lambda: mono_time[0],
    )

    # Process person at t0 and item at t1; item is pending in Matcher window
    controller1.step(poll_timeout=0.01)
    mono_time[0] = 1.0
    sim_now[0] = "2026-11-08T09:15:01.000Z"
    controller1.step(poll_timeout=0.01)
    # Observable: no outputs emitted yet
    assert len(producer1.published_messages) == 0

    # SIMULATE SUDDEN CRASH & RESTART
    controller1.request_stop()
    producer2 = MockKafkaProducer()
    consumer2 = MockKafkaConsumer([])  # empty queue on restart

    controller2 = EngineController(
        config=cfg,
        store=store,  # same underlying persistent store
        consumer=consumer2,
        producer=producer2,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
        now_ts_fn=lambda: sim_now[0],
        clock_fn=lambda: mono_time[0],
    )

    # Advance clock past idle timeout (t11) to finalize pending item
    mono_time[0] = 11.0
    sim_now[0] = "2026-11-08T09:15:11.000Z"
    controller2.step(poll_timeout=0.01)

    # Public observable assertions:
    # 1. Exactly one PUT finalized and published
    assert len(producer2.published_messages) == 1
    out = producer2.published_messages[0][2]
    assert out["event_id"] == "i_mid_1"
    assert out["owner_id"] == "p_01"
    assert out["status"] == "ok"

    # 2. Inventory observable state contains the item
    inv = store.get_inventory()
    assert len(inv) == 1
    assert inv[0]["item_id"] == "item_042"
    assert inv[0]["owner_id"] == "p_01"


def test_restart_dedup_redelivery_commit_before_kafka_ack():
    """Verify DB commit happens before Kafka commit, and redelivered input does not
    duplicate Matcher state or output.
    """
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    producer = MockKafkaProducer()

    valid_item = {
        "event_id": "i_dedup_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.90,
    }
    msg = MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=10)

    # Fail Kafka commit on first attempt
    consumer1 = MockKafkaConsumer([msg])
    consumer1.fail_commit = True

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer1,
        producer=producer,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
    )

    with pytest.raises(RuntimeError, match="Injected Kafka commit failure"):
        controller.step(poll_timeout=0.01)

    # DB committed the journal row before Kafka ack failed
    assert len(store.get_journal_records()) == 1

    # Redelivered message
    consumer2 = MockKafkaConsumer([msg])
    controller.bus.consumer = consumer2

    # Second delivery is deduplicated before mutating Matcher
    controller.step(poll_timeout=0.01)
    assert len(consumer2.committed_messages) == 1
    assert consumer2.committed_messages[0].offset() == 10
    # Journal still has only 1 record
    assert len(store.get_journal_records()) == 1


def test_live_postgres_visibility_and_version_rollback():
    """Separated live Postgres-only test: runs isolated schema rollback, cross-connection visibility
    using read_store GET methods (events, inventory, alerts), and version guard checks comparing
    before/after schema+rows with nonempty data for both mismatched version and legacy tables.
    """
    dsn = get_real_postgres_dsn()
    if dsn is None:
        pytest.skip("TEST_POSTGRES_DSN not set; skipping live Postgres integration test")

    import psycopg
    schema_name = f"test_live_pg_{uuid.uuid4().hex[:8]}"
    legacy_schema = f"test_legacy_{uuid.uuid4().hex[:8]}"

    try:
        with psycopg.connect(dsn, autocommit=True) as setup_conn:
            with setup_conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema_name};")
    except Exception as exc:
        pytest.fail(f"TEST_POSTGRES_DSN was set but schema creation failed: {exc}")

    try:
        with psycopg.connect(dsn, autocommit=True) as conn1, psycopg.connect(dsn, autocommit=True) as conn2:
            worker_store = PostgresStore(conn1, schema=schema_name)
            worker_store.init_db()
            worker_store.check_or_init_version(MATCHER_VERSION)

            read_store = PostgresStore(conn2, schema=schema_name)

            # Insert nonempty initial data
            matcher = Matcher()
            p1 = {
                "event_id": "p_live_pg_1", "topic": "person.seen", "track_id": 1,
                "person_id": "p_01", "ts": "2026-11-08T09:15:00.000Z", "confidence": 0.95
            }
            item1 = {
                "event_id": "i_live_pg_1", "topic": "item.event", "type": "PUT",
                "item_id": "item_milk", "item_label": "Live Milk", "ts": "2026-11-08T09:15:01.000Z",
                "confidence": 0.90
            }
            worker_store.handle_input("person", p1, matcher)
            worker_store.handle_input("item", item1, matcher)

            # 1. Before/after state for version mismatch refusal on nonempty database
            def get_db_snapshot():
                with conn2.cursor() as c:
                    c.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{schema_name}' ORDER BY table_name")
                    tables = [r[0] for r in c.fetchall()]
                    c.execute(f"SELECT version FROM {schema_name}.matcher_version")
                    v_rows = c.fetchall()
                    c.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal")
                    j_count = c.fetchone()[0]
                    c.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events")
                    fe_count = c.fetchone()[0]
                    c.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox")
                    o_count = c.fetchone()[0]
                    return tables, v_rows, j_count, fe_count, o_count

            before_snapshot = get_db_snapshot()

            with pytest.raises(VersionMismatchError):
                worker_store.check_or_init_version("incompatible-v2")

            after_snapshot = get_db_snapshot()
            assert before_snapshot == after_snapshot

            # 2. Before/after state for unversioned legacy state refusal
            with psycopg.connect(dsn, autocommit=True) as leg_conn:
                with leg_conn.cursor() as cur:
                    cur.execute(f"CREATE SCHEMA {legacy_schema};")
                    cur.execute(f"CREATE TABLE {legacy_schema}.matcher_journal (seq BIGSERIAL PRIMARY KEY, kind TEXT, payload JSONB, event_id TEXT);")
                    cur.execute(f"CREATE TABLE {legacy_schema}.fridge_events (event_id TEXT PRIMARY KEY, payload JSONB NOT NULL);")
                    cur.execute(f"CREATE TABLE {legacy_schema}.outbox (id BIGSERIAL PRIMARY KEY, event_id TEXT NOT NULL, topic TEXT NOT NULL, payload JSONB NOT NULL, status TEXT NOT NULL, published_at TIMESTAMPTZ);")
                    cur.execute(f"INSERT INTO {legacy_schema}.matcher_journal (kind, payload, event_id) VALUES ('person', '{{}}', 'p_leg_1');")
                    cur.execute(f"INSERT INTO {legacy_schema}.fridge_events (event_id, payload) VALUES ('fe_leg_1', '{{\"topic\":\"fridge.event\"}}');")
                    cur.execute(f"INSERT INTO {legacy_schema}.outbox (event_id, topic, payload, status) VALUES ('fe_leg_1', 'fridge.event', '{{}}', 'pending');")

            store_legacy = PostgresStore(conn1, schema=legacy_schema)
            with pytest.raises(VersionMismatchError):
                store_legacy.check_or_init_version(MATCHER_VERSION)

            with conn2.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {legacy_schema}.matcher_journal")
                assert cur.fetchone()[0] == 1
                cur.execute(f"SELECT COUNT(*) FROM {legacy_schema}.fridge_events")
                assert cur.fetchone()[0] == 1
                cur.execute(f"SELECT COUNT(*) FROM {legacy_schema}.outbox")
                assert cur.fetchone()[0] == 1
                cur.execute(f"SELECT to_regclass('{legacy_schema}.matcher_version')")
                assert cur.fetchone()[0] is None

            # 3. Cross-connection visibility using real read_store GET methods
            worker_store.handle_tick("2026-11-08T09:15:15.000Z", matcher)

            # Query read_store over committed state from second connection
            events = read_store.get_events(limit=50)
            assert len(events) == 1
            assert events[0]["item_id"] == "item_milk"
            assert events[0]["owner_id"] == "p_01"

            inventory = read_store.get_inventory()
            assert len(inventory) == 1
            assert inventory[0]["item_id"] == "item_milk"
            assert inventory[0]["owner_id"] == "p_01"
            assert inventory[0]["item_label"] == "Live Milk"

            alerts = read_store.get_alerts()
            assert alerts == []
    finally:
        with psycopg.connect(dsn, autocommit=True) as cleanup_conn:
            with cleanup_conn.cursor() as cur:
                if legacy_schema:
                    cur.execute(f"DROP SCHEMA IF EXISTS {legacy_schema} CASCADE;")
                if schema_name:
                    cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
