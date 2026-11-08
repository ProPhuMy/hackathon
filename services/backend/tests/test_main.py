"""Tests for EngineController, graceful shutdown, failure recovery replay, and CLI safety."""

import json
import threading
import pytest
from io_helpers import MockKafkaConsumer, MockKafkaProducer, MockKafkaMessage, MockPostgresConn, MockCursor, MockUvicornServer
from fridge_backend.config import BackendConfig
from fridge_backend.store import PostgresStore, ReplayMismatchError
try:
    from fridge_backend.store import VersionMismatchError
except ImportError:
    class VersionMismatchError(Exception):
        pass
from fridge_backend.main import EngineController, main_entry
from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION
from test_store import StubMatcher


def test_refuses_startup_without_matcher_factory():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    with pytest.raises(ValueError, match="Matcher factory is required"):
        EngineController(config=cfg, store=store, consumer=consumer, producer=producer, matcher_factory=None, matcher_version=MATCHER_VERSION)


def test_loop_controller_e2e_with_stub_matcher():
    cfg = BackendConfig(tick_interval_ms=1000)
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    valid_item = {
        "event_id": "i_ctrl_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.90,
    }
    consumer = MockKafkaConsumer([
        MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=1),
    ])
    producer = MockKafkaProducer()

    def mock_time_fn():
        return "2026-11-08T09:15:02.000Z"

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
        now_ts_fn=mock_time_fn,
    )

    controller.step(poll_timeout=0.01)

    assert len(producer.published_messages) == 1
    assert producer.published_messages[0][0] == "fridge.event"
    assert producer.published_messages[0][2]["event_id"] == "i_ctrl_1"
    assert len(store.get_pending_outbox()) == 0


def test_failure_recovery_discards_and_rebuilds_matcher():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    valid_person = {
        "event_id": "p_hist_1",
        "topic": "person.seen",
        "track_id": 1,
        "person_id": "p_01",
        "ts": "2026-11-08T09:15:00.000Z",
        "confidence": 0.95,
    }
    controller.store.handle_input("person", valid_person, controller.matcher)
    assert len(controller.matcher.seen_events) == 1

    old_matcher = controller.matcher
    controller.matcher.seen_events.append({"dirty": "mutation"})
    assert len(controller.matcher.seen_events) == 2

    controller.recover_from_failure()

    assert controller.matcher is not old_matcher
    assert controller.bus.matcher is controller.matcher
    assert len(controller.matcher.seen_events) == 1
    assert controller.matcher.seen_events[0]["event_id"] == "p_hist_1"


def test_relay_db_failure_rebuilds_controller_and_bus_matcher_and_fails_closed(monkeypatch):
    """Proves relay mark-published DB failure triggers matcher rebuild in step(), replaces
    controller.matcher AND bus.matcher, retains pending row, and stops further processing.
    """
    cfg = BackendConfig(outbox_poll_interval_ms=10)
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    first_item = {
        "event_id": "i_relay_fail_first",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.90,
    }
    second_item = {
        "event_id": "i_never_seen",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_002",
        "item_label": "Milk",
        "ts": "2026-11-08T09:15:02.000Z",
        "confidence": 0.90,
    }
    consumer = MockKafkaConsumer([
        MockKafkaMessage(topic="item.event", value=json.dumps(first_item), offset=1),
        MockKafkaMessage(topic="item.event", value=json.dumps(second_item), offset=2),
    ])
    producer = MockKafkaProducer(fail_delivery=False)

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    # Inject failure into UPDATE outbox
    orig_execute = MockCursor.execute

    def fail_update(self, sql, params=None):
        if "UPDATE" in sql.upper() and "OUTBOX" in sql.upper():
            raise RuntimeError("DB connection dropped on UPDATE outbox")
        return orig_execute(self, sql, params)

    monkeypatch.setattr(MockCursor, "execute", fail_update)

    old_matcher_id = id(controller.matcher)

    # step() processes first_item, then during outbox relay fails on UPDATE outbox
    with pytest.raises(RuntimeError, match="DB connection dropped on UPDATE outbox"):
        controller.step()

    # Matcher was rebuilt: identity changed on controller and bus
    assert id(controller.matcher) != old_matcher_id
    assert controller.bus.matcher is controller.matcher

    # Outbox row for first_item remains pending
    assert len(store.get_pending_outbox()) == 1
    assert store.get_pending_outbox()[0]["event_id"] == "i_relay_fail_first"

    # Second message in consumer was NEVER polled or processed!
    assert len(consumer.queue) == 1
    assert consumer.queue[0].offset() == 2
    assert len(consumer.committed_messages) == 1  # only first was committed before relay failed


