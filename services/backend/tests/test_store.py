"""Tests for Postgres store, matcher journal, transactional outbox, and deterministic replay."""

import contextlib
import copy
import json
from pathlib import Path
import uuid
import pytest
from io_helpers import MockPostgresConn, MockKafkaProducer, MockCursor, get_real_postgres_dsn
from fridge_backend.store import (
    PostgresStore,
    ReplayMismatchError,
    JournalRecord,
    create_postgres_connection,
    DuplicatePersonError,
)
try:
    from fridge_backend.store import VersionMismatchError
except ImportError:
    class VersionMismatchError(Exception):
        """Temporary placeholder for red tests until defined in store.py."""
        pass
from fridge_backend.matcher import Matcher, MatcherConfig, MATCHER_VERSION


class StubMatcher:
    """Deterministic stub matcher for store unit testing."""
    def __init__(self):
        self.seen_events: list[dict] = []
        self.tick_timestamps: list[str] = []
        self.should_fail = False
        self.should_fail_after_mutation = False

    def on_person(self, ev: dict) -> list[dict]:
        self.seen_events.append(ev)
        if self.should_fail or self.should_fail_after_mutation:
            raise RuntimeError("Injected Matcher on_person failure after mutation")
        return []

    def on_item(self, ev: dict) -> list[dict]:
        self.seen_events.append(ev)
        if self.should_fail or self.should_fail_after_mutation:
            raise RuntimeError("Injected Matcher on_item failure after mutation")
        return [{
            "event_id": ev["event_id"],
            "topic": "fridge.event",
            "type": ev["type"],
            "item_id": ev["item_id"],
            "item_label": ev["item_label"],
            "person_id": "p_01",
            "owner_id": "p_01",
            "ts": ev["ts"],
            "confidence": 0.85,
            "status": "ok",
        }]

    def tick(self, now_ts: str) -> list[dict]:
        self.tick_timestamps.append(now_ts)
        if self.should_fail or self.should_fail_after_mutation:
            raise RuntimeError("Injected Matcher tick failure after mutation")
        return []

    def inventory(self) -> dict[str, str | None]:
        return {}


def make_item_event(event_id: str, ts: str = "2026-11-08T09:15:00.000Z") -> dict:
    return {
        "event_id": event_id,
        "topic": "item.event",
        "type": "PUT",
        "item_id": "milk_01",
        "item_label": "Whole Milk",
        "ts": ts,
        "confidence": 0.95,
    }


def make_person_event(event_id: str, ts: str = "2026-11-08T09:14:59.000Z") -> dict:
    return {
        "event_id": event_id,
        "topic": "person.seen",
        "track_id": 1,
        "person_id": "p_01",
        "ts": ts,
        "confidence": 0.90,
    }


def test_reject_autocommit_false_or_none_connection():
    conn_false = MockPostgresConn(autocommit=False)
    with pytest.raises(ValueError, match="autocommit=True"):
        PostgresStore(conn_false)

    class ConnNoAutocommit:
        pass

    with pytest.raises(ValueError, match="autocommit=True"):
        PostgresStore(ConnNoAutocommit())


def test_store_close():
    conn = MockPostgresConn(autocommit=True)
    store = PostgresStore(conn)
    assert conn.is_closed is False
    store.close()
    assert conn.is_closed is True


def test_journal_sequence_and_unique_event_id():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    p1 = make_person_event("p1")
    outputs = store.handle_input("person", p1, matcher)
    assert outputs == []

    i1 = make_item_event("i1")
    outputs2 = store.handle_input("item", i1, matcher)
    assert len(outputs2) == 1
    assert outputs2[0]["event_id"] == "i1"

    records = store.get_journal_records()
    assert len(records) == 2
    assert records[0].seq == 1
    assert records[0].kind == "person"
    assert records[0].event_id == "p1"
    assert records[1].seq == 2
    assert records[1].kind == "item"
    assert records[1].event_id == "i1"

    matcher.seen_events.clear()
    dup_outputs = store.handle_input("person", p1, matcher)
    assert dup_outputs == []
    assert len(matcher.seen_events) == 0
    assert len(store.get_journal_records()) == 2


def test_atomic_rollback_on_matcher_failure():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    store.handle_input("person", make_person_event("p1"), matcher)
    assert len(store.get_journal_records()) == 1

    matcher.should_fail_after_mutation = True
    with pytest.raises(RuntimeError, match="failure after mutation"):
        store.handle_input("item", make_item_event("i2"), matcher)

    records = store.get_journal_records()
    assert len(records) == 1
    assert records[0].event_id == "p1"
    assert store.get_pending_outbox() == []


def test_atomic_rollback_on_outbox_failure(monkeypatch):
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    def fail_insert_outbox(*args, **kwargs):
        raise RuntimeError("DB Outbox insertion exploded")

    monkeypatch.setattr(store, "_insert_outbox", fail_insert_outbox)

    with pytest.raises(RuntimeError, match="DB Outbox insertion exploded"):
        store.handle_input("item", make_item_event("i1"), matcher)

    assert len(store.get_journal_records()) == 0
    assert store.get_stored_fridge_events() == {}
    assert store.get_pending_outbox() == []


