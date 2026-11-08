"""Minimal independent read-only Kafka recorder CLI for rehearsal residual measurements.

Subscribes strictly to person.seen and item.event, assigns high watermarks for live-only
recording, and appends raw published events preserving all field values and unknown fields
to a compact JSONL file.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any
import uuid

import confluent_kafka

logger = logging.getLogger(__name__)

RECORDED_TOPICS = ("person.seen", "item.event")


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser with exact required arguments only."""
    parser = argparse.ArgumentParser(
        description="Record person.seen and item.event streams to a compact JSONL file."
    )
    parser.add_argument(
        "output_path",
        metavar="OUTPUT_PATH",
        type=str,
        help="Path to output JSONL file (opened in append mode, never truncated).",
    )
    parser.add_argument(
        "--bootstrap-servers",
        metavar="HOSTS",
        dest="bootstrap_servers",
        default=None,
        help="Kafka bootstrap broker list (defaults to KAFKA_BOOTSTRAP_SERVERS or localhost:19092).",
    )
    return parser


def check_output_path(path: Path) -> None:
    """Refuses directories or non-empty files that do not end with a newline."""
    if path.exists():
        if path.is_dir():
            raise IsADirectoryError(f"Output path is a directory: {path}")
        size = path.stat().st_size
        if size > 0:
            with open(path, "rb") as f:
                f.seek(size - 1)
                last_byte = f.read(1)
                if last_byte != b"\n":
                    raise ValueError(
                        f"Refusing to append: existing file '{path}' is not empty and lacks a trailing newline."
                    )


def resolve_bootstrap_servers(bootstrap_servers: str | None) -> str:
    """Resolves Kafka bootstrap servers from CLI argument, environment, or default."""
    if bootstrap_servers:
        return bootstrap_servers
    env_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if env_servers:
        return env_servers
    return "localhost:19092"


def create_recorder_consumer(bootstrap_servers: str) -> confluent_kafka.Consumer:
    """Creates a Kafka Consumer with a unique ephemeral group ID and auto-commit disabled."""
    group_id = f"fridge-recorder-{uuid.uuid4()}"
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
        "auto.offset.reset": "latest",
    }
    return confluent_kafka.Consumer(conf)


def run_recorder(
    output_path: str | Path,
    bootstrap_servers: str | None = None,
) -> None:
    """Runs the recorder loop, appending incoming Kafka events to output_path.

    Pre-checks output file tail before creating the consumer, fixes high offsets on assign,
    signals READY to stderr, and ensures all file/consumer resources close cleanly.
    """
    out_p = Path(output_path).resolve()
    # Check tail before consumer creation to avoid opening consumer on invalid output paths
    check_output_path(out_p)

    resolved_broker = resolve_bootstrap_servers(bootstrap_servers)

    with open(out_p, "a", encoding="utf-8", newline="\n") as out_file:
        consumer = create_recorder_consumer(resolved_broker)
        try:
            assigned_once = False
            reassignment_error: Exception | None = None

            def on_assign(c: Any, partitions: list[Any]) -> None:
                nonlocal assigned_once, reassignment_error
                if assigned_once:
                    reassignment_error = RuntimeError(
                        "Capture interrupted: partition reassignment detected during live recording"
                    )
                    return

                try:
                    for tp in partitions:
                        _low, high = c.get_watermark_offsets(tp, timeout=5.0, cached=False)
                        tp.offset = high
                    c.assign(partitions)
                    assigned_once = True
                    sys.stderr.write("READY\n")
                    sys.stderr.flush()
                except Exception as exc:
                    reassignment_error = exc
                    raise

            consumer.subscribe(list(RECORDED_TOPICS), on_assign=on_assign)

            while True:
                if reassignment_error is not None:
                    raise reassignment_error

                msg = consumer.poll(0.5)

                if reassignment_error is not None:
                    raise reassignment_error

                if msg is None:
                    continue

                err = msg.error()
                if err:
                    if err.code() == confluent_kafka.KafkaError._PARTITION_EOF:
                        continue
                    raise confluent_kafka.KafkaException(err)

                topic = msg.topic()
                raw_val = msg.value()
                if raw_val is None:
                    raise ValueError(f"Empty payload on topic '{topic}'")

                text_val = raw_val.decode("utf-8")
                payload = json.loads(text_val)
                if not isinstance(payload, dict):
                    raise ValueError(
                        f"Expected JSON object dict on topic '{topic}', got {type(payload).__name__}"
                    )

                # Compact UTF-8 JSON line; reject non-finite float values
                record = {"topic": topic, "event": payload}
                serialized = json.dumps(
                    record,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ) + "\n"

                out_file.write(serialized)
                out_file.flush()
        finally:
            consumer.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint returning 0 on clean exit / Ctrl+C, nonzero on failure."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    try:
        run_recorder(
            output_path=Path(args.output_path),
            bootstrap_servers=args.bootstrap_servers,
        )
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        sys.stderr.write(f"Recorder error: {exc}\n")
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