def test_fatal_replay_mismatch_propagates():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    def fail_replay(factory, expected_version=None):
        raise ReplayMismatchError("Deterministic replay output mismatch!")

    controller.store.replay_journal = fail_replay

    with pytest.raises(ReplayMismatchError, match="Deterministic replay output mismatch!"):
        controller.recover_from_failure()


def test_run_fails_closed_without_overtaking_failed_offset():
    """Verify EngineController.run does NOT swallow step errors or loop past a failed input."""
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    valid_item = {
        "event_id": "i_fail_first",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.92,
    }
    valid_item2 = {
        "event_id": "i_second",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_002",
        "item_label": "Milk",
        "ts": "2026-11-08T09:15:02.000Z",
        "confidence": 0.90,
    }
    consumer = MockKafkaConsumer([
        MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=1),
        MockKafkaMessage(topic="item.event", value=json.dumps(valid_item2), offset=2),
    ])
    producer = MockKafkaProducer()

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    controller.matcher.should_fail_after_mutation = True

    with pytest.raises(RuntimeError, match="failure after mutation"):
        controller.run()

    # Message 2 is still queued and uncommitted!
    assert len(consumer.queue) == 1
    assert consumer.queue[0].offset() == 2
    assert len(consumer.committed_messages) == 0


def test_monotonic_clock_driven_intervals():
    cfg = BackendConfig(tick_interval_ms=1000, outbox_poll_interval_ms=500)
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    current_mono = [100.0]

    def mock_clock():
        return current_mono[0]

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
        clock_fn=mock_clock,
    )

    # Initial step: outbox processed, no tick
    controller.step(poll_timeout=0.01)
    assert len(store.get_journal_records()) == 0

    # Advance clock by 1.1 seconds -> tick triggers
    current_mono[0] = 101.1
    controller.step(poll_timeout=0.01)
    records = store.get_journal_records()
    assert len(records) == 1
    assert records[0].kind == "tick"


def test_cli_help_and_exit_codes(capsys, monkeypatch):
    with pytest.raises(SystemExit) as exit_help:
        main_entry(["--help"])
    assert exit_help.value.code == 0

    # Mock run_service so CLI test doesn't try to connect to live DB or listen on port
    monkeypatch.setattr("fridge_backend.main.run_service", lambda cfg: 0)
    with pytest.raises(SystemExit) as exit_run:
        main_entry([])
    assert exit_run.value.code == 0


def test_shutdown_closes_all_resources_even_if_one_fails():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    # Make consumer.close fail
    def fail_consumer_close():
        raise RuntimeError("Consumer close exploded")

    consumer.close = fail_consumer_close

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    assert controller.is_running is True
    assert conn.is_closed is False

    controller.stop()

    assert controller.is_running is False
    # store was still closed despite consumer close failing
    assert conn.is_closed is True


def test_controller_refuses_missing_explicit_matcher_version():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    # Missing or None matcher_version must be refused
    with pytest.raises((ValueError, TypeError)):
        EngineController(
            config=cfg,
            store=store,
            consumer=consumer,
            producer=producer,
            matcher_factory=StubMatcher,
            matcher_version=None,
        )


def test_controller_version_refusal_precedes_kafka_poll_and_outbox():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    conn._committed_tables.add("matcher_version")
    conn._committed_version = "old-version"
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    factory_called = False

    def tracking_factory():
        nonlocal factory_called
        factory_called = True
        return StubMatcher()

    # Preflight check in controller construction must raise before calling factory or polling
    with pytest.raises(VersionMismatchError):
        EngineController(
            config=cfg,
            store=store,
            consumer=consumer,
            producer=producer,
            matcher_factory=tracking_factory,
            matcher_version=MATCHER_VERSION,
        )

    assert not factory_called, "Matcher factory must not be called when version check fails"