def test_no_output_tick_journaling():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    now_ts = "2026-11-08T09:15:10.500Z"
    outputs = store.handle_tick(now_ts, matcher)
    assert outputs == []

    records = store.get_journal_records()
    assert len(records) == 1
    assert records[0].kind == "tick"
    assert records[0].event_id is None
    assert records[0].payload == {"now_ts": now_ts}


def test_arrival_order_not_event_time_journaling():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    i_late_ts = make_item_event("i_late", ts="2026-11-08T09:20:00.000Z")
    store.handle_input("item", i_late_ts, matcher)

    p_early_ts = make_person_event("p_early", ts="2026-11-08T09:10:00.000Z")
    store.handle_input("person", p_early_ts, matcher)

    records = store.get_journal_records()
    assert len(records) == 2
    assert records[0].event_id == "i_late"
    assert records[1].event_id == "p_early"


def test_startup_replay_restores_state():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    p1 = make_person_event("p1")
    i1 = make_item_event("i1")
    store.handle_input("person", p1, matcher)
    store.handle_input("item", i1, matcher)
    store.handle_tick("2026-11-08T09:15:05.000Z", matcher)

    fresh_matcher = store.replay_journal(StubMatcher, expected_version=MATCHER_VERSION)
    assert len(fresh_matcher.seen_events) == 2
    assert len(fresh_matcher.tick_timestamps) == 1
    assert fresh_matcher.tick_timestamps[0] == "2026-11-08T09:15:05.000Z"


def test_replay_cross_check_and_fail_closed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i1"), matcher)

    class MutatingMatcher(StubMatcher):
        def on_item(self, ev: dict) -> list[dict]:
            out = super().on_item(ev)
            out[0]["status"] = "wrong_owner"
            return out

    with pytest.raises(ReplayMismatchError, match="Payload mismatch"):
        store.replay_journal(MutatingMatcher, expected_version=MATCHER_VERSION)

    class SilentMatcher(StubMatcher):
        def on_item(self, ev: dict) -> list[dict]:
            return []

    with pytest.raises(ReplayMismatchError, match="Missing expected output"):
        store.replay_journal(SilentMatcher, expected_version=MATCHER_VERSION)

    class ExtraMatcher(StubMatcher):
        def on_person(self, ev: dict) -> list[dict]:
            return [{
                "event_id": "spurious_id",
                "topic": "fridge.event",
                "type": "PUT",
                "item_id": "extra",
                "item_label": "extra",
                "person_id": None,
                "owner_id": None,
                "ts": "2026-11-08T09:15:00.000Z",
                "confidence": 0.0,
                "status": "uncertain",
            }]

    store.handle_input("person", make_person_event("p1"), matcher)
    with pytest.raises(ReplayMismatchError, match="Spurious extra output"):
        store.replay_journal(ExtraMatcher, expected_version=MATCHER_VERSION)


def test_replay_detects_duplicate_output_mismatch():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i1"), matcher)

    class DuplicateEmittingMatcher(StubMatcher):
        def on_item(self, ev: dict) -> list[dict]:
            out = super().on_item(ev)
            return [out[0], copy.deepcopy(out[0])]

    with pytest.raises(ReplayMismatchError, match="Duplicate output"):
        store.replay_journal(DuplicateEmittingMatcher, expected_version=MATCHER_VERSION)


def test_db_commit_success_then_kafka_commit_failure_redelivery():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    i1 = make_item_event("i1")
    outputs = store.handle_input("item", i1, matcher)
    assert len(outputs) == 1
    assert len(matcher.seen_events) == 1

    redelivered_outputs = store.handle_input("item", i1, matcher)
    assert redelivered_outputs == []
    assert len(matcher.seen_events) == 1


def test_outbox_self_driving_flush_and_stop_on_failure():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i1"), matcher)
    store.handle_input("item", make_item_event("i2"), matcher)
    assert len(store.get_pending_outbox()) == 2

    failing_producer = MockKafkaProducer(fail_delivery=True)
    count = store.relay_outbox(failing_producer)
    assert count == 0
    pending = store.get_pending_outbox()
    assert len(pending) == 2
    assert pending[0]["event_id"] == "i1"

    success_producer = MockKafkaProducer(fail_delivery=False)
    count = store.relay_outbox(success_producer)
    assert count == 2
    assert len(store.get_pending_outbox()) == 0


def test_outbox_flush_timeout_or_missing_callback_fails_closed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i1"), matcher)
    timeout_producer = MockKafkaProducer(timeout_flush=True)

    with pytest.raises(RuntimeError, match="Outbox delivery confirmation timed out"):
        store.relay_outbox(timeout_producer, timeout=0.1)

    assert len(store.get_pending_outbox()) == 1


