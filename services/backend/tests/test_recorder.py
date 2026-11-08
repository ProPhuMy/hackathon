"""Tests for the minimal independent read-only Kafka recorder CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import uuid

import confluent_kafka
import pytest

from fridge_backend.recorder import (
    RECORDED_TOPICS,
    build_parser,
    check_output_path,
    create_recorder_consumer,
    main,
    resolve_bootstrap_servers,
    run_recorder,
)


class MockTopicPartition:
    """Mock Kafka TopicPartition for unit tests."""

    def __init__(self, topic: str, partition: int = 0, offset: int = -1001) -> None:
        self.topic = topic
        self.partition = partition
        self.offset = offset


class MockKafkaError:
    """Mock Kafka Error for unit tests."""

    def __init__(self, code: int, name: str = "ERROR") -> None:
        self._code = code
        self._name = name

    def code(self) -> int:
        return self._code

    def __str__(self) -> str:
        return self._name


class MockKafkaMessage:
    """Mock Kafka Message for unit tests matching confluent_kafka.Message interface."""

    def __init__(
        self,
        topic: str = "person.seen",
        value: bytes | None = None,
        error: MockKafkaError | None = None,
        offset: int = 0,
    ) -> None:
        self._topic = topic
        self._value = value
        self._error = error
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def value(self) -> bytes | None:
        return self._value

    def error(self) -> MockKafkaError | None:
        return self._error

    def offset(self) -> int:
        return self._offset


class MockKafkaConsumer:
    """Mock Kafka Consumer simulating assignment, subscription, polling, and teardown."""

    def __init__(self, conf: dict[str, Any] | None = None) -> None:
        self.conf = conf or {}
        self.subscribed_topics: list[str] = []
        self.on_assign_cb: Any = None
        self.assigned_partitions: list[MockTopicPartition] = []
        self.messages_queue: list[Any] = []
        self.is_closed = False
        self.poll_calls = 0

    def subscribe(self, topics: list[str], on_assign: Any = None) -> None:
        self.subscribed_topics = list(topics)
        self.on_assign_cb = on_assign

    def get_watermark_offsets(
        self, tp: Any, timeout: float = 5.0, cached: bool = False
    ) -> tuple[int, int]:
        return (0, 100)

    def assign(self, partitions: list[Any]) -> None:
        self.assigned_partitions = list(partitions)

    def trigger_assign(self, partitions: list[Any]) -> None:
        if self.on_assign_cb:
            self.on_assign_cb(self, partitions)

    def poll(self, timeout: float = 0.5) -> Any:
        self.poll_calls += 1
        if self.messages_queue:
            item = self.messages_queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        raise KeyboardInterrupt()

    def close(self) -> None:
        self.is_closed = True


class FailingFileWrapper:
    """Wrapper around a real file object to inject write or flush failures while forwarding close."""

    def __init__(self, real_file: Any, fail_on: str = "write") -> None:
        self._real_file = real_file
        self.fail_on = fail_on

    def write(self, s: str) -> int:
        if self.fail_on == "write":
            raise OSError("Injected write failure (disk full simulation)")
        return self._real_file.write(s)

    def flush(self) -> None:
        if self.fail_on == "flush":
            raise OSError("Injected flush failure simulation")
        return self._real_file.flush()

    def close(self) -> None:
        return self._real_file.close()

    @property
    def closed(self) -> bool:
        return self._real_file.closed

    def __enter__(self) -> FailingFileWrapper:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self._real_file.__exit__(exc_type, exc_val, exc_tb)


# ==============================================================================
# Unit Tests
# ==============================================================================


def test_build_parser_options() -> None:
    parser = build_parser()
    args = parser.parse_args(["/tmp/output.jsonl", "--bootstrap-servers", "mybroker:9092"])
    assert args.output_path == "/tmp/output.jsonl"
    assert args.bootstrap_servers == "mybroker:9092"

    args2 = parser.parse_args(["/tmp/output.jsonl"])
    assert args2.output_path == "/tmp/output.jsonl"
    assert args2.bootstrap_servers is None


def test_unique_group_and_consumer_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure production matcher group in environment is ignored
    monkeypatch.setenv("KAFKA_GROUP_ID", "production-matcher-group")

    captured_confs: list[dict[str, Any]] = []

    class FakeConfluentConsumer:
        def __init__(self, conf: dict[str, Any]) -> None:
            captured_confs.append(conf)

    monkeypatch.setattr(confluent_kafka, "Consumer", FakeConfluentConsumer)

    c1 = create_recorder_consumer("broker1:9092")
    c2 = create_recorder_consumer("broker1:9092")

    assert len(captured_confs) == 2
    conf1, conf2 = captured_confs[0], captured_confs[1]

    # Must start with fridge-recorder- and be a unique UUID
    assert conf1["group.id"].startswith("fridge-recorder-")
    assert conf2["group.id"].startswith("fridge-recorder-")
    assert conf1["group.id"] != conf2["group.id"]
    assert conf1["group.id"] != "production-matcher-group"

    # Auto-commit and offset store must be disabled; reset to latest
    assert conf1["enable.auto.commit"] is False
    assert conf1["enable.auto.offset.store"] is False
    assert conf1["auto.offset.reset"] == "latest"
    assert conf1["bootstrap.servers"] == "broker1:9092"


def test_resolve_bootstrap_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "envbroker:9092")
    assert resolve_bootstrap_servers("clibroker:9092") == "clibroker:9092"

    assert resolve_bootstrap_servers(None) == "envbroker:9092"

    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    assert resolve_bootstrap_servers(None) == "localhost:19092"


def test_exact_topic_subscription_and_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out_file = tmp_path / "test.jsonl"
    mock_consumer = MockKafkaConsumer()
    tp = MockTopicPartition("person.seen", 0)

    def fake_poll(timeout: float = 0.5) -> Any:
        mock_consumer.poll_calls += 1
        if mock_consumer.poll_calls == 1:
            mock_consumer.trigger_assign([tp])
            return None
        raise KeyboardInterrupt()

    mock_consumer.poll = fake_poll  # type: ignore[assignment]
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file), "--bootstrap-servers", "mock:9092"])
    assert status == 0

    assert set(mock_consumer.subscribed_topics) == set(RECORDED_TOPICS)
    assert tp.offset == 100
    assert mock_consumer.assigned_partitions == [tp]

    captured = capsys.readouterr()
    assert captured.err == "READY\n"
    assert mock_consumer.is_closed is True


def test_reassignment_fails_visibly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_file = tmp_path / "test.jsonl"
    mock_consumer = MockKafkaConsumer()
    tp1 = MockTopicPartition("person.seen", 0)
    tp2 = MockTopicPartition("item.event", 0)

    def fake_poll(timeout: float = 0.5) -> Any:
        mock_consumer.poll_calls += 1
        if mock_consumer.poll_calls == 1:
            mock_consumer.trigger_assign([tp1])
            return None
        elif mock_consumer.poll_calls == 2:
            mock_consumer.trigger_assign([tp2])
            return None
        raise KeyboardInterrupt()

    mock_consumer.poll = fake_poll  # type: ignore[assignment]
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    with pytest.raises(RuntimeError, match="Capture interrupted: partition reassignment detected"):
        run_recorder(output_path=out_file, bootstrap_servers="mock:9092")

    assert mock_consumer.is_closed is True


def test_refuse_partial_tail_without_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "partial.jsonl"
    content_without_newline = b'{"existing":"data"}'
    out_file.write_bytes(content_without_newline)

    consumer_created = False

    def fake_consumer(broker: str) -> MockKafkaConsumer:
        nonlocal consumer_created
        consumer_created = True
        return MockKafkaConsumer()

    monkeypatch.setattr("fridge_backend.recorder.create_recorder_consumer", fake_consumer)

    with pytest.raises(ValueError, match="lacks a trailing newline"):
        run_recorder(output_path=out_file, bootstrap_servers="mock:9092")

    assert consumer_created is False
    assert out_file.read_bytes() == content_without_newline

    status = main([str(out_file)])
    assert status == 1


def test_valid_sentinel_file_appends_without_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "valid.jsonl"
    sentinel = '{"sentinel":"initial_record"}\n'
    out_file.write_text(sentinel, encoding="utf-8")

    mock_consumer = MockKafkaConsumer()
    ev = {"event_id": "evt_1", "kind": "seen"}
    msg = MockKafkaMessage(topic="person.seen", value=json.dumps(ev).encode("utf-8"))
    mock_consumer.messages_queue.append(msg)

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file)])
    assert status == 0

    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == '{"sentinel":"initial_record"}'
    assert json.loads(lines[1]) == {"topic": "person.seen", "event": ev}
    assert mock_consumer.is_closed is True


def test_poll_order_with_backward_timestamps_and_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "order_dup.jsonl"
    mock_consumer = MockKafkaConsumer()

    ev_item = {"event_id": "item_01", "ts": "2026-11-08T10:00:10Z", "item": "milk"}
    ev_person = {"event_id": "pers_01", "ts": "2026-11-08T10:00:01Z", "person": "alice"}

    msg1 = MockKafkaMessage(topic="item.event", value=json.dumps(ev_item).encode("utf-8"))
    msg2 = MockKafkaMessage(topic="person.seen", value=json.dumps(ev_person).encode("utf-8"))
    msg3 = MockKafkaMessage(topic="item.event", value=json.dumps(ev_item).encode("utf-8"))

    mock_consumer.messages_queue.extend([msg1, msg2, msg3])

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file)])
    assert status == 0

    lines = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3

    assert lines[0] == {"topic": "item.event", "event": ev_item}
    assert lines[1] == {"topic": "person.seen", "event": ev_person}
    assert lines[2] == {"topic": "item.event", "event": ev_item}


def test_unicode_nulls_and_unknown_fields_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "unicode.jsonl"
    mock_consumer = MockKafkaConsumer()

    complex_event = {
        "event_id": "evt_uni",
        "label": "Hộp sữa tươi 1L",
        "actor": None,
        "nested": {"key": "giá trị", "active": True},
        "unknown_extra_metric": 42.5,
    }
    msg = MockKafkaMessage(
        topic="item.event",
        value=json.dumps(complex_event, ensure_ascii=False).encode("utf-8"),
    )
    mock_consumer.messages_queue.append(msg)

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file)])
    assert status == 0

    line = out_file.read_text(encoding="utf-8").strip()
    data = json.loads(line)
    assert data["topic"] == "item.event"
    assert data["event"] == complex_event
    assert "Hộp sữa tươi 1L" in line


def test_malformed_utf8_fails_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "bad_utf8.jsonl"
    mock_consumer = MockKafkaConsumer()
    msg = MockKafkaMessage(topic="item.event", value=b"\xff\xfe\x00\x01")
    mock_consumer.messages_queue.append(msg)

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file)])
    assert status == 1
    assert mock_consumer.is_closed is True
    assert not out_file.exists() or out_file.stat().st_size == 0


def test_malformed_json_and_non_object_fails_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "bad_json.jsonl"

    # Case A: Invalid JSON syntax
    mock_consumer_a = MockKafkaConsumer()
    mock_consumer_a.messages_queue.append(
        MockKafkaMessage(topic="item.event", value=b"{\"unclosed: json")
    )
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer_a
    )
    assert main([str(out_file)]) == 1
    assert mock_consumer_a.is_closed is True

    # Case B: JSON array instead of object
    mock_consumer_b = MockKafkaConsumer()
    mock_consumer_b.messages_queue.append(
        MockKafkaMessage(topic="item.event", value=b"[1, 2, 3]")
    )
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer_b
    )
    assert main([str(out_file)]) == 1
    assert mock_consumer_b.is_closed is True

    # Case C: Non-finite float (NaN) rejected by allow_nan=False
    mock_consumer_c = MockKafkaConsumer()
    mock_consumer_c.messages_queue.append(
        MockKafkaMessage(topic="item.event", value=b"{\"val\": NaN}")
    )
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer_c
    )
    assert main([str(out_file)]) == 1
    assert mock_consumer_c.is_closed is True


def test_partition_eof_ignored_and_fatal_error_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "eof.jsonl"
    mock_consumer = MockKafkaConsumer()

    eof_err = MockKafkaError(confluent_kafka.KafkaError._PARTITION_EOF, "PARTITION_EOF")
    eof_msg = MockKafkaMessage(error=eof_err)

    fatal_err = MockKafkaError(
        confluent_kafka.KafkaError._ALL_BROKERS_DOWN, "ALL_BROKERS_DOWN"
    )
    fatal_msg = MockKafkaMessage(error=fatal_err)

    ev = {"event_id": "valid_after_eof"}
    valid_msg = MockKafkaMessage(topic="person.seen", value=json.dumps(ev).encode("utf-8"))

    # 1. EOF is safely skipped, next valid message is recorded
    mock_consumer.messages_queue.extend([eof_msg, valid_msg])
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )
    assert main([str(out_file)]) == 0
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == ev

    # 2. Fatal broker error raises KafkaException and exits nonzero
    mock_consumer2 = MockKafkaConsumer()
    mock_consumer2.messages_queue.append(fatal_msg)
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer2
    )
    assert main([str(out_file)]) == 1
    assert mock_consumer2.is_closed is True


def test_file_write_flush_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Test write failure
    out_file_w = tmp_path / "write_fail.jsonl"
    mock_consumer_w = MockKafkaConsumer()
    msg_w = MockKafkaMessage(topic="person.seen", value=b"{\"event_id\":\"e1\"}")
    mock_consumer_w.messages_queue.append(msg_w)

    real_open = open
    wrapper_w: FailingFileWrapper | None = None

    def fake_open_write(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        nonlocal wrapper_w
        handle = real_open(path, mode, **kwargs)
        wrapper_w = FailingFileWrapper(handle, fail_on="write")
        return wrapper_w

    monkeypatch.setattr("fridge_backend.recorder.open", fake_open_write, raising=False)
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer_w
    )

    status_w = main([str(out_file_w)])
    assert status_w == 1
    assert mock_consumer_w.is_closed is True
    assert wrapper_w is not None and wrapper_w.closed is True

    # Test flush failure
    out_file_f = tmp_path / "flush_fail.jsonl"
    mock_consumer_f = MockKafkaConsumer()
    msg_f = MockKafkaMessage(topic="person.seen", value=b"{\"event_id\":\"e2\"}")
    mock_consumer_f.messages_queue.append(msg_f)

    wrapper_f: FailingFileWrapper | None = None

    def fake_open_flush(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        nonlocal wrapper_f
        handle = real_open(path, mode, **kwargs)
        wrapper_f = FailingFileWrapper(handle, fail_on="flush")
        return wrapper_f

    monkeypatch.setattr("fridge_backend.recorder.open", fake_open_flush, raising=False)
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer_f
    )

    status_f = main([str(out_file_f)])
    assert status_f == 1
    assert mock_consumer_f.is_closed is True
    assert wrapper_f is not None and wrapper_f.closed is True


def test_consumer_close_failure_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "close_fail.jsonl"
    mock_consumer = MockKafkaConsumer()

    def fake_close() -> None:
        mock_consumer.is_closed = True
        raise RuntimeError("Consumer close fatal error")

    mock_consumer.close = fake_close  # type: ignore[assignment]
    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    real_open = open
    recorded_handles: list[Any] = []

    def tracking_open(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        h = real_open(path, mode, **kwargs)
        recorded_handles.append(h)
        return h

    monkeypatch.setattr("fridge_backend.recorder.open", tracking_open, raising=False)

    status = main([str(out_file)])
    assert status == 1
    assert mock_consumer.is_closed is True
    assert len(recorded_handles) == 1 and recorded_handles[0].closed is True


@pytest.mark.parametrize("phase", ["subscribe", "watermark"])
def test_subscribe_or_watermark_failure_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    out_file = tmp_path / f"{phase}_fail.jsonl"
    mock_consumer = MockKafkaConsumer()

    if phase == "subscribe":
        def fake_subscribe(topics: list[str], on_assign: Any = None) -> None:
            raise RuntimeError("Subscribe broker connection failed")

        mock_consumer.subscribe = fake_subscribe  # type: ignore[assignment]
    elif phase == "watermark":
        tp = MockTopicPartition("person.seen", 0)

        def fake_get_watermark(
            tp_arg: Any, timeout: float = 5.0, cached: bool = False
        ) -> tuple[int, int]:
            raise RuntimeError("Watermark lookup timeout")

        mock_consumer.get_watermark_offsets = fake_get_watermark  # type: ignore[assignment]

        def fake_poll(timeout: float = 0.5) -> Any:
            mock_consumer.trigger_assign([tp])
            return None

        mock_consumer.poll = fake_poll  # type: ignore[assignment]

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    real_open = open
    recorded_handles: list[Any] = []

    def tracking_open(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        h = real_open(path, mode, **kwargs)
        recorded_handles.append(h)
        return h

    monkeypatch.setattr("fridge_backend.recorder.open", tracking_open, raising=False)

    status = main([str(out_file)])
    assert status == 1
    assert mock_consumer.is_closed is True
    assert len(recorded_handles) == 1 and recorded_handles[0].closed is True


def test_ctrl_c_graceful_cleanup_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "ctrl_c.jsonl"
    mock_consumer = MockKafkaConsumer()
    mock_consumer.messages_queue.append(KeyboardInterrupt())

    monkeypatch.setattr(
        "fridge_backend.recorder.create_recorder_consumer", lambda b: mock_consumer
    )

    status = main([str(out_file)])
    assert status == 0
    assert mock_consumer.is_closed is True


def test_cli_main_return_status(tmp_path: Path) -> None:
    assert main(["--help"]) == 0
    assert main(["/tmp/output.jsonl", "--extra-unsupported-flag"]) == 2

    dir_path = tmp_path / "a_directory"
    dir_path.mkdir()
    assert main([str(dir_path)]) == 1


# ==============================================================================
# Opt-in Live Integration Smoke Test
# ==============================================================================


def test_live_recorder_smoke(tmp_path: Path) -> None:
    """Smoke test running actual recorder CLI against a live Kafka broker.

    Requires TEST_KAFKA_BOOTSTRAP_SERVERS (e.g. localhost:29092); skipped otherwise.
    """
    broker = os.environ.get("TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not broker:
        pytest.skip("TEST_KAFKA_BOOTSTRAP_SERVERS not set; skipping live recorder smoke test.")

    import confluent_kafka.admin

    admin_client = confluent_kafka.admin.AdminClient({"bootstrap.servers": broker})
    topics_to_create = [
        confluent_kafka.admin.NewTopic("person.seen", num_partitions=1, replication_factor=1),
        confluent_kafka.admin.NewTopic("item.event", num_partitions=1, replication_factor=1),
    ]
    fs = admin_client.create_topics(topics_to_create)
    for _topic, f in fs.items():
        try:
            f.result(timeout=5.0)
        except confluent_kafka.KafkaException as exc:
            err = exc.args[0]
            if hasattr(err, "code") and err.code() == confluent_kafka.KafkaError.TOPIC_ALREADY_EXISTS:
                pass
            else:
                raise

    out_file = tmp_path / "live_rehearsal_capture.jsonl"
    sentinel_record = {"sentinel": "pre_existing_valid_line"}
    out_file.write_text(json.dumps(sentinel_record) + "\n", encoding="utf-8")

    stderr_log = tmp_path / "recorder_stderr.log"

    env = os.environ.copy()
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    cur_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{cur_pp}" if cur_pp else src_dir
    env["PYTHONUNBUFFERED"] = "1"

    stderr_f = open(stderr_log, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fridge_backend.recorder",
            str(out_file),
            "--bootstrap-servers",
            broker,
        ],
        env=env,
        stderr=stderr_f,
        stdout=subprocess.DEVNULL,
    )

    try:
        # Poll stderr log file with bounded wait for READY signal
        ready = False
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr_f.flush()
                err_content = stderr_log.read_text(encoding="utf-8") if stderr_log.exists() else ""
                pytest.fail(
                    f"Recorder exited early with code {proc.returncode}; stderr: {err_content}"
                )
            if stderr_log.exists():
                stderr_f.flush()
                content = stderr_log.read_text(encoding="utf-8")
                if "READY\n" in content:
                    ready = True
                    break
            time.sleep(0.05)

        assert ready, f"Recorder failed to signal READY; stderr: {stderr_log.read_text(encoding='utf-8')}"

        producer = confluent_kafka.Producer({"bootstrap.servers": broker})
        delivery_errors: list[Any] = []

        def ack(err: Any, msg: Any) -> None:
            if err:
                delivery_errors.append(err)

        uid_p = str(uuid.uuid4())
        uid_i = str(uuid.uuid4())

        # Exact contract-shaped person.seen payload
        ev_person = {
            "event_id": f"p_{uid_p}",
            "topic": "person.seen",
            "track_id": 1,
            "person_id": "p_01",
            "ts": "2026-11-08T12:00:10.000000Z",
            "confidence": 0.95,
        }
        # Exact contract-shaped item.event payload with backward timestamp & unicode item_label
        ev_item = {
            "event_id": f"i_{uid_i}",
            "topic": "item.event",
            "type": "TAKE",
            "item_id": f"item_{uid_i[:8]}",
            "item_label": "Hộp sữa tươi 1L",
            "ts": "2026-11-08T12:00:02.000000Z",
            "confidence": 0.85,
        }

        def await_file_records(expected_count: int, timeout: float = 15.0) -> list[str]:
            file_deadline = time.monotonic() + timeout
            while time.monotonic() < file_deadline:
                if proc.poll() is not None:
                    stderr_f.flush()
                    err_txt = stderr_log.read_text(encoding="utf-8") if stderr_log.exists() else ""
                    pytest.fail(
                        f"Recorder exited unexpectedly with code {proc.returncode}; stderr: {err_txt}"
                    )
                if out_file.exists():
                    lines = [
                        line.strip()
                        for line in out_file.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    if len(lines) >= expected_count:
                        return lines
                time.sleep(0.05)
            stderr_f.flush()
            err_txt = stderr_log.read_text(encoding="utf-8") if stderr_log.exists() else ""
            pytest.fail(
                f"Timed out waiting for {expected_count} records. stderr: {err_txt}"
            )

        # 1. Publish person.seen, assert delivery, and await append
        producer.produce(
            "person.seen",
            key=uid_p.encode("utf-8"),
            value=json.dumps(ev_person, ensure_ascii=False).encode("utf-8"),
            on_delivery=ack,
        )
        rem = producer.flush(timeout=5.0)
        assert rem == 0 and not delivery_errors, f"Produce person.seen failed: {delivery_errors}"
        lines_step1 = await_file_records(expected_count=2)
        assert json.loads(lines_step1[1]) == {"topic": "person.seen", "event": ev_person}

        # 2. Publish item.event with earlier ts, assert delivery, and await append
        producer.produce(
            "item.event",
            key=uid_i.encode("utf-8"),
            value=json.dumps(ev_item, ensure_ascii=False).encode("utf-8"),
            on_delivery=ack,
        )
        rem = producer.flush(timeout=5.0)
        assert rem == 0 and not delivery_errors, f"Produce item.event failed: {delivery_errors}"
        lines_step2 = await_file_records(expected_count=3)
        assert json.loads(lines_step2[2]) == {"topic": "item.event", "event": ev_item}

        # 3. Publish duplicate person.seen, assert delivery, and await append
        producer.produce(
            "person.seen",
            key=uid_p.encode("utf-8"),
            value=json.dumps(ev_person, ensure_ascii=False).encode("utf-8"),
            on_delivery=ack,
        )
        rem = producer.flush(timeout=5.0)
        assert rem == 0 and not delivery_errors, f"Produce duplicate person.seen failed: {delivery_errors}"
        final_lines = await_file_records(expected_count=4)

        # Final assertions
        assert len(final_lines) == 4
        assert json.loads(final_lines[0]) == sentinel_record
        assert json.loads(final_lines[1]) == {"topic": "person.seen", "event": ev_person}
        assert json.loads(final_lines[2]) == {"topic": "item.event", "event": ev_item}
        assert json.loads(final_lines[3]) == {"topic": "person.seen", "event": ev_person}

        # Backward timestamp preserved (no sorting by event ts)
        rec1 = json.loads(final_lines[1])
        rec2 = json.loads(final_lines[2])
        assert rec2["event"]["ts"] < rec1["event"]["ts"]

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        try:
            stderr_f.close()
        except Exception:
            pass