def test_controller_request_stop_and_cleanup_order():
    cfg = BackendConfig()
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=StubMatcher,
        matcher_version=MATCHER_VERSION,
    )

    # Calling request_stop signals the loop to exit without immediately closing resources
    controller.request_stop()
    assert controller.is_running is False
    # Resources must not be closed prematurely while a step may still be finishing
    assert not conn.is_closed

    # In finally block, controller runs cleanup
    controller.stop()
    assert conn.is_closed


def test_worker_crash_sets_uvicorn_should_exit(monkeypatch):
    """Tests the production runner/watcher path: unhandled worker crash actively sets
    server.should_exit = True and returns exit code 1.
    """
    from fridge_backend.main import run_service

    cfg = BackendConfig()
    server = MockUvicornServer()

    conn1 = MockPostgresConn()
    conn2 = MockPostgresConn()
    conns = [conn1, conn2]
    monkeypatch.setattr("fridge_backend.main.create_postgres_connection", lambda dsn: conns.pop(0))
    monkeypatch.setattr("fridge_backend.main.create_kafka_consumer", lambda c: MockKafkaConsumer([]))
    monkeypatch.setattr("fridge_backend.main.create_kafka_producer", lambda c: MockKafkaProducer())

    # Make worker controller crash during run()
    def failing_step(self, poll_timeout=0.1):
        raise RuntimeError("Simulated worker thread crash")

    monkeypatch.setattr(EngineController, "step", failing_step)

    def fake_server_run():
        import time
        for _ in range(30):
            if server.should_exit:
                break
            time.sleep(0.02)

    server.run = fake_server_run

    exit_code = run_service(cfg, server_override=server)
    assert server.should_exit is True
    assert exit_code == 1
    assert conn1.is_closed
    assert conn2.is_closed


def test_worker_active_step_blocks_shutdown_until_step_completes(monkeypatch):
    from fridge_backend.main import run_service

    cfg = BackendConfig()
    server = MockUvicornServer()

    server_run_started = threading.Event()
    server_should_exit_gate = threading.Event()

    def fake_server_run():
        server_run_started.set()
        server_should_exit_gate.wait(timeout=5.0)
        server.should_exit = True

    server.run = fake_server_run

    conn1 = MockPostgresConn()
    conn2 = MockPostgresConn()
    conns = [conn1, conn2]
    monkeypatch.setattr("fridge_backend.main.create_postgres_connection", lambda dsn: conns.pop(0))
    monkeypatch.setattr("fridge_backend.main.create_kafka_consumer", lambda c: MockKafkaConsumer([]))
    monkeypatch.setattr("fridge_backend.main.create_kafka_producer", lambda c: MockKafkaProducer())

    step_started = threading.Event()
    step_release = threading.Event()

    def blocking_step(self, poll_timeout=0.1):
        step_started.set()
        step_release.wait(timeout=5.0)
        self.request_stop()

    monkeypatch.setattr(EngineController, "step", blocking_step)

    runner_finished = threading.Event()
    runner_exceptions = []
    exit_code_holder = []

    def run_target():
        try:
            exit_code = run_service(cfg, server_override=server)
            exit_code_holder.append(exit_code)
        except BaseException as exc:
            runner_exceptions.append(exc)
        finally:
            runner_finished.set()

    runner_thread = threading.Thread(target=run_target, name="TestServiceRunner", daemon=True)
    runner_thread.start()

    try:
        # Wait until server.run has started and worker is actively executing step
        assert server_run_started.wait(timeout=2.0), "Server run did not start"
        assert step_started.wait(timeout=2.0), "Worker step did not start"

        # Signal server.run to complete (simulating server shutdown request)
        server_should_exit_gate.set()

        # Allow server.run to exit and enter run_service finally block (request_stop + worker_thread.join)
        import time
        time.sleep(0.05)

        # Assert runner does NOT report complete while step is still blocked/active
        assert not runner_finished.is_set(), "Runner prematurely reported finished while worker was in step"
        assert not conn2.is_closed, "Worker connection closed while worker was still active in step"
        assert not conn1.is_closed, "Reader connection closed before worker completed"

        # Release worker step so worker loop can finish its step and execute controller.stop() in finally
        step_release.set()

        # Runner now completes cleanly and joins
        assert runner_finished.wait(timeout=3.0), "Runner did not complete after step was released"

        # Verify no unhandled exception occurred in runner
        assert not runner_exceptions, f"Runner crashed with exception: {runner_exceptions[0]}"
        assert exit_code_holder and exit_code_holder[0] == 0, f"Expected exit code 0, got {exit_code_holder}"

        # Exactly once cleanup verified: both connections are closed after runner completes
        assert conn1.is_closed, "Reader connection was not closed"
        assert conn2.is_closed, "Worker connection was not closed"
    finally:
        # ALWAYS release all gates and join runner thread to prevent hangs or leaking non-daemon threads
        step_release.set()
        server_should_exit_gate.set()
        runner_thread.join(timeout=2.0)