def test_outbox_broker_success_then_published_mark_db_failure(monkeypatch):
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i1"), matcher)
    producer = MockKafkaProducer(fail_delivery=False)

    orig_execute = MockCursor.execute

    def fail_update(self, sql, params=None):
        if "UPDATE" in sql.upper() and "OUTBOX" in sql.upper():
            raise RuntimeError("Database connection died during outbox status update")
        return orig_execute(self, sql, params)

    monkeypatch.setattr(MockCursor, "execute", fail_update)

    with pytest.raises(RuntimeError, match="Database connection died"):
        store.relay_outbox(producer)

    # Outbox row remains pending (safe duplicate delivery permitted on retry)
    assert len(store.get_pending_outbox()) == 1


def test_real_postgres_integration(monkeypatch):
    dsn = get_real_postgres_dsn()
    if dsn is None:
        pytest.skip("TEST_POSTGRES_DSN not set; skipping live Postgres integration test")

    import psycopg
    schema_name = f"test_{uuid.uuid4().hex[:8]}"

    try:
        with psycopg.connect(dsn, autocommit=True) as conn1:
            with conn1.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema_name};")
    except Exception as exc:
        pytest.fail(f"TEST_POSTGRES_DSN was provided but connection/schema setup failed: {exc}")

    try:
        with psycopg.connect(dsn, autocommit=True) as conn1, psycopg.connect(dsn, autocommit=True) as conn2:
            store = PostgresStore(conn1, schema=schema_name)
            store.init_db()
            store.check_or_init_version(MATCHER_VERSION)

            matcher = StubMatcher()

            # 1. Rollback on Matcher failure after mutation
            matcher.should_fail_after_mutation = True
            with pytest.raises(RuntimeError):
                store.handle_input("item", make_item_event("i_fail_mut"), matcher)
            matcher.should_fail_after_mutation = False

            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = 'i_fail_mut'")
                assert cur2.fetchone()[0] == 0

            # 2. Rollback on fridge_events INSERT failure AFTER matcher mutation
            orig_insert_fe = store._insert_fridge_event

            def fail_fe(out_ev):
                raise RuntimeError("Injected fridge_events INSERT failure")

            monkeypatch.setattr(store, "_insert_fridge_event", fail_fe)
            with pytest.raises(RuntimeError, match="Injected fridge_events INSERT failure"):
                store.handle_input("item", make_item_event("i_fail_fe"), matcher)
            monkeypatch.setattr(store, "_insert_fridge_event", orig_insert_fe)

            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = 'i_fail_fe'")
                assert cur2.fetchone()[0] == 0
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events WHERE event_id = 'i_fail_fe'")
                assert cur2.fetchone()[0] == 0

            # 3. Rollback on outbox INSERT failure AFTER matcher mutation
            def fail_outbox(out_ev):
                raise RuntimeError("Injected outbox INSERT failure")

            monkeypatch.setattr(store, "_insert_outbox", fail_outbox)
            with pytest.raises(RuntimeError, match="Injected outbox INSERT failure"):
                store.handle_input("item", make_item_event("i_fail_outbox"), matcher)
            monkeypatch.undo()

            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = 'i_fail_outbox'")
                assert cur2.fetchone()[0] == 0
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox WHERE event_id = 'i_fail_outbox'")
                assert cur2.fetchone()[0] == 0

            # 4. Tick failure rollback AFTER matcher mutation
            matcher.should_fail_after_mutation = True
            with pytest.raises(RuntimeError):
                store.handle_tick("2026-11-08T09:15:30.000Z", matcher)
            matcher.should_fail_after_mutation = False

            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE kind = 'tick'")
                assert cur2.fetchone()[0] == 0

            # 5. Cross-connection durability before Kafka ack & published mark visibility
            store.handle_input("item", make_item_event("i_durable"), matcher)
            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.matcher_journal WHERE event_id = 'i_durable'")
                assert cur2.fetchone()[0] == 1
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.fridge_events WHERE event_id = 'i_durable'")
                assert cur2.fetchone()[0] == 1
                cur2.execute(f"SELECT COUNT(*) FROM {schema_name}.outbox WHERE event_id = 'i_durable' AND status = 'pending'")
                assert cur2.fetchone()[0] == 1

            # 6. Deduplication before matcher mutation
            matcher.seen_events.clear()
            dup = store.handle_input("item", make_item_event("i_durable"), matcher)
            assert dup == []
            assert len(matcher.seen_events) == 0

            # 7. Successful outbox publish marks published with non-null published_at on conn2
            producer = MockKafkaProducer(fail_delivery=False)
            store.relay_outbox(producer)
            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT status, published_at FROM {schema_name}.outbox WHERE event_id = 'i_durable'")
                row = cur2.fetchone()
                assert row[0] == "published"
                assert row[1] is not None

            # 8. Full-payload replay on live PG
            fresh = store.replay_journal(StubMatcher, expected_version=MATCHER_VERSION)
            assert len(fresh.seen_events) == 1
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")


def test_version_guard_same_version_passes():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    # First call initializes version table and records MATCHER_VERSION
    store.check_or_init_version(MATCHER_VERSION)
    assert conn._committed_version == MATCHER_VERSION
    # Repeated call with same version succeeds without error or state change
    store.check_or_init_version(MATCHER_VERSION)
    assert conn._committed_version == MATCHER_VERSION


