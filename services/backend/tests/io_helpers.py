"""Test doubles and I/O helpers for store, bus, and loop controller tests."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from typing import Any, Callable
import pytest


def get_real_postgres_dsn() -> str | None:
    """Return TEST_POSTGRES_DSN if explicitly provided, or None."""
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if dsn is None:
        return None
    stripped = dsn.strip()
    return stripped if stripped else dsn


def get_real_kafka_bootstrap() -> str | None:
    """Return TEST_KAFKA_BOOTSTRAP_SERVERS if explicitly provided, or None."""
    boot = os.environ.get("TEST_KAFKA_BOOTSTRAP_SERVERS")
    if boot is None:
        return None
    stripped = boot.strip()
    return stripped if stripped else boot


class MockUvicornServer:
    def __init__(self):
        self.should_exit = False


class MockTopicPartition:
    def __init__(self, topic: str, partition: int, offset: int = -1, error: Any = None):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.error = error


class MockCursor:
    def __init__(self, conn: MockPostgresConn):
        self.conn = conn
        self._results: list[Any] = []
        self._idx = 0
        self.rowcount = 0

    def __enter__(self) -> MockCursor:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def execute(self, sql: str, params: Any = None) -> MockCursor:
        self.conn._check_active_tx()
        sql_clean = " ".join(sql.strip().split())
        sql_upper = sql_clean.upper()

        # Resolve state store (either active transaction working state or committed state)
        journal = self.conn._tx_journal if self.conn._in_transaction else self.conn._committed_journal
        fridge_events = self.conn._tx_fridge_events if self.conn._in_transaction else self.conn._committed_fridge_events
        outbox = self.conn._tx_outbox if self.conn._in_transaction else self.conn._committed_outbox
        people = self.conn._tx_people if self.conn._in_transaction else self.conn._committed_people
        tables_created = self.conn._tx_tables if self.conn._in_transaction else self.conn._committed_tables

        if "SET SEARCH_PATH" in sql_upper or "SET TRANSACTION" in sql_upper:
            self.rowcount = 0
            return self

        if "CREATE TABLE" in sql_upper or "CREATE INDEX" in sql_upper or "DROP SCHEMA" in sql_upper or "CREATE SCHEMA" in sql_upper:
            if self.conn._in_transaction:
                self.conn._tx_ddl.append(sql)
            else:
                self.conn._committed_ddl.append(sql)

            if "CREATE TABLE" in sql_upper:
                if "MATCHER_VERSION" in sql_upper:
                    tables_created.add("matcher_version")
                if "MATCHER_JOURNAL" in sql_upper:
                    tables_created.add("matcher_journal")
                if "FRIDGE_EVENTS" in sql_upper:
                    tables_created.add("fridge_events")
                if "OUTBOX" in sql_upper:
                    tables_created.add("outbox")
                if "PEOPLE" in sql_upper:
                    tables_created.add("people")
            self.rowcount = 0
            return self

        if "TO_REGCLASS" in sql_upper or "INFORMATION_SCHEMA.TABLES" in sql_upper:
            # Check table existence
            t_name = params[0].replace("'", "") if params else "matcher_version"
            t_clean = t_name.split(".")[-1]
            exists = t_clean in tables_created
            if "TO_REGCLASS" in sql_upper:
                self._results = [(t_clean if exists else None,)]
            else:
                self._results = [(exists,)]
            self._idx = 0
            self.rowcount = 1
            return self

        if "INSERT INTO" in sql_upper and "MATCHER_VERSION" in sql_upper:
            v = params[1] if len(params) > 1 else params[0]
            if self.conn._in_transaction:
                self.conn._tx_version = v
            else:
                self.conn._committed_version = v
            tables_created.add("matcher_version")
            self.rowcount = 1
            return self

        if "SELECT VERSION FROM" in sql_upper and "MATCHER_VERSION" in sql_upper:
            v = self.conn._tx_version if self.conn._in_transaction else self.conn._committed_version
            if v is not None:
                self._results = [(v,)]
            else:
                self._results = []
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "SELECT EXISTS(SELECT 1 FROM" in sql_upper and "MATCHER_JOURNAL" in sql_upper:
            event_id = params[0]
            exists = any(r["event_id"] == event_id for r in journal)
            self._results = [(exists,)]
            self._idx = 0
            self.rowcount = 1
            return self

        if "SELECT 1 FROM" in sql_upper and "SELECT EXISTS" not in sql_upper:
            if "MATCHER_JOURNAL" in sql_upper:
                self._results = [(1,)] if journal else []
            elif "FRIDGE_EVENTS" in sql_upper:
                self._results = [(1,)] if fridge_events else []
            elif "OUTBOX" in sql_upper:
                self._results = [(1,)] if outbox else []
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "SELECT ID FROM" in sql_upper and "OUTBOX WHERE EVENT_ID" in sql_upper:
            eid = params[0]
            matched = [r["id"] for r in outbox if r["event_id"] == eid]
            self._results = [(mid,) for mid in matched]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "FROM" in sql_upper and "OUTBOX" in sql_upper and "FRIDGE_EVENTS" in sql_upper:
            # Joined query between outbox and fridge_events
            items = []
            for o in sorted(outbox, key=lambda x: x["id"]):
                eid = o["event_id"]
                if eid in fridge_events:
                    items.append((o["id"], o["event_id"], copy.deepcopy(fridge_events[eid])))

            # Filters
            if "O.ID >" in sql_upper or "OUTBOX.ID >" in sql_upper:
                gt_id = params[0]
                items = [it for it in items if it[0] > gt_id]
            if "WRONG_OWNER" in sql_upper:
                items = [it for it in items if it[2].get("status") in ("wrong_owner", "uncertain")]

            # Ordering
            if "DESC" in sql_upper:
                items = list(reversed(items))

            # Limit
            if "LIMIT" in sql_upper and params:
                lim = params[-1]
                if isinstance(lim, int):
                    items = items[:lim]

            select_part = sql_upper.split("FROM")[0]
            if "F.PAYLOAD" in select_part and "O.ID" not in select_part:
                self._results = [(it[2],) for it in items]
            elif "O.ID" in select_part and "F.PAYLOAD" in select_part and "O.EVENT_ID" not in select_part:
                self._results = [(it[0], it[2]) for it in items]
            elif "O.EVENT_ID" in select_part:
                self._results = [(it[0], it[1], it[2]) for it in items]
            else:
                self._results = [(it[0], it[2]) for it in items]

            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "INSERT INTO" in sql_upper and "MATCHER_JOURNAL" in sql_upper:
            kind, payload, event_id = params
            payload_obj = json.loads(payload) if isinstance(payload, str) else copy.deepcopy(payload)

            if event_id is not None:
                for row in journal:
                    if row["event_id"] == event_id:
                        raise self.conn.IntegrityError(f"duplicate key value violates unique constraint matcher_journal_event_id_key: {event_id}")

            self.conn._next_seq += 1
            seq = self.conn._next_seq
            row = {"seq": seq, "kind": kind, "payload": payload_obj, "event_id": event_id}
            journal.append(row)
            self._results = [(seq,)]
            self._idx = 0
            self.rowcount = 1
            return self

        if "SELECT EXISTS(SELECT 1 FROM" in sql_upper and "MATCHER_JOURNAL" in sql_upper:
            event_id = params[0]
            exists = any(r["event_id"] == event_id for r in journal)
            self._results = [(exists,)]
            self._idx = 0
            self.rowcount = 1
            return self

        if "SELECT SEQ, KIND, PAYLOAD, EVENT_ID FROM" in sql_upper and "MATCHER_JOURNAL" in sql_upper:
            rows = sorted(journal, key=lambda r: r["seq"])
            self._results = [(r["seq"], r["kind"], r["payload"], r["event_id"]) for r in rows]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "INSERT INTO" in sql_upper and "FRIDGE_EVENTS" in sql_upper:
            event_id, payload = params
            payload_obj = json.loads(payload) if isinstance(payload, str) else copy.deepcopy(payload)

            if event_id in fridge_events:
                raise self.conn.IntegrityError(f"duplicate key value violates unique constraint fridge_events_pkey: {event_id}")

            fridge_events[event_id] = payload_obj
            self.rowcount = 1
            return self

        if "FROM" in sql_upper and "FRIDGE_EVENTS" in sql_upper and "GROUP BY" in sql_upper:
            # Aggregate trends query over fridge_events
            start_str = params[0]
            end_str = params[1]
            owner_filter = params[2] if len(params) > 2 else None

            s_clean = start_str.strip()
            if s_clean.endswith("Z") or s_clean.endswith("z"):
                s_clean = s_clean[:-1] + "+00:00"
            start_dt = datetime.fromisoformat(s_clean).astimezone(timezone.utc)

            e_clean = end_str.strip()
            if e_clean.endswith("Z") or e_clean.endswith("z"):
                e_clean = e_clean[:-1] + "+00:00"
            end_dt = datetime.fromisoformat(e_clean).astimezone(timezone.utc)

            grouped: dict[tuple[Any, Any, Any, Any], int] = {}
            for ev in fridge_events.values():
                ev_ts_str = ev.get("ts")
                if not ev_ts_str:
                    continue
                ev_clean = ev_ts_str.strip()
                if ev_clean.endswith("Z") or ev_clean.endswith("z"):
                    ev_clean = ev_clean[:-1] + "+00:00"
                ev_dt = datetime.fromisoformat(ev_clean).astimezone(timezone.utc)

                if not (start_dt <= ev_dt < end_dt):
                    continue

                ev_owner = ev.get("owner_id")
                if owner_filter is not None and ev_owner != owner_filter:
                    continue

                key = (ev.get("type"), ev.get("status"), ev.get("person_id"), ev_owner)
                grouped[key] = grouped.get(key, 0) + 1

            self._results = [(k[0], k[1], k[2], k[3], count) for k, count in grouped.items()]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "SELECT EVENT_ID, PAYLOAD FROM" in sql_upper and "FRIDGE_EVENTS" in sql_upper:
            self._results = [(eid, copy.deepcopy(p)) for eid, p in fridge_events.items()]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "INSERT INTO" in sql_upper and "OUTBOX" in sql_upper:
            event_id, topic, payload, status = params
            payload_obj = json.loads(payload) if isinstance(payload, str) else copy.deepcopy(payload)

            if event_id not in fridge_events:
                raise self.conn.IntegrityError(f"insert on table 'outbox' violates foreign key constraint: {event_id}")

            self.conn._next_outbox_id += 1
            oid = self.conn._next_outbox_id
            outbox.append({
                "id": oid,
                "event_id": event_id,
                "topic": topic,
                "payload": payload_obj,
                "status": status,
                "published_at": None,
            })
            self._results = [(oid,)]
            self._idx = 0
            self.rowcount = 1
            return self

        if "SELECT ID, EVENT_ID, TOPIC, PAYLOAD FROM" in sql_upper and "OUTBOX WHERE STATUS = 'PENDING'" in sql_upper:
            pending = [r for r in outbox if r["status"] == "pending"]
            self._results = [(r["id"], r["event_id"], r["topic"], copy.deepcopy(r["payload"])) for r in pending]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "UPDATE" in sql_upper and "OUTBOX SET STATUS = 'PUBLISHED'" in sql_upper:
            target_id = params[0]
            updated = 0
            for r in outbox:
                if r["id"] == target_id and r["status"] == "pending":
                    r["status"] = "published"
                    r["published_at"] = "2026-11-08T09:15:00.000Z"
                    updated += 1
            self.rowcount = updated
            return self

        if "INSERT INTO" in sql_upper and "PEOPLE" in sql_upper:
            person_id, name = params
            if person_id in people:
                if "ON CONFLICT" in sql_upper:
                    self._results = []
                    self.rowcount = 0
                    return self
                raise self.conn.IntegrityError(f"duplicate key value violates unique constraint people_pkey: {person_id}")

            now_dt = datetime(2026, 11, 8, 9, 15, 0, tzinfo=timezone.utc)
            rec = {
                "person_id": person_id,
                "name": name,
                "created_at": now_dt,
                "updated_at": now_dt,
            }
            people[person_id] = rec
            if "RETURNING" in sql_upper:
                self._results = [(person_id, name, rec["created_at"], rec["updated_at"])]
            self.rowcount = 1
            return self

        if "SELECT" in sql_upper and "FROM" in sql_upper and "PEOPLE" in sql_upper:
            if "WHERE PERSON_ID" in sql_upper:
                pid = params[0]
                if pid in people:
                    rec = people[pid]
                    self._results = [(rec["person_id"], rec["name"], rec["created_at"], rec["updated_at"])]
                else:
                    self._results = []
            else:
                sorted_p = sorted(people.values(), key=lambda x: x["person_id"])
                self._results = [(rec["person_id"], rec["name"], rec["created_at"], rec["updated_at"]) for rec in sorted_p]
            self._idx = 0
            self.rowcount = len(self._results)
            return self

        if "UPDATE" in sql_upper and "PEOPLE" in sql_upper:
            # Expected params: (name, person_id)
            name, person_id = params
            if person_id in people:
                rec = people[person_id]
                rec["name"] = name
                rec["updated_at"] = datetime(2026, 11, 8, 9, 15, 1, tzinfo=timezone.utc)
                if "RETURNING" in sql_upper:
                    self._results = [(person_id, name, rec["created_at"], rec["updated_at"])]
                self._idx = 0
                self.rowcount = 1
            else:
                self._results = []
                self._idx = 0
                self.rowcount = 0
            return self

        raise NotImplementedError(f"Mock SQL not implemented: {sql}")

    def fetchone(self) -> Any:
        if self._idx < len(self._results):
            res = self._results[self._idx]
            self._idx += 1
            return res
        return None

    def fetchall(self) -> list[Any]:
        res = self._results[self._idx:]
        self._idx = len(self._results)
        return res

    def close(self) -> None:
        pass


class MockTransaction:
    def __init__(self, conn: MockPostgresConn):
        self.conn = conn

    def __enter__(self) -> MockTransaction:
        self.conn._begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn._rollback()
        else:
            self.conn._commit()


class MockPostgresConn:
    class IntegrityError(Exception):
        pass

    class OperationalError(Exception):
        pass

    def __init__(self, autocommit: bool = True):
        self.autocommit = autocommit
        # Committed state
        self._committed_journal: list[dict] = []
        self._committed_fridge_events: dict[str, dict] = {}
        self._committed_outbox: list[dict] = []
        self._committed_people: dict[str, dict] = {}
        self._committed_version: str | None = None
        self._committed_tables: set[str] = set()
        self._committed_ddl: list[str] = []
        self._next_seq = 0
        self._next_outbox_id = 0

        # Transaction working state
        self._tx_journal: list[dict] = []
        self._tx_fridge_events: dict[str, dict] = {}
        self._tx_outbox: list[dict] = []
        self._tx_people: dict[str, dict] = {}
        self._tx_version: str | None = None
        self._tx_tables: set[str] = set()
        self._tx_ddl: list[str] = []
        self._in_transaction = False
        self.is_closed = False

    @property
    def executed_ddl(self) -> list[str]:
        return list(self._committed_ddl)

    def _check_active_tx(self):
        if self.is_closed:
            raise self.OperationalError("Connection is closed")

    def _begin(self):
        self._in_transaction = True
        self._tx_journal = copy.deepcopy(self._committed_journal)
        self._tx_fridge_events = copy.deepcopy(self._committed_fridge_events)
        self._tx_outbox = copy.deepcopy(self._committed_outbox)
        self._tx_people = copy.deepcopy(self._committed_people)
        self._tx_version = self._committed_version
        self._tx_tables = set(self._committed_tables)
        self._tx_ddl = []

    def _commit(self):
        if not self._in_transaction:
            return
        self._committed_journal = copy.deepcopy(self._tx_journal)
        self._committed_fridge_events = copy.deepcopy(self._tx_fridge_events)
        self._committed_outbox = copy.deepcopy(self._tx_outbox)
        self._committed_people = copy.deepcopy(self._tx_people)
        self._committed_version = self._tx_version
        self._committed_tables = set(self._tx_tables)
        self._committed_ddl.extend(self._tx_ddl)
        self._tx_ddl = []
        self._in_transaction = False

    def _rollback(self):
        if not self._in_transaction:
            return
        self._tx_journal = copy.deepcopy(self._committed_journal)
        self._tx_fridge_events = copy.deepcopy(self._committed_fridge_events)
        self._tx_outbox = copy.deepcopy(self._committed_outbox)
        self._tx_people = copy.deepcopy(self._committed_people)
        self._tx_version = self._committed_version
        self._tx_tables = set(self._committed_tables)
        self._tx_ddl = []
        self._in_transaction = False

    def transaction(self) -> MockTransaction:
        return MockTransaction(self)

    def cursor(self) -> MockCursor:
        return MockCursor(self)

    def close(self):
        self.is_closed = True


class MockKafkaMessage:
    def __init__(self, topic: str, value: bytes | str | None, offset: int, partition: int = 0, error: Any = None):
        self._topic = topic
        if isinstance(value, str):
            self._value = value.encode("utf-8")
        else:
            self._value = value
        self._offset = offset
        self._partition = partition
        self._error = error

    def topic(self) -> str:
        return self._topic

    def value(self) -> bytes | None:
        return self._value

    def offset(self) -> int:
        return self._offset

    def partition(self) -> int:
        return self._partition

    def error(self) -> Any:
        return self._error


class MockKafkaConsumer:
    def __init__(self, messages: list[MockKafkaMessage] | None = None):
        self.queue = list(messages) if messages else []
        self.subscribed_topics: list[str] = []
        self.committed_messages: list[MockKafkaMessage] = []
        self.closed = False
        self.fail_commit = False
        self.commit_return_error: Any = None

    def subscribe(self, topics: list[str]):
        self.subscribed_topics = list(topics)

    def poll(self, timeout: float = 0.0) -> MockKafkaMessage | None:
        if self.closed or not self.queue:
            return None
        return self.queue.pop(0)

    def commit(self, message: Any = None, offsets: Any = None, asynchronous: bool = False):
        if self.fail_commit:
            raise RuntimeError("Injected Kafka commit failure")
        if self.commit_return_error:
            # Return TopicPartition with error
            t = message.topic() if message else "unknown"
            p = message.partition() if message else 0
            return [MockTopicPartition(topic=t, partition=p, error=self.commit_return_error)]
        if message is not None:
            self.committed_messages.append(message)
        return []

    def close(self):
        self.closed = True


class MockKafkaProducer:
    def __init__(self, fail_delivery: bool = False, timeout_flush: bool = False):
        self.fail_delivery = fail_delivery
        self.timeout_flush = timeout_flush
        self.published_messages: list[tuple[str, str, dict]] = []
        self._callbacks: list[tuple[Callable, Any, Any]] = []

    def produce(self, topic: str, key: str | None, value: str, on_delivery: Callable | None = None):
        val_obj = json.loads(value)
        self.published_messages.append((topic, key or "", val_obj))
        if on_delivery:
            if self.fail_delivery:
                err = RuntimeError("Broker rejected message")
                self._callbacks.append((on_delivery, err, None))
            else:
                msg = MockKafkaMessage(topic=topic, value=value, offset=len(self.published_messages) - 1)
                self._callbacks.append((on_delivery, None, msg))

    def flush(self, timeout: float = 1.0) -> int:
        if self.timeout_flush:
            # Did not call callbacks, returned queue length > 0
            return len(self._callbacks)
        callbacks = list(self._callbacks)
        self._callbacks.clear()
        for cb, err, msg in callbacks:
            cb(err, msg)
        return 0

    def poll(self, timeout: float = 0.0) -> int:
        return self.flush(timeout)
