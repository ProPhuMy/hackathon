"""Tests for Kafka bus message parsing, contract schema validation, and offset commit management."""

import json
import pytest
from io_helpers import MockKafkaConsumer, MockKafkaMessage, MockPostgresConn
from fridge_backend.config import BackendConfig
from fridge_backend.bus import EventBus, create_kafka_consumer, create_kafka_producer
from fridge_backend.store import PostgresStore
from fridge_backend.matcher import MATCHER_VERSION
from test_store import StubMatcher


def test_client_factory_settings(monkeypatch):
    cfg = BackendConfig(
        kafka_bootstrap_servers="mybroker:9092",
        kafka_group_id="test-grp",
        person_topic="p.topic",
        item_topic="i.topic",
    )
    captured_consumer_conf = {}
    subscribed_topics = []

    class FakeConfluentConsumer:
        def __init__(self, conf):
            captured_consumer_conf.update(conf)

        def subscribe(self, topics):
            subscribed_topics.extend(topics)

    captured_producer_conf = {}

    class FakeConfluentProducer:
        def __init__(self, conf):
            captured_producer_conf.update(conf)

    import confluent_kafka
    monkeypatch.setattr(confluent_kafka, "Consumer", FakeConfluentConsumer)
    monkeypatch.setattr(confluent_kafka, "Producer", FakeConfluentProducer)

    consumer = create_kafka_consumer(cfg)
    assert captured_consumer_conf["bootstrap.servers"] == "mybroker:9092"
    assert captured_consumer_conf["group.id"] == "test-grp"
    assert captured_consumer_conf["enable.auto.commit"] is False
    assert captured_consumer_conf["enable.auto.offset.store"] is False
    assert captured_consumer_conf["auto.offset.reset"] == "earliest"
    assert set(subscribed_topics) == {"p.topic", "i.topic"}

    producer = create_kafka_producer(cfg)
    assert captured_producer_conf["bootstrap.servers"] == "mybroker:9092"


def test_partition_eof_ignored_real_error_raised():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    class FakeError:
        def __init__(self, code, name):
            self._code = code
            self._name = name

        def code(self):
            return self._code

        def __str__(self):
            return self._name

    import confluent_kafka
    eof_code = confluent_kafka.KafkaError._PARTITION_EOF

    # 1. Partition EOF message: ignored and returns False
    eof_msg = MockKafkaMessage(topic="person.seen", value=None, offset=1, error=FakeError(eof_code, "PARTITION_EOF"))
    consumer = MockKafkaConsumer([eof_msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)
    assert bus.poll_and_process(timeout=0.1) is False

    # 2. Fatal Kafka error: raises KafkaException so later offsets cannot overtake
    fatal_msg = MockKafkaMessage(topic="person.seen", value=None, offset=2, error=FakeError(999, "BrokerTransportFailure"))
    consumer2 = MockKafkaConsumer([fatal_msg])
    bus2 = EventBus(consumer=consumer2, store=store, matcher=matcher)
    with pytest.raises(confluent_kafka.KafkaException, match="BrokerTransportFailure"):
        bus2.poll_and_process(timeout=0.1)


def test_commit_error_on_topic_partition_result():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    valid_person = {
        "event_id": "p_valid",
        "topic": "person.seen",
        "track_id": 1,
        "person_id": "p_01",
        "ts": "2026-11-08T09:15:00.000Z",
        "confidence": 0.90,
    }
    msg = MockKafkaMessage(topic="person.seen", value=json.dumps(valid_person), offset=10)
    consumer = MockKafkaConsumer([msg])
    # Consumer commit returns TopicPartition with error
    consumer.commit_return_error = RuntimeError("TopicPartition offset commit failed")
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    with pytest.raises(RuntimeError, match="TopicPartition offset commit failed"):
        bus.poll_and_process(timeout=0.1)


def test_genuine_commit_failure_through_event_bus_and_redelivery():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    store.check_or_init_version(MATCHER_VERSION)
    matcher = StubMatcher()

    valid_item = {
        "event_id": "i_commit_fail_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.92,
    }
    msg = MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=50)

    # 1. Processing succeeds in DB, but Kafka commit throws genuine error
    consumer = MockKafkaConsumer([msg])
    consumer.fail_commit = True
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    with pytest.raises(RuntimeError, match="Injected Kafka commit failure"):
        bus.poll_and_process(timeout=0.1)

    # Matcher was called once and DB committed the event
    assert len(matcher.seen_events) == 1
    assert len(store.get_journal_records()) == 1

    # 2. Restart/recovery rebuilds Matcher from journal
    fresh_matcher = store.replay_journal(StubMatcher, expected_version=MATCHER_VERSION)
    assert len(fresh_matcher.seen_events) == 1

    # 3. Kafka redelivers the uncommitted message
    consumer_redelivery = MockKafkaConsumer([msg])
    bus_restarted = EventBus(consumer=consumer_redelivery, store=store, matcher=fresh_matcher)

    handled = bus_restarted.poll_and_process(timeout=0.1)
    assert handled is True
    # Crucial check: fresh_matcher was NOT called again! Duplicate state mutation was prevented.
    assert len(fresh_matcher.seen_events) == 1
    # Offset is successfully committed this time
    assert len(consumer_redelivery.committed_messages) == 1
    assert consumer_redelivery.committed_messages[0].offset() == 50