def test_version_guard_mismatch_fails_with_operator_message():
    conn = MockPostgresConn()
    conn._committed_tables.add("matcher_version")
    conn._committed_version = "0-legacy"
    store = PostgresStore(conn)

    with pytest.raises(VersionMismatchError) as exc_info:
        store.check_or_init_version(MATCHER_VERSION)

    msg = str(exc_info.value)
    assert "0-legacy" in msg
    assert MATCHER_VERSION in msg
    # Verify tables/data remain untouched
    assert conn._committed_version == "0-legacy"


def test_version_guard_legacy_journal_only_fails():
    conn = MockPostgresConn()
    conn._committed_tables.add("matcher_journal")
    conn._committed_journal.append({
        "seq": 1, "kind": "person", "payload": {}, "event_id": "p_legacy"
    })
    store = PostgresStore(conn)

    with pytest.raises(VersionMismatchError):
        store.check_or_init_version(MATCHER_VERSION)

    # Preexisting rows and schema remain completely untouched
    assert len(conn._committed_journal) == 1
    assert "matcher_version" not in conn._committed_tables


def test_version_guard_legacy_outbox_or_events_only_fails():
    conn = MockPostgresConn()
    conn._committed_tables.add("fridge_events")
    conn._committed_tables.add("outbox")
    conn._committed_fridge_events["e1"] = {"dummy": "event"}
    conn._committed_outbox.append({
        "id": 1, "event_id": "e1", "topic": "fridge.event",
        "payload": {}, "status": "pending", "published_at": None
    })
    store = PostgresStore(conn)

    with pytest.raises(VersionMismatchError):
        store.check_or_init_version(MATCHER_VERSION)

    assert len(conn._committed_fridge_events) == 1
    assert len(conn._committed_outbox) == 1
    assert "matcher_version" not in conn._committed_tables


def test_version_guard_empty_legacy_initializes_cleanly():
    conn = MockPostgresConn()
    # Tables exist but have zero rows
    conn._committed_tables.update(["matcher_journal", "fridge_events", "outbox"])
    store = PostgresStore(conn)

    store.check_or_init_version(MATCHER_VERSION)
    assert conn._committed_version == MATCHER_VERSION


def test_version_guard_rollback_leaves_schema_and_rows_unchanged():
    conn = MockPostgresConn()
    conn._committed_tables.add("matcher_version")
    conn._committed_version = "old-v"
    store = PostgresStore(conn)

    with pytest.raises(VersionMismatchError):
        store.check_or_init_version(MATCHER_VERSION)

    # In-transaction working copy was rolled back to committed
    assert conn._committed_version == "old-v"
    assert not conn._in_transaction
    assert len(conn.executed_ddl) == 0, "No DDL statements must be committed on refusal"


@pytest.mark.parametrize("scenario", [
    "mismatch_with_full_data",
    "legacy_journal_pending_item",
    "legacy_fridge_events_only",
    "legacy_outbox_only",
    "present_empty_version_table_with_data",
])
def test_version_guard_refusal_snapshots_unchanged(scenario):
    conn = MockPostgresConn()

    if scenario == "mismatch_with_full_data":
        conn._committed_tables.update(["matcher_version", "matcher_journal", "fridge_events", "outbox"])
        conn._committed_version = "old-version-1"
        conn._committed_journal.append({"seq": 1, "kind": "person", "payload": {}, "event_id": "p1"})
        conn._committed_fridge_events["e1"] = {"event_id": "e1", "topic": "fridge.event"}
        conn._committed_outbox.append({
            "id": 1, "event_id": "e1", "topic": "fridge.event",
            "payload": {}, "status": "pending", "published_at": None
        })
    elif scenario == "legacy_journal_pending_item":
        conn._committed_tables.add("matcher_journal")
        conn._committed_journal.append({"seq": 1, "kind": "item", "payload": {"item_id": "milk"}, "event_id": "i1"})
    elif scenario == "legacy_fridge_events_only":
        conn._committed_tables.add("fridge_events")
        conn._committed_fridge_events["e1"] = {"event_id": "e1", "topic": "fridge.event"}
    elif scenario == "legacy_outbox_only":
        conn._committed_tables.add("outbox")
        conn._committed_outbox.append({
            "id": 1, "event_id": "e1", "topic": "fridge.event",
            "payload": {}, "status": "pending", "published_at": None
        })
    elif scenario == "present_empty_version_table_with_data":
        conn._committed_tables.update(["matcher_version", "matcher_journal"])
        conn._committed_version = None  # present table but empty
        conn._committed_journal.append({"seq": 1, "kind": "person", "payload": {}, "event_id": "p1"})

    store = PostgresStore(conn)

    # Snapshot exact tables, version, rows before
    tables_before = set(conn._committed_tables)
    version_before = conn._committed_version
    journal_before = copy.deepcopy(conn._committed_journal)
    events_before = copy.deepcopy(conn._committed_fridge_events)
    outbox_before = copy.deepcopy(conn._committed_outbox)
    ddl_len_before = len(conn.executed_ddl)

    with pytest.raises(VersionMismatchError):
        store.check_or_init_version(MATCHER_VERSION)

    # Assert exact snapshot equality before == after
    assert set(conn._committed_tables) == tables_before
    assert conn._committed_version == version_before
    assert conn._committed_journal == journal_before
    assert conn._committed_fridge_events == events_before
    assert conn._committed_outbox == outbox_before
    assert len(conn.executed_ddl) == ddl_len_before
    assert not conn._in_transaction


