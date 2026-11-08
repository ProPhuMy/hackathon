"""Main backend controller, Kafka event loop, idle tick generator, and recovery coordinator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import sys
import threading
import time
from typing import Any, Callable

from fridge_backend.config import BackendConfig, load_config
from fridge_backend.store import PostgresStore, create_postgres_connection
from fridge_backend.bus import EventBus, create_kafka_consumer, create_kafka_producer
from fridge_backend.matcher import Matcher, MATCHER_VERSION

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Format current UTC time as ISO 8601 string ending in Z with milliseconds."""
    dt = datetime.now(timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EngineController:
    def __init__(
        self,
        config: BackendConfig,
        store: PostgresStore,
        consumer: Any,
        producer: Any,
        matcher_factory: Callable[[], Any] | None,
        matcher_version: str | None = None,
        now_ts_fn: Callable[[], str] | None = None,
        clock_fn: Callable[[], float] | None = None,
    ) -> None:
        if matcher_factory is None:
            raise ValueError("Matcher factory is required")
        if not matcher_version or not isinstance(matcher_version, str):
            raise ValueError("Explicit non-empty matcher_version is required")

        self.config = config
        self.store = store
        self.consumer = consumer
        self.producer = producer
        self.matcher_factory = matcher_factory
        self.matcher_version = matcher_version
        self.now_ts_fn = now_ts_fn or utc_now_iso
        self.clock_fn = clock_fn or time.monotonic

        self.is_running = True
        self._is_closed = False
        self.worker_failed = False
        self.worker_error: Exception | None = None
        self._last_tick_mono = self.clock_fn()
        self._last_outbox_mono = 0.0

        # Preflight version guard must precede Matcher reconstruction and bus consumption
        logger.info("Initializing engine: checking matcher version preflight...")
        self.store.check_or_init_version(self.matcher_version)

        # Reconstruct Matcher deterministically from journal
        logger.info("Replaying matcher journal from Postgres...")
        self.matcher = self.store.replay_journal(
            self.matcher_factory, expected_version=self.matcher_version
        )

        self.bus = EventBus(
            consumer=self.consumer,
            store=self.store,
            matcher=self.matcher,
            person_topic=self.config.person_topic,
            item_topic=self.config.item_topic,
        )

    def recover_from_failure(self) -> None:
        """Discards mutated in-memory Matcher and rebuilds state via Postgres call journal replay."""
        logger.warning("Transaction or loop failure detected: rebuilding Matcher from journal...")
        self.matcher = self.store.replay_journal(
            self.matcher_factory, expected_version=self.matcher_version
        )
        self.bus.set_matcher(self.matcher)
        logger.info("Matcher recovery replay complete.")

    def step(self, poll_timeout: float = 0.1) -> None:
        """Executes a single controller step: input processing, tick evaluation, outbox dispatch."""
        # 1. Process Kafka input message
        try:
            self.bus.poll_and_process(timeout=poll_timeout)
        except Exception as exc:
            logger.error("Error processing input message: %s", exc)
            self.recover_from_failure()
            raise

        # 2. Check and emit idle tick if due
        now_mono = self.clock_fn()
        tick_interval_sec = self.config.tick_interval_ms / 1000.0
        if now_mono - self._last_tick_mono >= tick_interval_sec:
            now_ts = self.now_ts_fn()
            try:
                self.store.handle_tick(now_ts, self.matcher)
                self._last_tick_mono = now_mono
            except Exception as exc:
                logger.error("Error processing tick: %s", exc)
                self.recover_from_failure()
                raise

        # 3. Relay pending outbox records to Kafka
        outbox_interval_sec = self.config.outbox_poll_interval_ms / 1000.0
        if now_mono - self._last_outbox_mono >= outbox_interval_sec:
            try:
                self.store.relay_outbox(
                    self.producer,
                    timeout=1.0,
                )
                self._last_outbox_mono = now_mono
            except Exception as exc:
                logger.error("Error relaying outbox: %s", exc)
                self.recover_from_failure()
                raise

    def request_stop(self) -> None:
        """Signals the main loop to terminate without immediately closing underlying resources."""
        self.is_running = False

    def run(self) -> None:
        """Main execution loop until stopped. Fails closed and closes resources on error."""
        logger.info("Engine controller loop started.")
        try:
            while self.is_running:
                self.step(poll_timeout=0.1)
        except Exception as exc:
            self.worker_failed = True
            self.worker_error = exc
            logger.error("Fatal error in EngineController worker loop: %s", exc)
            raise
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully stop controller and attempt cleanup of all resources once."""
        self.is_running = False
        if self._is_closed:
            return
        self._is_closed = True
        logger.info("Stopping EngineController and cleaning up resources...")
        cleanup_errors: list[Exception] = []

        try:
            self.bus.close()
        except Exception as exc:
            logger.error("Error closing bus during shutdown: %s", exc)
            cleanup_errors.append(exc)

        try:
            if hasattr(self.producer, "flush"):
                self.producer.flush(timeout=2.0)
        except Exception as exc:
            logger.error("Error flushing producer during shutdown: %s", exc)
            cleanup_errors.append(exc)

        try:
            self.store.close()
        except Exception as exc:
            logger.error("Error closing store during shutdown: %s", exc)
            cleanup_errors.append(exc)

        if cleanup_errors:
            logger.warning("Encountered %d errors during shutdown cleanup", len(cleanup_errors))


def run_service(config: BackendConfig, server_override: Any = None) -> int:
    """Main production service runner: initializes read store, starts serial matcher worker,
    and runs uvicorn HTTP server with failure propagation.
    """
    from fridge_backend.api import create_app
    import uvicorn

    read_conn = None
    read_store = None
    worker_conn = None
    worker_store = None
    consumer = None
    producer = None
    controller = None
    worker_started = False

    try:
        # 1. Reader store (separate autocommit connection)
        read_conn = create_postgres_connection(config.postgres_dsn)
        read_store = PostgresStore(read_conn)

        # Preflight check on read store
        read_store.check_or_init_version(MATCHER_VERSION)

        # 2. Worker allocations guarded against startup/construction failures
        worker_conn = create_postgres_connection(config.postgres_dsn)
        worker_store = PostgresStore(worker_conn)
        consumer = create_kafka_consumer(config)
        producer = create_kafka_producer(config)
        controller = EngineController(
            config=config,
            store=worker_store,
            consumer=consumer,
            producer=producer,
            matcher_factory=lambda: Matcher(),
            matcher_version=MATCHER_VERSION,
        )

        app = create_app(config, read_store, worker_controller=controller)

        uv_cfg = uvicorn.Config(
            app=app,
            host=config.api_host,
            port=config.api_port,
            log_level="info",
        )
        server = server_override or uvicorn.Server(uv_cfg)

        def worker_target():
            try:
                controller.run()
            except BaseException as exc:
                controller.worker_failed = True
                controller.worker_error = exc
                if hasattr(app, "state"):
                    app.state.worker_failed = True
                server.should_exit = True
                logger.error("Worker thread failed fatally: %s", exc)

        worker_thread = threading.Thread(target=worker_target, name="MatcherWorker", daemon=False)
        worker_thread.start()
        worker_started = True

        try:
            server.run()
        finally:
            controller.request_stop()
            worker_thread.join()

        return 1 if controller.worker_failed else 0

    finally:
        if not worker_started:
            if controller is not None:
                controller.stop()
            else:
                if consumer is not None:
                    try:
                        consumer.close()
                    except Exception:
                        pass
                if producer is not None:
                    try:
                        if hasattr(producer, "flush"):
                            producer.flush(2.0)
                    except Exception:
                        pass
                if worker_store is not None:
                    try:
                        worker_store.close()
                    except Exception:
                        pass
                elif worker_conn is not None:
                    try:
                        worker_conn.close()
                    except Exception:
                        pass

        if read_store is not None:
            try:
                read_store.close()
            except Exception:
                pass
        elif read_conn is not None:
            try:
                read_conn.close()
            except Exception:
                pass


def main_entry(argv: list[str] | None = None) -> None:
    """CLI entry point for fridge-backend service."""
    parser = argparse.ArgumentParser(
        prog="fridge-backend",
        description="Fridge Tracker Backend Service (Role 3 Codex)",
    )
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Starting fridge-backend (Role 3 Codex Stage 2)...")

    config = load_config()
    exit_code = run_service(config)
    sys.exit(exit_code)
