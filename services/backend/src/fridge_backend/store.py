"""Postgres storage, matcher call journal, transactional outbox, and deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable
from jsonschema import Draft202012Validator

logger = logging.getLogger(__name__)


def _find_contracts_dir() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "contracts" / "fridge.event.schema.json"
        if cand.is_file():
            return parent / "contracts"
    raise FileNotFoundError("Could not find contracts directory")


SCHEMA_PATH = _find_contracts_dir() / "fridge.event.schema.json"
FRIDGE_EVENT_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(FRIDGE_EVENT_SCHEMA)


class ReplayMismatchError(RuntimeError):
    """Raised when replaying the journal produces outputs differing from stored fridge events."""
    pass


class VersionMismatchError(RuntimeError):
    """Raised when stored matcher version mismatches or unversioned legacy state is detected."""
    pass


class DuplicatePersonError(ValueError):
    """Raised when inserting a person with an already existing person_id."""
    pass


def validate_person_id(person_id: Any) -> str:
    if not isinstance(person_id, str) or isinstance(person_id, bool):
        raise ValueError(f"person_id must be a string, got {type(person_id).__name__}")
    if not (1 <= len(person_id) <= 64):
        raise ValueError(f"person_id length must be between 1 and 64, got {len(person_id)}")
    if not re.match(r"^[a-zA-Z0-9_-]+$", person_id):
        raise ValueError(f"person_id must match ^[a-zA-Z0-9_-]+$, got {person_id!r}")
    if any(c in person_id for c in ("\r", "\n", "\0")):
        raise ValueError(f"person_id must not contain control characters: {person_id!r}")
    return person_id


def validate_name(name: Any) -> str:
    if not isinstance(name, str) or isinstance(name, bool):
        raise ValueError(f"name must be a string, got {type(name).__name__}")
    cleaned = name.strip()
    if not (1 <= len(cleaned) <= 100):
        raise ValueError(f"name length after stripping whitespace must be between 1 and 100, got {len(cleaned)}")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("name must not contain control characters")
    return cleaned


def format_iso_z(dt_val: datetime) -> str:
    if not isinstance(dt_val, datetime) or isinstance(dt_val, bool):
        raise TypeError(f"Expected datetime instance, got {type(dt_val).__name__}")
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=timezone.utc)
    else:
        dt_val = dt_val.astimezone(timezone.utc)
    return dt_val.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_trends_iso_z(dt_val: datetime) -> str:
    """Formats datetime as UTC ISO-8601 string preserving up to microsecond resolution with 'Z'."""
    if not isinstance(dt_val, datetime) or isinstance(dt_val, bool):
        raise TypeError(f"Expected datetime instance, got {type(dt_val).__name__}")
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=timezone.utc)
    else:
        dt_val = dt_val.astimezone(timezone.utc)
    if dt_val.microsecond % 1000 == 0:
        return dt_val.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return dt_val.isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_trends_range(start_ts: Any, end_ts: Any) -> tuple[datetime, datetime, str, str]:
    """Validates offset-aware ISO-8601 timestamps for trends query, ensuring a half-open
    [start_ts, end_ts) interval up to 366 days, real calendar dates, and returns UTC normalized bounds.
    Preserves microsecond precision and rejects precision exceeding 6 fractional digits.
    """
    if not isinstance(start_ts, str) or isinstance(start_ts, bool):
        raise ValueError(f"start_ts must be a string, got {type(start_ts).__name__}")
    if not isinstance(end_ts, str) or isinstance(end_ts, bool):
        raise ValueError(f"end_ts must be a string, got {type(end_ts).__name__}")
    if any(c in start_ts for c in ("\r", "\n", "\0")):
        raise ValueError("start_ts must not contain control characters")
    if any(c in end_ts for c in ("\r", "\n", "\0")):
        raise ValueError("end_ts must not contain control characters")

    # Reject precision exceeding 6 fractional digits with either '.' or ',' separator
    for name, ts_str in (("start_ts", start_ts), ("end_ts", end_ts)):
        sep = "." if "." in ts_str else ("," if "," in ts_str else None)
        if sep is not None:
            frac = ts_str.split(sep, 1)[1]
            digits = ""
            for ch in frac:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if len(digits) > 6:
                raise ValueError(f"{name} precision exceeds maximum supported 6 fractional digits (microseconds)")

    s_str = start_ts.strip()
    if s_str.endswith("Z") or s_str.endswith("z"):
        s_str = s_str[:-1] + "+00:00"
    try:
        start_dt = datetime.fromisoformat(s_str)
    except Exception as exc:
        raise ValueError(f"start_ts must be a valid ISO-8601 calendar date/time: {exc}") from exc

    e_str = end_ts.strip()
    if e_str.endswith("Z") or e_str.endswith("z"):
        e_str = e_str[:-1] + "+00:00"
    try:
        end_dt = datetime.fromisoformat(e_str)
    except Exception as exc:
        raise ValueError(f"end_ts must be a valid ISO-8601 calendar date/time: {exc}") from exc

    if start_dt.tzinfo is None:
        raise ValueError("start_ts must be an offset-aware timestamp")
    if end_dt.tzinfo is None:
        raise ValueError("end_ts must be an offset-aware timestamp")

    try:
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"Timestamp timezone conversion overflow: {exc}") from exc

    if start_utc >= end_utc:
        raise ValueError("start_ts must be strictly before end_ts")

    if end_utc - start_utc > timedelta(days=366):
        raise ValueError("Time range cannot exceed 366 days")

    start_iso = format_trends_iso_z(start_utc)
    end_iso = format_trends_iso_z(end_utc)
    return (start_utc, end_utc, start_iso, end_iso)


@dataclass(frozen=True)
class JournalRecord:
    seq: int
    kind: str
    payload: dict
    event_id: str | None


def create_postgres_connection(dsn: str) -> Any:
    """Creates a dedicated PostgreSQL connection with autocommit=True for explicit transaction control."""
    import psycopg
    return psycopg.connect(dsn, autocommit=True)


class PostgresStore:
    def __init__(self, conn: Any, schema: str | None = None) -> None:
        if getattr(conn, "autocommit", None) is not True:
            raise ValueError("PostgresStore requires an autocommit=True connection for explicit transaction boundaries")

        self._conn = conn
        self._schema = schema
        self._schema_prefix = f"{schema}." if schema else ""

    @classmethod
    def get_migration_sql(cls) -> str:
        mig1 = Path(__file__).parents[2] / "migrations" / "001_initial.sql"
        mig2 = Path(__file__).parents[2] / "migrations" / "002_integration.sql"
        mig3 = Path(__file__).parents[2] / "migrations" / "003_people.sql"
        sql1 = mig1.read_text(encoding="utf-8")
        sql2 = mig2.read_text(encoding="utf-8")
        sql3 = mig3.read_text(encoding="utf-8")
        return f"{sql1}\n{sql2}\n{sql3}"

    def check_or_init_version(self, current_version: str) -> None:
        """Preflight check: verifies stored matcher version matches current_version, or safely
        initializes empty database. Refuses nonempty unversioned state or version mismatch.
        Leaves preexisting schema and rows completely unchanged on refusal.
        On successful match with existing database, idempotently ensures latest migrations (003_people)
        are applied at startup without relabeling or changing version policy.
        """
        if not current_version or not isinstance(current_version, str):
            raise ValueError("Explicit non-empty matcher_version is required")

        table_prefix = f"{self._schema}." if self._schema else ""

        # Preflight inspection: check without executing any DDL
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT to_regclass(%s)",
                (f"{table_prefix}matcher_version",),
            )
            row = cur.fetchone()
            version_table_exists = row is not None and row[0] is not None

            if version_table_exists:
                cur.execute(f"SELECT version FROM {self._schema_prefix}matcher_version WHERE id = 1")
                v_row = cur.fetchone()
                if v_row is not None and v_row[0] is not None:
                    stored_v = v_row[0]
                    if stored_v == current_version:
                        # Existing same-version database acquires missing people table idempotently
                        cur.execute(
                            f"SELECT to_regclass(%s)",
                            (f"{table_prefix}people",),
                        )
                        p_row = cur.fetchone()
                        people_exists = p_row is not None and p_row[0] is not None
                        if not people_exists:
                            mig3 = Path(__file__).parents[2] / "migrations" / "003_people.sql"
                            sql3 = mig3.read_text(encoding="utf-8")
                            with self._conn.transaction():
                                with self._conn.cursor() as mig_cur:
                                    if self._schema:
                                        mig_cur.execute(f"SET search_path TO {self._schema};")
                                    mig_cur.execute(sql3)
                        return
                    else:
                        raise VersionMismatchError(
                            f"Stored matcher version mismatch: stored='{stored_v}', current='{current_version}'. "
                            f"Operator must reset development journal/state per handoff documentation."
                        )

            # Check legacy tables individually
            legacy_tables = ("matcher_journal", "fridge_events", "outbox")
            for tbl in legacy_tables:
                cur.execute(
                    f"SELECT to_regclass(%s)",
                    (f"{table_prefix}{tbl}",),
                )
                tbl_row = cur.fetchone()
                if tbl_row is not None and tbl_row[0] is not None:
                    cur.execute(f"SELECT 1 FROM {self._schema_prefix}{tbl} LIMIT 1")
                    if cur.fetchone() is not None:
                        raise VersionMismatchError(
                            f"Stored matcher version mismatch: stored=<unversioned>, current='{current_version}'. "
                            f"Found nonempty unversioned legacy state in table '{tbl}'. "
                            f"Operator must reset development journal/state per handoff documentation."
                        )

        # Empty or uninitialized DB: apply migrations and insert version atomically
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                if self._schema:
                    cur.execute(f"SET search_path TO {self._schema};")
                cur.execute(self.get_migration_sql())
                cur.execute(
                    f"INSERT INTO {self._schema_prefix}matcher_version (id, version) VALUES (1, %s)",
                    (current_version,),
                )

    def init_db(self) -> None:
        sql = self.get_migration_sql()
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                if self._schema:
                    cur.execute(f"SET search_path TO {self._schema};")
                cur.execute(sql)

    def close(self) -> None:
        """Closes the underlying database connection."""
        if hasattr(self._conn, "close"):
            self._conn.close()

    def handle_input(self, kind: str, event_dict: dict, matcher: Any) -> list[dict]:
        """Atomically journals the input, executes Matcher, validates output, and writes outbox.
        Deduplicates on event_id prior to invoking the Matcher.
        """
        event_id = event_dict.get("event_id")
        if event_id is not None:
            if not isinstance(event_id, str) or any(c in event_id for c in ("\r", "\n", "\0")):
                raise ValueError(f"Invalid or unsafe event_id with control characters: {event_id!r}")
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT EXISTS(SELECT 1 FROM {self._schema_prefix}matcher_journal WHERE event_id = %s)",
                    (event_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    # Redelivered input whose event_id is already journaled; skip without calling Matcher
                    return []

        with self._conn.transaction():
            with self._conn.cursor() as cur:
                payload_json = json.dumps(event_dict) if not isinstance(event_dict, str) else event_dict
                cur.execute(
                    f"INSERT INTO {self._schema_prefix}matcher_journal (kind, payload, event_id) VALUES (%s, %s, %s) RETURNING seq",
                    (kind, payload_json, event_id),
                )

            # Call Matcher inside transaction boundaries
            if kind == "person":
                outputs = matcher.on_person(event_dict)
            elif kind == "item":
                outputs = matcher.on_item(event_dict)
            else:
                raise ValueError(f"Unknown input kind: {kind}")

            for out_ev in outputs:
                VALIDATOR.validate(out_ev)
                self._insert_fridge_event(out_ev)
                self._insert_outbox(out_ev)

            return outputs

    def handle_tick(self, now_ts: str, matcher: Any) -> list[dict]:
        """Atomically journals an idle tick, calls Matcher.tick, validates output, and writes outbox."""
        tick_payload = {"now_ts": now_ts}
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._schema_prefix}matcher_journal (kind, payload, event_id) VALUES (%s, %s, %s) RETURNING seq",
                    ("tick", json.dumps(tick_payload), None),
                )

            outputs = matcher.tick(now_ts)

            for out_ev in outputs:
                VALIDATOR.validate(out_ev)
                self._insert_fridge_event(out_ev)
                self._insert_outbox(out_ev)

            return outputs

    def _insert_fridge_event(self, out_ev: dict) -> None:
        event_id = out_ev["event_id"]
        if not isinstance(event_id, str) or any(c in event_id for c in ("\r", "\n", "\0")):
            raise ValueError(f"Invalid or unsafe fridge event_id: {event_id!r}")
        payload_json = json.dumps(out_ev)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._schema_prefix}fridge_events (event_id, payload) VALUES (%s, %s)",
                (event_id, payload_json),
            )

    def _insert_outbox(self, out_ev: dict) -> None:
        event_id = out_ev["event_id"]
        if not isinstance(event_id, str) or any(c in event_id for c in ("\r", "\n", "\0")):
            raise ValueError(f"Invalid or unsafe outbox event_id: {event_id!r}")
        topic = out_ev.get("topic", "fridge.event")
        payload_json = json.dumps(out_ev)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._schema_prefix}outbox (event_id, topic, payload, status) VALUES (%s, %s, %s, %s) RETURNING id",
                (event_id, topic, payload_json, "pending"),
            )

    def replay_journal(self, matcher_factory: Callable[[], Any], expected_version: str) -> Any:
        """Reconstructs Matcher state by replaying all journal rows in seq order.
        Validates replay outputs, detects duplicate emissions, and cross-checks against stored fridge_events.
        Requires explicit expected_version and verifies version compatibility before calling matcher_factory.
        """
        if not expected_version or not isinstance(expected_version, str):
            raise ValueError("Explicit expected_version is required for replay_journal")

        self.check_or_init_version(expected_version)
        fresh_matcher = matcher_factory()

        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT event_id, payload FROM {self._schema_prefix}fridge_events"
            )
            stored_events_rows = cur.fetchall()
            stored_events: dict[str, dict] = {}
            for eid, payload in stored_events_rows:
                if isinstance(payload, str):
                    stored_events[eid] = json.loads(payload)
                else:
                    stored_events[eid] = payload

            cur.execute(
                f"SELECT seq, kind, payload, event_id FROM {self._schema_prefix}matcher_journal ORDER BY seq ASC"
            )
            journal_rows = cur.fetchall()

        seen_replayed_ids: set[str] = set()
        replayed_outputs: dict[str, dict] = {}

        for seq, kind, payload, event_id in journal_rows:
            payload_dict = json.loads(payload) if isinstance(payload, str) else payload

            if kind == "person":
                outs = fresh_matcher.on_person(payload_dict)
            elif kind == "item":
                outs = fresh_matcher.on_item(payload_dict)
            elif kind == "tick":
                outs = fresh_matcher.tick(payload_dict["now_ts"])
            else:
                raise ValueError(f"Unknown journal kind during replay: {kind}")

            for out_ev in outs:
                VALIDATOR.validate(out_ev)
                out_id = out_ev["event_id"]

                if out_id in seen_replayed_ids:
                    raise ReplayMismatchError(
                        f"Duplicate output {out_id} emitted during replay at seq {seq}"
                    )
                seen_replayed_ids.add(out_id)

                if out_id not in stored_events:
                    raise ReplayMismatchError(
                        f"Spurious extra output {out_id} during replay at seq {seq}"
                    )
                if out_ev != stored_events[out_id]:
                    raise ReplayMismatchError(
                        f"Payload mismatch for {out_id}: replayed {out_ev} != stored {stored_events[out_id]}"
                    )
                replayed_outputs[out_id] = out_ev

        if len(replayed_outputs) != len(stored_events):
            missing = set(stored_events.keys()) - set(replayed_outputs.keys())
            raise ReplayMismatchError(
                f"Missing expected output during replay: {missing}"
            )

        return fresh_matcher

    def relay_outbox(
        self,
        producer: Any,
        max_batch: int = 50,
        timeout: float = 1.0,
    ) -> int:
        """Relays pending outbox events to Kafka, self-driving producer flush, and transactionally
        marking them published only upon confirmed broker delivery.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT id, event_id, topic, payload FROM {self._schema_prefix}outbox WHERE status = 'pending' ORDER BY id ASC LIMIT %s",
                (max_batch,),
            )
            rows = cur.fetchall()

        published_count = 0
        for outbox_id, event_id, topic, payload in rows:
            payload_dict = json.loads(payload) if isinstance(payload, str) else payload
            payload_bytes = json.dumps(payload_dict)

            delivery_result = {"called": False, "delivered": False, "error": None}

            def on_delivery(err: Any, msg: Any) -> None:
                delivery_result["called"] = True
                delivery_result["delivered"] = (err is None)
                delivery_result["error"] = err

            producer.produce(
                topic=topic,
                key=event_id,
                value=payload_bytes,
                on_delivery=on_delivery,
            )

            # Self-drive broker confirmation via flush
            remaining = producer.flush(timeout=timeout)

            if not delivery_result["called"] or remaining > 0:
                raise RuntimeError(
                    f"Outbox delivery confirmation timed out for outbox row {outbox_id}"
                )

            if not delivery_result["delivered"]:
                logger.warning(
                    "Broker rejected message for outbox row %s: %s; stopping relay batch",
                    outbox_id,
                    delivery_result["error"],
                )
                break

            # Transactionally mark published
            try:
                with self._conn.transaction():
                    with self._conn.cursor() as update_cur:
                        update_cur.execute(
                            f"UPDATE {self._schema_prefix}outbox SET status = 'published', published_at = NOW() WHERE id = %s",
                            (outbox_id,),
                        )
                published_count += 1
            except Exception as db_exc:
                logger.error("Failed to mark outbox row %s published: %s", outbox_id, db_exc)
                raise

        return published_count

    def get_journal_records(self) -> list[JournalRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT seq, kind, payload, event_id FROM {self._schema_prefix}matcher_journal ORDER BY seq ASC"
            )
            rows = cur.fetchall()
            records = []
            for seq, kind, payload, event_id in rows:
                p_dict = json.loads(payload) if isinstance(payload, str) else payload
                records.append(JournalRecord(seq=seq, kind=kind, payload=p_dict, event_id=event_id))
            return records

    def get_stored_fridge_events(self) -> dict[str, dict]:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT event_id, payload FROM {self._schema_prefix}fridge_events")
            rows = cur.fetchall()
            return {
                eid: (json.loads(p) if isinstance(p, str) else p) for eid, p in rows
            }

    def get_pending_outbox(self) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT id, event_id, topic, payload FROM {self._schema_prefix}outbox WHERE status = 'pending' ORDER BY id ASC"
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "event_id": r[1],
                    "topic": r[2],
                    "payload": json.loads(r[3]) if isinstance(r[3], str) else r[3],
                }
                for r in rows
            ]

    def get_inventory(self) -> list[dict]:
        """Derives current inventory strictly via consistency.apply over all historical emitted events.
        Preserves original item_label and since_ts from accepted PUT across duplicate PUTs; clears metadata on TAKE.
        Returns bare list of {item_id, item_label, owner_id, since_ts}.
        """
        from fridge_backend import consistency

        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT f.payload FROM {self._schema_prefix}outbox o "
                f"JOIN {self._schema_prefix}fridge_events f ON o.event_id = f.event_id "
                f"ORDER BY o.id ASC"
            )
            rows = cur.fetchall()

        events = [(json.loads(p[0]) if isinstance(p[0], str) else p[0]) for p in rows]

        state: dict[str, str | None] = {}
        metadata: dict[str, tuple[str, str]] = {}

        for ev in events:
            ev_type = ev.get("type")
            item_id = ev.get("item_id")
            if not item_id:
                continue

            if ev_type == "PUT":
                if item_id not in state:
                    metadata[item_id] = (ev.get("item_label", ""), ev.get("ts", ""))
            elif ev_type == "TAKE":
                metadata.pop(item_id, None)

            state = consistency.apply(state, ev)

        result = []
        for item_id, owner_id in state.items():
            label, since_ts = metadata.get(item_id, ("", ""))
            result.append({
                "item_id": item_id,
                "item_label": label,
                "owner_id": owner_id,
                "since_ts": since_ts,
            })
        return result

    def get_events(self, limit: int = 50) -> list[dict]:
        """Returns bare list of canonical fridge.event payloads, newest emitted first."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT f.payload FROM {self._schema_prefix}outbox o "
                f"JOIN {self._schema_prefix}fridge_events f ON o.event_id = f.event_id "
                f"ORDER BY o.id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            return [(json.loads(p[0]) if isinstance(p[0], str) else p[0]) for p in rows]

    def get_alerts(self, limit: int = 50) -> list[dict]:
        """Returns bare list of canonical events with status wrong_owner OR uncertain, newest emitted first."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT f.payload FROM {self._schema_prefix}outbox o "
                f"JOIN {self._schema_prefix}fridge_events f ON o.event_id = f.event_id "
                f"WHERE f.payload->>'status' IN ('wrong_owner', 'uncertain') "
                f"ORDER BY o.id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            return [(json.loads(p[0]) if isinstance(p[0], str) else p[0]) for p in rows]

    def resolve_outbox_id(self, event_id: str) -> int | None:
        """Resolves an event_id UUID string to its durable integer outbox.id."""
        if not isinstance(event_id, str) or any(c in event_id for c in ("\r", "\n", "\0")):
            return None
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT id FROM {self._schema_prefix}outbox WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_stream_events(self, after_outbox_id: int, limit: int = 50) -> list[tuple[int, dict]]:
        """Queries strictly greater durable outbox items for SSE streaming."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT o.id, f.payload FROM {self._schema_prefix}outbox o "
                f"JOIN {self._schema_prefix}fridge_events f ON o.event_id = f.event_id "
                f"WHERE o.id > %s ORDER BY o.id ASC LIMIT %s",
                (after_outbox_id, limit),
            )
            rows = cur.fetchall()
            return [
                (r[0], json.loads(r[1]) if isinstance(r[1], str) else r[1])
                for r in rows
            ]

    def create_person(self, person_id: str, name: str) -> dict:
        """Atomically inserts a new person record with truthful unknown enrollment status.
        Validates identifiers and names strictly. Raises DuplicatePersonError on conflict.
        """
        pid = validate_person_id(person_id)
        pname = validate_name(name)
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._schema_prefix}people (person_id, name) VALUES (%s, %s) "
                    f"ON CONFLICT (person_id) DO NOTHING "
                    f"RETURNING person_id, name, created_at, updated_at",
                    (pid, pname),
                )
                row = cur.fetchone()
                if row is None:
                    raise DuplicatePersonError(f"Person with person_id '{pid}' already exists")
                return {
                    "person_id": row[0],
                    "name": row[1],
                    "enrollment_status": "unknown",
                    "created_at": format_iso_z(row[2]),
                    "updated_at": format_iso_z(row[3]),
                }

    def get_people(self) -> list[dict]:
        """Returns bare list of all people sorted deterministically by person_id ASC."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT person_id, name, created_at, updated_at "
                f"FROM {self._schema_prefix}people "
                f"ORDER BY person_id ASC"
            )
            rows = cur.fetchall()
            return [
                {
                    "person_id": r[0],
                    "name": r[1],
                    "enrollment_status": "unknown",
                    "created_at": format_iso_z(r[2]),
                    "updated_at": format_iso_z(r[3]),
                }
                for r in rows
            ]

    def get_person(self, person_id: str) -> dict | None:
        """Returns a single person record by person_id or None if not found."""
        pid = validate_person_id(person_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT person_id, name, created_at, updated_at "
                f"FROM {self._schema_prefix}people "
                f"WHERE person_id = %s",
                (pid,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "person_id": row[0],
                "name": row[1],
                "enrollment_status": "unknown",
                "created_at": format_iso_z(row[2]),
                "updated_at": format_iso_z(row[3]),
            }

    def update_person(self, person_id: str, name: str) -> dict | None:
        """Atomically updates a person's display name and updated_at timestamp.
        Does not allow modifying person_id or enrollment_status.
        """
        pid = validate_person_id(person_id)
        pname = validate_name(name)
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self._schema_prefix}people SET name = %s, updated_at = NOW() "
                    f"WHERE person_id = %s "
                    f"RETURNING person_id, name, created_at, updated_at",
                    (pname, pid),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "person_id": row[0],
                    "name": row[1],
                    "enrollment_status": "unknown",
                    "created_at": format_iso_z(row[2]),
                    "updated_at": format_iso_z(row[3]),
                }

    def get_trends(self, start_ts: str, end_ts: str, owner_id: str | None = None) -> dict:
        """Returns aggregate metrics and top-20 wrong_owner pair rankings for [start_ts, end_ts).
        Aggregates across all committed canonical fridge_events without artificial history limits.
        Read-only SQL aggregate; no database writes or version guard mutations.
        """
        _, _, start_iso, end_iso = validate_trends_range(start_ts, end_ts)
        valid_owner = validate_person_id(owner_id) if owner_id is not None else None

        sql = (
            f"SELECT "
            f"payload->>'type' AS type, "
            f"payload->>'status' AS status, "
            f"payload->>'person_id' AS person_id, "
            f"payload->>'owner_id' AS owner_id, "
            f"COUNT(*) AS cnt "
            f"FROM {self._schema_prefix}fridge_events "
            f"WHERE (payload->>'ts')::timestamptz >= %s::timestamptz AND (payload->>'ts')::timestamptz < %s::timestamptz "
        )
        params: list[Any] = [start_iso, end_iso]
        if valid_owner is not None:
            sql += "AND payload->>'owner_id' = %s "
            params.append(valid_owner)

        sql += "GROUP BY payload->>'type', payload->>'status', payload->>'person_id', payload->>'owner_id'"

        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

        event_count = 0
        put_count = 0
        take_count = 0
        wrong_owner_count = 0
        uncertain_count = 0
        pair_counts: dict[tuple[str, str], int] = {}

        for row in rows:
            ev_type, status, pid, oid, cnt = row
            cnt_int = int(cnt)
            event_count += cnt_int
            if ev_type == "PUT":
                put_count += cnt_int
            elif ev_type == "TAKE":
                take_count += cnt_int

            if status == "wrong_owner":
                wrong_owner_count += cnt_int
            elif status == "uncertain":
                uncertain_count += cnt_int

            if (
                ev_type == "TAKE"
                and status == "wrong_owner"
                and pid is not None
                and oid is not None
                and pid != oid
                and pid != ""
                and oid != ""
            ):
                pair_key = (str(pid), str(oid))
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + cnt_int

        sorted_pairs = sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
        rankings_truncated = len(sorted_pairs) > 20
        wrong_owner_by_pair = [
            {"person_id": p, "owner_id": o, "count": c}
            for (p, o), c in sorted_pairs[:20]
        ]

        return {
            "start_ts": start_iso,
            "end_ts": end_iso,
            "owner_id": valid_owner,
            "event_count": event_count,
            "put_count": put_count,
            "take_count": take_count,
            "wrong_owner_count": wrong_owner_count,
            "uncertain_count": uncertain_count,
            "wrong_owner_by_pair": wrong_owner_by_pair,
            "rankings_truncated": rankings_truncated,
        }