def test_version_preflight_precedes_init_db_even_for_versioned_mismatch():
    conn = MockPostgresConn()
    conn._committed_tables.add("matcher_version")
    conn._committed_version = "mismatch-v"
    store = PostgresStore(conn)

    # Calling check_or_init_version must refuse before running migration SQL
    with pytest.raises(VersionMismatchError):
        store.check_or_init_version(MATCHER_VERSION)
    assert len(conn.executed_ddl) == 0


def test_replay_journal_requires_explicit_matcher_version():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    # Direct replay_journal call without explicit version parameter fails
    with pytest.raises((ValueError, TypeError)):
        store.replay_journal(StubMatcher, expected_version=None)


def test_committed_pending_outbox_persists_across_crash():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    # Step 1: Input successfully processed and committed in DB
    item_ev = make_item_event("i_crash_1")
    store.handle_input("item", item_ev, matcher)

    assert len(store.get_pending_outbox()) == 1
    pending_id = store.get_pending_outbox()[0]["id"]

    # Step 2: Simulated crash and fresh store restart
    store_restarted = PostgresStore(conn)
    fresh_matcher = store_restarted.replay_journal(StubMatcher, expected_version=MATCHER_VERSION)

    # Replay must NOT duplicate outputs or outbox rows
    assert len(store_restarted.get_pending_outbox()) == 1
    assert store_restarted.get_pending_outbox()[0]["id"] == pending_id
    assert len(store_restarted.get_stored_fridge_events()) == 1

    # Step 3: Failed delivery keeps row pending
    fail_producer = MockKafkaProducer(fail_delivery=True)
    count = store_restarted.relay_outbox(fail_producer)
    assert count == 0
    assert len(store_restarted.get_pending_outbox()) == 1

    # Step 4: Successful delivery marks published
    ok_producer = MockKafkaProducer(fail_delivery=False)
    count = store_restarted.relay_outbox(ok_producer)
    assert count == 1
    assert len(store_restarted.get_pending_outbox()) == 0


def test_uncommitted_outbox_and_journal_rolls_back():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()
    matcher.should_fail_after_mutation = True

    with pytest.raises(RuntimeError):
        store.handle_input("item", make_item_event("i_rollback"), matcher)

    # Zero rows remain in journal or outbox
    assert len(store.get_journal_records()) == 0
    assert len(store.get_pending_outbox()) == 0


def test_failed_outbox_delivery_remains_pending_until_later_confirmed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    store.handle_input("item", make_item_event("i_retry"), matcher)
    assert len(store.get_pending_outbox()) == 1

    # First attempt: broker failure
    fail_producer = MockKafkaProducer(fail_delivery=True)
    count = store.relay_outbox(fail_producer)
    assert count == 0
    assert len(store.get_pending_outbox()) == 1

    # Second attempt: broker success
    ok_producer = MockKafkaProducer(fail_delivery=False)
    count = store.relay_outbox(ok_producer)
    assert count == 1
    assert len(store.get_pending_outbox()) == 0


def test_real_matcher_memory_mutation_recovered_from_journal(monkeypatch):
    from fridge_backend.main import EngineController
    from io_helpers import MockKafkaConsumer, MockKafkaProducer
    from fridge_backend.config import BackendConfig

    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    real_matcher = Matcher()

    p1 = make_person_event("p_real_1", ts="2026-11-08T09:14:59.000Z")
    store.handle_input("person", p1, real_matcher)

    item1 = make_item_event("i_fail_mut", ts="2026-11-08T09:15:00.000Z")
    store.handle_input("item", item1, real_matcher)

    assert len(store.get_journal_records()) == 2
    assert len(store.get_events()) == 0
    assert len(store.get_pending_outbox()) == 0

    # Inject a database failure on tick AFTER Matcher has mutated its in-memory state
    def fail_insert_fe(out_ev):
        raise RuntimeError("Simulated DB crash during fridge_events insert after matcher mutation")

    monkeypatch.setattr(store, "_insert_fridge_event", fail_insert_fe)

    with pytest.raises(RuntimeError, match="Simulated DB crash during fridge_events insert"):
        store.handle_tick("2026-11-08T09:15:15.000Z", real_matcher)

    # DB transaction rolled back cleanly: no dirty rows in journal, events, or outbox
    assert len(store.get_journal_records()) == 2
    assert len(store.get_events()) == 0
    assert len(store.get_pending_outbox()) == 0

    # real_matcher in memory is now dirty/mutated (tick emptied its pending queue before DB failed)
    assert real_matcher.tick("2026-11-08T09:15:16.000Z") == []

    # Replay journal via EngineController to discard corrupted state and recover clean Matcher
    cfg = BackendConfig()
    consumer = MockKafkaConsumer([])
    producer = MockKafkaProducer()
    controller = EngineController(
        config=cfg,
        store=store,
        consumer=consumer,
        producer=producer,
        matcher_factory=lambda: Matcher(),
        matcher_version=MATCHER_VERSION,
    )
    controller.recover_from_failure()

    # Restore unmonkeypatched insert and re-execute tick on recovered matcher
    monkeypatch.undo()
    outputs = store.handle_tick("2026-11-08T09:15:15.000Z", controller.matcher)
    assert len(outputs) == 1
    assert outputs[0]["item_id"] == "milk_01"
    assert len(store.get_journal_records()) == 3
    assert len(store.get_events()) == 1
    assert len(store.get_pending_outbox()) == 1


