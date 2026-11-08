"""Kafka event bus consumer, strict JSON schema validation, and offset commit management."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
import confluent_kafka
from jsonschema import Draft202012Validator, ValidationError

from fridge_backend.config import BackendConfig
from fridge_backend.store import PostgresStore

logger = logging.getLogger(__name__)


def _find_contracts_dir() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "contracts" / "person.seen.schema.json"
        if cand.is_file():
            return parent / "contracts"
    raise FileNotFoundError("Could not locate contracts directory")


CONTRACTS_DIR = _find_contracts_dir()
PERSON_SCHEMA = json.loads((CONTRACTS_DIR / "person.seen.schema.json").read_text(encoding="utf-8"))
ITEM_SCHEMA = json.loads((CONTRACTS_DIR / "item.event.schema.json").read_text(encoding="utf-8"))

PERSON_VALIDATOR = Draft202012Validator(PERSON_SCHEMA)
ITEM_VALIDATOR = Draft202012Validator(ITEM_SCHEMA)


def create_kafka_consumer(config: BackendConfig) -> confluent_kafka.Consumer:
    """Creates a configured Confluent Kafka Consumer with auto-commit/auto-store disabled."""
    conf = {
        "bootstrap.servers": config.kafka_bootstrap_servers,
        "group.id": config.kafka_group_id,
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
        "auto.offset.reset": "earliest",
    }
    consumer = confluent_kafka.Consumer(conf)
    consumer.subscribe([config.person_topic, config.item_topic])
    return consumer


def create_kafka_producer(config: BackendConfig) -> confluent_kafka.Producer:
    """Creates a configured Confluent Kafka Producer."""
    conf = {
        "bootstrap.servers": config.kafka_bootstrap_servers,
    }
    return confluent_kafka.Producer(conf)


class EventBus:
    def __init__(
        self,
        consumer: Any,
        store: PostgresStore,
        matcher: Any,
        person_topic: str = "person.seen",
        item_topic: str = "item.event",
    ) -> None:
        self.consumer = consumer
        self.store = store
        self.matcher = matcher
        self.person_topic = person_topic
        self.item_topic = item_topic

    def set_matcher(self, matcher: Any) -> None:
        """Update active Matcher instance (e.g. after replay recovery)."""
        self.matcher = matcher

    def poll_and_process(self, timeout: float = 1.0) -> bool:
        """Polls one message, validates schema, applies atomic store transaction, and commits offset.
        Returns True if a message was handled (or skipped safely), False if poll timed out.
        """
        msg = self.consumer.poll(timeout)
        if msg is None:
            return False

        if hasattr(msg, "error") and msg.error():
            err = msg.error()
            err_code = err.code() if hasattr(err, "code") else None
            if err_code == confluent_kafka.KafkaError._PARTITION_EOF:
                logger.debug("Reached end of partition: %s", err)
                return False
            else:
                logger.error("Fatal Kafka consumer error: %s", err)
                raise confluent_kafka.KafkaException(err)

        topic = msg.topic() if callable(getattr(msg, "topic", None)) else getattr(msg, "topic", "")
        raw_val = msg.value() if callable(getattr(msg, "value", None)) else getattr(msg, "value", None)
        offset_val = msg.offset() if callable(getattr(msg, "offset", None)) else getattr(msg, "offset", None)

        def acknowledge_and_skip(reason: str) -> bool:
            logger.warning(
                "Skipping invalid/unrecognized message on topic %s (offset %s): %s",
                topic,
                offset_val,
                reason,
            )
            self._commit_message(msg)
            return True

        if topic not in (self.person_topic, self.item_topic):
            return acknowledge_and_skip(f"Unrecognized topic: {topic}")

        if raw_val is None:
            return acknowledge_and_skip("Empty message payload")

        try:
            if isinstance(raw_val, (bytes, bytearray)):
                text_val = raw_val.decode("utf-8")
            else:
                text_val = str(raw_val)
            payload = json.loads(text_val)
        except Exception as exc:
            return acknowledge_and_skip(f"Malformed JSON: {exc}")

        if not isinstance(payload, dict):
            return acknowledge_and_skip(f"Expected JSON object dict, got {type(payload).__name__}")

        # Validate against strict contract schema
        try:
            if topic == self.person_topic:
                PERSON_VALIDATOR.validate(payload)
                kind = "person"
            else:
                ITEM_VALIDATOR.validate(payload)
                kind = "item"
        except ValidationError as val_err:
            return acknowledge_and_skip(f"Schema validation error: {val_err.message}")

        # Atomic database transaction: journal + Matcher + outbox
        # If this raises, DO NOT commit the offset, and allow exception to propagate.
        self.store.handle_input(kind, payload, self.matcher)

        # Success: commit the offset for this message
        self._commit_message(msg)
        return True

    def _commit_message(self, msg: Any) -> None:
        if hasattr(self.consumer, "commit"):
            res = self.consumer.commit(message=msg, asynchronous=False)
            if isinstance(res, (list, tuple)):
                for tp in res:
                    tp_err = getattr(tp, "error", None)
                    if tp_err:
                        if isinstance(tp_err, Exception):
                            raise tp_err
                        raise RuntimeError(f"Kafka commit error on {getattr(tp, 'topic', '')}[{getattr(tp, 'partition', '')}]: {tp_err}")

    def close(self) -> None:
        if hasattr(self.consumer, "close"):
            self.consumer.close()
