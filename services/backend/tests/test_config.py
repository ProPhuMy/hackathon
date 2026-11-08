"""Tests for backend configuration, environment parsing, sanitization, and validation."""

import pytest
from fridge_backend.config import BackendConfig, load_config, ConfigError


def test_default_config():
    cfg = BackendConfig()
    assert cfg.postgres_dsn == "postgresql://fridge:fridge@localhost:5432/fridge"
    assert cfg.kafka_bootstrap_servers == "localhost:19092"
    assert cfg.kafka_group_id == "fridge-backend-v1"
    assert cfg.person_topic == "person.seen"
    assert cfg.item_topic == "item.event"
    assert cfg.fridge_topic == "fridge.event"
    assert cfg.tick_interval_ms == 1000
    assert cfg.outbox_poll_interval_ms == 100
    assert cfg.api_host == "0.0.0.0"
    assert cfg.api_port == 8000


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://custom_user:pass@db:5432/test_db")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda.internal:9092")
    monkeypatch.setenv("KAFKA_GROUP_ID", "custom-group")
    monkeypatch.setenv("PERSON_TOPIC", "custom.person")
    monkeypatch.setenv("ITEM_TOPIC", "custom.item")
    monkeypatch.setenv("FRIDGE_TOPIC", "custom.fridge")
    monkeypatch.setenv("TICK_INTERVAL_MS", "2000")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_MS", "250")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "9000")

    cfg = load_config()
    assert cfg.postgres_dsn == "postgresql://custom_user:pass@db:5432/test_db"
    assert cfg.kafka_bootstrap_servers == "redpanda.internal:9092"
    assert cfg.kafka_group_id == "custom-group"
    assert cfg.person_topic == "custom.person"
    assert cfg.item_topic == "custom.item"
    assert cfg.fridge_topic == "custom.fridge"
    assert cfg.tick_interval_ms == 2000
    assert cfg.outbox_poll_interval_ms == 250
    assert cfg.api_host == "127.0.0.1"
    assert cfg.api_port == 9000


def test_invalid_postgres_dsn():
    with pytest.raises(ConfigError, match="postgres_dsn"):
        BackendConfig(postgres_dsn="")

    with pytest.raises(ConfigError, match="postgres_dsn"):
        BackendConfig(postgres_dsn="http://not-postgres")


def test_dsn_password_redaction_in_error():
    secret_pass = "super_secret_p@ssword!123"
    bad_dsn = f"mysql://user:{secret_pass}@localhost:3306/db"
    with pytest.raises(ConfigError) as exc_info:
        BackendConfig(postgres_dsn=bad_dsn)
    err_msg = str(exc_info.value)
    assert secret_pass not in err_msg, "Sensitive password must not leak into ConfigError message"


def test_invalid_integer_env_vars(monkeypatch):
    monkeypatch.setenv("TICK_INTERVAL_MS", "not-an-integer")
    with pytest.raises(ConfigError, match="TICK_INTERVAL_MS"):
        load_config()

    monkeypatch.setenv("TICK_INTERVAL_MS", "1000")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_MS", "xyz")
    with pytest.raises(ConfigError, match="OUTBOX_POLL_INTERVAL_MS"):
        load_config()


def test_boundary_intervals():
    with pytest.raises(ConfigError, match="tick_interval_ms"):
        BackendConfig(tick_interval_ms=0)

    with pytest.raises(ConfigError, match="tick_interval_ms"):
        BackendConfig(tick_interval_ms=-1)

    with pytest.raises(ConfigError, match="outbox_poll_interval_ms"):
        BackendConfig(outbox_poll_interval_ms=0)

    with pytest.raises(ConfigError, match="outbox_poll_interval_ms"):
        BackendConfig(outbox_poll_interval_ms=-10)


def test_invalid_api_host_and_port():
    with pytest.raises(ConfigError, match="api_host"):
        BackendConfig(api_host="")

    with pytest.raises(ConfigError, match="api_port"):
        BackendConfig(api_port=0)

    with pytest.raises(ConfigError, match="api_port"):
        BackendConfig(api_port=65536)

    with pytest.raises(ConfigError, match="api_port"):
        BackendConfig(api_port=-1)


def test_invalid_api_port_env(monkeypatch):
    monkeypatch.setenv("API_PORT", "not-a-port")
    with pytest.raises(ConfigError, match="API_PORT"):
        load_config()