def test_store_get_inventory_derived_from_all_history_in_emission_order():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    # Feed events in emission order
    # 1. PUT item1
    ev1 = make_item_event("i_inv_1", ts="2026-11-08T09:15:00.000Z")
    ev1["item_id"] = "milk_01"
    ev1["item_label"] = "Whole Milk"
    store.handle_input("item", ev1, matcher)

    # 2. PUT item2
    ev2 = make_item_event("i_inv_2", ts="2026-11-08T09:15:01.000Z")
    ev2["item_id"] = "yogurt_02"
    ev2["item_label"] = "Greek Yogurt"
    store.handle_input("item", ev2, matcher)

    # 3. Duplicate PUT of item1 with different label / ts (preserves original)
    ev3 = make_item_event("i_inv_3", ts="2026-11-08T09:15:05.000Z")
    ev3["item_id"] = "milk_01"
    ev3["item_label"] = "Skim Milk"
    # In store, simulate the emitted fridge event for duplicate PUT
    fe_dup = {
        "event_id": "i_inv_3", "topic": "fridge.event", "type": "PUT",
        "item_id": "milk_01", "item_label": "Skim Milk", "person_id": "p_02",
        "owner_id": "p_01", "ts": "2026-11-08T09:15:05.000Z", "confidence": 0.5,
        "status": "uncertain"
    }
    store._insert_fridge_event(fe_dup)
    store._insert_outbox(fe_dup)

    # 4. TAKE item2 (removes item2 and clears metadata)
    fe_take = {
        "event_id": "i_inv_4", "topic": "fridge.event", "type": "TAKE",
        "item_id": "yogurt_02", "item_label": "Greek Yogurt", "person_id": "p_02",
        "owner_id": "p_01", "ts": "2026-11-08T09:15:10.000Z", "confidence": 0.85,
        "status": "wrong_owner"
    }
    store._insert_fridge_event(fe_take)
    store._insert_outbox(fe_take)

    inv = store.get_inventory()
    # Bare list of {item_id, item_label, owner_id, since_ts}
    assert isinstance(inv, list)
    assert len(inv) == 1
    assert inv[0]["item_id"] == "milk_01"
    # Preserves original metadata from first accepted PUT
    assert inv[0]["item_label"] == "Whole Milk"
    assert inv[0]["since_ts"] == "2026-11-08T09:15:00.000Z"
    assert inv[0]["owner_id"] == "p_01"


def test_store_get_events_newest_first_and_limits():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    for i in range(1, 4):
        fe = {
            "event_id": f"e_{i}", "topic": "fridge.event", "type": "PUT",
            "item_id": f"item_{i}", "item_label": f"label_{i}", "person_id": "p1",
            "owner_id": "p1", "ts": f"2026-11-08T09:15:0{i}.000Z", "confidence": 0.9,
            "status": "ok"
        }
        store._insert_fridge_event(fe)
        store._insert_outbox(fe)

    events = store.get_events(limit=2)
    assert isinstance(events, list)
    assert len(events) == 2
    # Newest emitted first
    assert events[0]["event_id"] == "e_3"
    assert events[1]["event_id"] == "e_2"


def test_store_get_alerts_filters_wrong_owner_and_uncertain():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    fe_ok = {
        "event_id": "e_ok", "topic": "fridge.event", "type": "PUT",
        "item_id": "item_1", "item_label": "Milk", "person_id": "p1",
        "owner_id": "p1", "ts": "2026-11-08T09:15:01.000Z", "confidence": 0.9,
        "status": "ok"
    }
    fe_wrong = {
        "event_id": "e_wrong", "topic": "fridge.event", "type": "TAKE",
        "item_id": "item_1", "item_label": "Milk", "person_id": "p2",
        "owner_id": "p1", "ts": "2026-11-08T09:15:02.000Z", "confidence": 0.8,
        "status": "wrong_owner"
    }
    fe_unc = {
        "event_id": "e_unc", "topic": "fridge.event", "type": "PUT",
        "item_id": "item_2", "item_label": "Juice", "person_id": None,
        "owner_id": None, "ts": "2026-11-08T09:15:03.000Z", "confidence": 0.3,
        "status": "uncertain"
    }

    for fe in (fe_ok, fe_wrong, fe_unc):
        store._insert_fridge_event(fe)
        store._insert_outbox(fe)

    alerts = store.get_alerts(limit=50)
    assert isinstance(alerts, list)
    assert len(alerts) == 2
    # Newest emitted first
    assert alerts[0]["event_id"] == "e_unc"
    assert alerts[1]["event_id"] == "e_wrong"