def test_malformed_json_skipped_and_offset_committed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    bad_msg = MockKafkaMessage(topic="person.seen", value=b"{bad json...", offset=10)
    consumer = MockKafkaConsumer([bad_msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    handled = bus.poll_and_process(timeout=0.1)
    assert handled is True
    assert len(matcher.seen_events) == 0
    assert len(store.get_journal_records()) == 0
    assert len(consumer.committed_messages) == 1
    assert consumer.committed_messages[0].offset() == 10


def test_non_dict_json_skipped_and_offset_committed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    non_dict_msg = MockKafkaMessage(topic="item.event", value=b"[1, 2, 3]", offset=20)
    consumer = MockKafkaConsumer([non_dict_msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    handled = bus.poll_and_process(timeout=0.1)
    assert handled is True
    assert len(matcher.seen_events) == 0
    assert len(consumer.committed_messages) == 1
    assert consumer.committed_messages[0].offset() == 20


def test_schema_invalid_message_skipped_and_offset_committed():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    invalid_person = {
        "event_id": "p_invalid",
        "topic": "person.seen",
        "track_id": 1,
        "person_id": "p_01",
        "ts": "2026-11-08T09:15:00.000Z",
    }
    msg = MockKafkaMessage(topic="person.seen", value=json.dumps(invalid_person), offset=30)
    consumer = MockKafkaConsumer([msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    handled = bus.poll_and_process(timeout=0.1)
    assert handled is True
    assert len(matcher.seen_events) == 0
    assert len(store.get_journal_records()) == 0
    assert len(consumer.committed_messages) == 1
    assert consumer.committed_messages[0].offset() == 30


def test_wrong_topic_message_skipped():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    msg = MockKafkaMessage(topic="random.topic", value=b"{}", offset=40)
    consumer = MockKafkaConsumer([msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    handled = bus.poll_and_process(timeout=0.1)
    assert handled is True
    assert len(matcher.seen_events) == 0
    assert len(consumer.committed_messages) == 1
    assert consumer.committed_messages[0].offset() == 40


def test_valid_message_commits_offset():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()

    valid_item = {
        "event_id": "i_valid_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.92,
    }
    msg = MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=50)
    consumer = MockKafkaConsumer([msg])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    handled = bus.poll_and_process(timeout=0.1)
    assert handled is True
    assert len(matcher.seen_events) == 1
    assert len(store.get_journal_records()) == 1
    assert len(consumer.committed_messages) == 1
    assert consumer.committed_messages[0].offset() == 50


def test_failed_valid_input_does_not_advance_kafka_offset():
    conn = MockPostgresConn()
    store = PostgresStore(conn)
    matcher = StubMatcher()
    matcher.should_fail = True

    valid_item = {
        "event_id": "i_fail_1",
        "topic": "item.event",
        "type": "PUT",
        "item_id": "item_001",
        "item_label": "Yogurt",
        "ts": "2026-11-08T09:15:01.000Z",
        "confidence": 0.92,
    }
    msg1 = MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=60)
    msg2 = MockKafkaMessage(topic="item.event", value=json.dumps(valid_item), offset=61)
    consumer = MockKafkaConsumer([msg1, msg2])
    bus = EventBus(consumer=consumer, store=store, matcher=matcher)

    with pytest.raises(RuntimeError, match="Injected Matcher on_item failure"):
        bus.poll_and_process(timeout=0.1)

    assert len(consumer.committed_messages) == 0