def test_startup_version_mismatch_closes_reader_connection(monkeypatch):
    from fridge_backend.main import run_service

    cfg = BackendConfig()
    conn_reader = MockPostgresConn()
    conn_reader._committed_tables.add("matcher_version")
    conn_reader._committed_version = "incompatible_v0"

    monkeypatch.setattr("fridge_backend.main.create_postgres_connection", lambda dsn: conn_reader)

    with pytest.raises(VersionMismatchError):
        run_service(cfg)

    assert conn_reader.is_closed


def test_startup_allocation_failure_closes_all_resources(monkeypatch):
    from fridge_backend.main import run_service

    cfg = BackendConfig()
    conn1 = MockPostgresConn()
    conn2 = MockPostgresConn()
    conns = [conn1, conn2]
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()

    monkeypatch.setattr("fridge_backend.main.create_postgres_connection", lambda dsn: conns.pop(0))
    monkeypatch.setattr("fridge_backend.main.create_kafka_consumer", lambda c: consumer)
    monkeypatch.setattr("fridge_backend.main.create_kafka_producer", lambda c: producer)

    def failing_init(self, *args, **kwargs):
        raise RuntimeError("Failed during EngineController init")

    monkeypatch.setattr(EngineController, "__init__", failing_init)

    with pytest.raises(RuntimeError, match="Failed during EngineController init"):
        run_service(cfg)

    assert conn1.is_closed
    assert conn2.is_closed
    assert consumer.closed


def test_separate_reader_and_worker_connections(monkeypatch):
    from fridge_backend.main import run_service

    cfg = BackendConfig()
    conn_reader = MockPostgresConn()
    conn_worker = MockPostgresConn()
    conns = [conn_reader, conn_worker]

    monkeypatch.setattr("fridge_backend.main.create_postgres_connection", lambda dsn: conns.pop(0))
    monkeypatch.setattr("fridge_backend.main.create_kafka_consumer", lambda c: MockKafkaConsumer([]))
    monkeypatch.setattr("fridge_backend.main.create_kafka_producer", lambda c: MockKafkaProducer())

    server = MockUvicornServer()
    server.run = lambda: server.__setattr__("should_exit", True)

    run_service(cfg, server_override=server)
    assert conn_reader is not conn_worker


def test_real_matcher_wiring_in_engine_controller():
    cfg = BackendConfig(tick_interval_ms=1000)
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    producer = MockKafkaProducer()

    valid_person = {
        "event_id": "p_real_ctrl_1",
        "topic": "person.seen",
        "track_id": 1,
        "person_id": "p_01",
        "ts": "2026-11-08T09:14:59.000Z",
        "confidence": 0.95,
    }
    valid_item = {
        "event_id": "i_real_ctrl_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_042",
        "item_label": "milk carton",
        "ts": "2026-11-08T09:15:00.000Z",
        "confidence": 0.90,
    }

    consumer = MockKafkaConsumer([
        MockKafkaMessage(topic="person.seen", value=json.dumps(valid_person), offset=1),
        MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=2),
    ])

    mono_time = [0.0]

    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
        now_ts_fn=lambda: "2026-11-08T09:15:10.000Z",
        clock_fn=lambda: mono_time[0],
    )

    # Process person (t=0s)
    controller.step(poll_timeout=0.01)
    # Process item (t=0.5s)
    mono_time[0] = 0.5
    controller.step(poll_timeout=0.01)
    assert len(producer.published_messages) == 0

    # Advance monotonic clock by > 1.0s (tick interval)
    mono_time[0] = 2.0
    controller.step(poll_timeout=0.01)

    # Verify real Matcher emitted PUT event
    assert len(producer.published_messages) == 1
    topic, key, payload = producer.published_messages[0]
    assert topic == "fridge.event"
    assert payload["event_id"] == "i_real_ctrl_1"
    assert payload["owner_id"] == "p_01"
    assert payload["status"] == "ok"