def test_store_resolve_outbox_id_from_event_id():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    fe = {
        "event_id": "target_uuid_123", "topic": "fridge.event", "type": "PUT",
        "item_id": "item_1", "item_label": "Milk", "person_id": "p1",
        "owner_id": "p1", "ts": "2026-11-08T09:15:01.000Z", "confidence": 0.9,
        "status": "ok"
    }
    store._insert_fridge_event(fe)
    store._insert_outbox(fe)

    assert store.resolve_outbox_id("target_uuid_123") == 1
    assert store.resolve_outbox_id("unknown_uuid") is None


def test_store_get_stream_events_tailing():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    for i in range(1, 4):
        fe = {
            "event_id": f"stream_{i}", "topic": "fridge.event", "type": "PUT",
            "item_id": f"item_{i}", "item_label": f"label_{i}", "person_id": "p1",
            "owner_id": "p1", "ts": f"2026-11-08T09:15:0{i}.000Z", "confidence": 0.9,
            "status": "ok"
        }
        store._insert_fridge_event(fe)
        store._insert_outbox(fe)

    # Query strictly greater than outbox id 1
    tail = store.get_stream_events(after_outbox_id=1, limit=50)
    assert len(tail) == 2
    assert tail[0][0] == 2
    assert tail[0][1]["event_id"] == "stream_2"
    assert tail[1][0] == 3
    assert tail[1][1]["event_id"] == "stream_3"


def test_store_same_version_upgrade_acquires_people_table():
    """Existing same-version database missing people table acquires it on startup."""
    conn = MockPostgresConn()
    conn._committed_tables.update(["matcher_version", "matcher_journal", "fridge_events", "outbox"])
    conn._committed_version = MATCHER_VERSION
    store = PostgresStore(conn)

    assert "people" not in conn._committed_tables
    store.check_or_init_version(MATCHER_VERSION)
    assert "people" in conn._committed_tables
    assert conn._committed_version == MATCHER_VERSION


def test_same_version_repeated_replay_no_migration_ddl():
    """Repeated recovery or replay on established database executes zero migration DDL."""
    conn = MockPostgresConn()
    conn._committed_tables.update(["matcher_version", "matcher_journal", "fridge_events", "outbox"])
    conn._committed_version = MATCHER_VERSION
    store = PostgresStore(conn)

    # First startup acquires missing table
    store.check_or_init_version(MATCHER_VERSION)
    assert "people" in conn._committed_tables
    ddl_len_after_first = len(conn.executed_ddl)

    # Second startup / recovery replay: people table already exists, so no DDL runs
    store.check_or_init_version(MATCHER_VERSION)
    assert len(conn.executed_ddl) == ddl_len_after_first


def test_store_people_crud_and_deterministic_order():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    p2 = store.create_person("p_02", "Bob")
    p1 = store.create_person("p_01", "Alice")

    assert p1["person_id"] == "p_01"
    assert p1["name"] == "Alice"
    assert p1["enrollment_status"] == "unknown"
    assert p1["created_at"].endswith("Z")
    assert p1["updated_at"].endswith("Z")

    # Listing must be ordered deterministically by person_id ASC
    people = store.get_people()
    assert isinstance(people, list)
    assert len(people) == 2
    assert people[0]["person_id"] == "p_01"
    assert people[1]["person_id"] == "p_02"

    # Single lookup
    fetched = store.get_person("p_01")
    assert fetched is not None
    assert fetched["name"] == "Alice"
    assert store.get_person("p_unknown") is None

    # Update
    updated = store.update_person("p_01", "Alice Smith")
    assert updated is not None
    assert updated["name"] == "Alice Smith"
    assert store.get_person("p_01")["name"] == "Alice Smith"
    assert store.update_person("p_unknown", "Nobody") is None


def test_store_people_duplicate_raises_duplicate_person_error():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    store.create_person("p_dup", "Original")
    with pytest.raises(DuplicatePersonError, match="already exists"):
        store.create_person("p_dup", "Duplicate")


def test_store_people_validation():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    # Invalid person_id types / contents
    with pytest.raises(ValueError, match="must be a string"):
        store.create_person(123, "Alice")
    with pytest.raises(ValueError, match="must be a string"):
        store.create_person(True, "Alice")
    with pytest.raises(ValueError, match="must not contain control characters"):
        store.create_person("p_01\n", "Alice")
    with pytest.raises(ValueError, match="match"):
        store.create_person("bad id with spaces", "Alice")

    # Invalid name types / contents
    with pytest.raises(ValueError, match="must be a string"):
        store.create_person("p_01", 123)
    with pytest.raises(ValueError, match="length after stripping whitespace"):
        store.create_person("p_01", "   ")
    with pytest.raises(ValueError, match="control characters"):
        store.create_person("p_01", "Alice\0")


