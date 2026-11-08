"""Configuration management and environment variable parsing for fridge-backend."""

from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigError(ValueError):
    """Raised when configuration values are missing, invalid, or out of range."""
    pass


@dataclass
class BackendConfig:
    postgres_dsn: str = "postgresql://fridge:fridge@localhost:5432/fridge"
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_group_id: str = "fridge-backend-v1"
    person_topic: str = "person.seen"
    item_topic: str = "item.event"
    fridge_topic: str = "fridge.event"
    tick_interval_ms: int = 1000
    outbox_poll_interval_ms: int = 100
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def __post_init__(self) -> None:
        if not self.postgres_dsn or not (
            self.postgres_dsn.startswith("postgresql://") or self.postgres_dsn.startswith("postgres://")
        ):
            # Omit sensitive credentials/passwords from error message
            raise ConfigError("postgres_dsn must be a valid non-empty postgresql URL (e.g. postgresql://user:pass@host:port/db)")

        if not self.kafka_bootstrap_servers or not self.kafka_bootstrap_servers.strip():
            raise ConfigError("kafka_bootstrap_servers must be a non-empty string")

        if not self.kafka_group_id or not self.kafka_group_id.strip():
            raise ConfigError("kafka_group_id must be a non-empty string")

        if not self.person_topic or not self.person_topic.strip():
            raise ConfigError("person_topic must be a non-empty string")

        if not self.item_topic or not self.item_topic.strip():
            raise ConfigError("item_topic must be a non-empty string")

        if not self.fridge_topic or not self.fridge_topic.strip():
            raise ConfigError("fridge_topic must be a non-empty string")

        if self.tick_interval_ms <= 0:
            raise ConfigError(
                f"tick_interval_ms must be a positive integer, got {self.tick_interval_ms}"
            )

        if self.outbox_poll_interval_ms <= 0:
            raise ConfigError(
                f"outbox_poll_interval_ms must be a positive integer, got {self.outbox_poll_interval_ms}"
            )

        if not self.api_host or not self.api_host.strip():
            raise ConfigError("api_host must be a non-empty string")

        if not (1 <= self.api_port <= 65535):
            raise ConfigError(f"api_port must be between 1 and 65535, got {self.api_port}")


def load_config() -> BackendConfig:
    """Load configuration from environment variables with defaults."""
    tick_str = os.environ.get("TICK_INTERVAL_MS")
    if tick_str:
        try:
            tick_ms = int(tick_str)
        except ValueError:
            raise ConfigError(f"Invalid integer for TICK_INTERVAL_MS: {tick_str!r}")
    else:
        tick_ms = 1000

    outbox_str = os.environ.get("OUTBOX_POLL_INTERVAL_MS")
    if outbox_str:
        try:
            outbox_ms = int(outbox_str)
        except ValueError:
            raise ConfigError(f"Invalid integer for OUTBOX_POLL_INTERVAL_MS: {outbox_str!r}")
    else:
        outbox_ms = 100

    port_str = os.environ.get("API_PORT")
    if port_str:
        try:
            api_port = int(port_str)
        except ValueError:
            raise ConfigError(f"Invalid integer for API_PORT: {port_str!r}")
    else:
        api_port = 8000

    return BackendConfig(
        postgres_dsn=os.environ.get("POSTGRES_DSN", "postgresql://fridge:fridge@localhost:5432/fridge"),
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        kafka_group_id=os.environ.get("KAFKA_GROUP_ID", "fridge-backend-v1"),
        person_topic=os.environ.get("PERSON_TOPIC", "person.seen"),
        item_topic=os.environ.get("ITEM_TOPIC", "item.event"),
        fridge_topic=os.environ.get("FRIDGE_TOPIC", "fridge.event"),
        tick_interval_ms=tick_ms,
        outbox_poll_interval_ms=outbox_ms,
        api_host=os.environ.get("API_HOST", "0.0.0.0"),
        api_port=api_port,
    )