def test_store_people_transaction_rollback(monkeypatch):
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    orig_transaction = conn.transaction

    @contextlib.contextmanager
    def failing_transaction():
        with orig_transaction():
            yield
            raise RuntimeError("Injected DB failure on commit")

    monkeypatch.setattr(conn, "transaction", failing_transaction)

    with pytest.raises(RuntimeError, match="Injected DB failure on commit"):
        store.create_person("p_fail_tx", "Failed Alice")

    monkeypatch.undo()
    assert store.get_person("p_fail_tx") is None
    assert store.get_people() == []


def test_store_people_not_overwritten_by_matcher_replay():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)

    store.create_person("p_keep", "Permanent Person")
    store.handle_input("item", {
        "event_id": "i_replay_1", "topic": "item.event", "type": "PUT",
        "item_id": "milk", "item_label": "Milk", "ts": "2026-11-08T09:15:00.000Z",
        "confidence": 0.90
    }, StubMatcher())

    # Replay journal
    store.replay_journal(StubMatcher, expected_version=MATCHER_VERSION)

    # Verify people table was not cleared or mutated
    p = store.get_person("p_keep")
    assert p is not None
    assert p["name"] == "Permanent Person"


def test_migration_003_idempotent():
    conn = MockPostgresConn()
    store = PostgresStore(conn)

    # Running init_db multiple times must not raise or drop tables
    store.init_db()
    store.init_db()
    assert "people" in conn._committed_tables


def test_real_postgres_people_integration():
    dsn = get_real_postgres_dsn()
    if dsn is None:
        pytest.skip("TEST_POSTGRES_DSN not set; skipping live Postgres people integration test")

    import psycopg
    schema_name = f"test_people_{uuid.uuid4().hex[:8]}"

    try:
        with psycopg.connect(dsn, autocommit=True) as setup_conn:
            with setup_conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema_name};")
    except Exception as exc:
        pytest.fail(f"TEST_POSTGRES_DSN was set but schema creation failed: {exc}")

    try:
        # Separate live connections: connection 1 (writer/worker), connection 2 (reader)
        with psycopg.connect(dsn, autocommit=True) as conn1, psycopg.connect(dsn, autocommit=True) as conn2:
            worker_store = PostgresStore(conn1, schema=schema_name)
            read_store = PostgresStore(conn2, schema=schema_name)

            # 1. Simulate same-version 002-only upgrade in live test
            mig1 = Path(__file__).parents[1] / "migrations" / "001_initial.sql"
            mig2 = Path(__file__).parents[1] / "migrations" / "002_integration.sql"
            with conn1.cursor() as cur1:
                cur1.execute(f"SET search_path TO {schema_name};")
                cur1.execute(mig1.read_text(encoding="utf-8"))
                cur1.execute(mig2.read_text(encoding="utf-8"))
                cur1.execute(
                    f"INSERT INTO {schema_name}.matcher_version (id, version) VALUES (1, %s)",
                    (MATCHER_VERSION,),
                )
                # Verify people table does not exist yet
                cur1.execute(f"SELECT to_regclass('{schema_name}.people')")
                assert cur1.fetchone()[0] is None

            # Startup check_or_init_version upgrades database by acquiring missing 003_people table
            worker_store.check_or_init_version(MATCHER_VERSION)
            with conn2.cursor() as cur2:
                cur2.execute(f"SELECT to_regclass('{schema_name}.people')")
                assert cur2.fetchone()[0] is not None

            # 2. Insert person on worker_store and verify visibility on separate live read connection
            created = worker_store.create_person("p_real_01", "Real Alice")
            assert created["person_id"] == "p_real_01"
            assert created["name"] == "Real Alice"
            assert created["enrollment_status"] == "unknown"

            # Query via separate read connection
            read_person = read_store.get_person("p_real_01")
            assert read_person is not None
            assert read_person["name"] == "Real Alice"

            # 3. Duplicate rejection via ON CONFLICT DO NOTHING
            with pytest.raises(DuplicatePersonError):
                worker_store.create_person("p_real_01", "Duplicate Alice")

            # 4. Update on worker_store visible to separate read_store
            updated = worker_store.update_person("p_real_01", "Alice Updated")
            assert updated["name"] == "Alice Updated"
            read_updated = read_store.get_person("p_real_01")
            assert read_updated["name"] == "Alice Updated"

            # 5. Ordering visible across connections
            worker_store.create_person("p_real_00", "Zero")
            people = read_store.get_people()
            assert len(people) == 2
            assert people[0]["person_id"] == "p_real_00"
            assert people[1]["person_id"] == "p_real_01"

            # 6. Verify 003 idempotence: repeat check_or_init_version and verify row is retained
            worker_store.check_or_init_version(MATCHER_VERSION)
            retained = read_store.get_person("p_real_01")
            assert retained is not None
            assert retained["name"] == "Alice Updated"
    finally:
        with psycopg.connect(dsn, autocommit=True) as cleanup_conn:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
