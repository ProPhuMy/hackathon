"""FastAPI serving endpoints for committed events, alerts, inventory, and SSE stream."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Callable

import anyio
from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from fridge_backend.config import BackendConfig
from fridge_backend.store import (
    PostgresStore,
    DuplicatePersonError,
    validate_person_id,
    validate_name,
)

logger = logging.getLogger(__name__)


class PersonCreate(BaseModel):
    person_id: str
    name: str
    model_config = {"extra": "forbid"}

    @field_validator("person_id")
    @classmethod
    def check_person_id(cls, v: Any) -> str:
        return validate_person_id(v)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Any) -> str:
        return validate_name(v)


class PersonUpdate(BaseModel):
    name: str
    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Any) -> str:
        return validate_name(v)


def _validate_path_person_id(person_id: str) -> str:
    try:
        return validate_person_id(person_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def create_app(
    config: BackendConfig,
    read_store: PostgresStore,
    worker_controller: Any = None,
    clock_fn: Callable[[], float] | None = None,
) -> FastAPI:
    """Creates the FastAPI application with dedicated read store and worker controller."""
    # Serialize read connection usage across threads to prevent concurrent psycopg cursor overlap
    read_lock = asyncio.Lock()
    clock = clock_fn or time.monotonic

    async def safe_read(func, *args, **kwargs):
        async with read_lock:
            task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    await task
                raise

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.worker_controller = worker_controller
        app.state.worker_failed = getattr(worker_controller, "worker_failed", False)
        app.state.worker_error = None
        yield

    app = FastAPI(
        title="Fridge Tracker API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.read_store = read_store
    app.state.read_lock = read_lock
    app.state.safe_read = safe_read
    app.state.clock_fn = clock
    app.state.worker_controller = worker_controller
    app.state.worker_failed = getattr(worker_controller, "worker_failed", False)
    app.state.worker_error = None

    @app.middleware("http")
    async def check_worker_health(request: Request, call_next):
        worker_ctrl = getattr(app.state, "worker_controller", None)
        is_failed = getattr(app.state, "worker_failed", False) or (
            worker_ctrl is not None and getattr(worker_ctrl, "worker_failed", False)
        )
        if is_failed:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Matcher worker encountered a fatal error; service unavailable."},
            )
        return await call_next(request)

    @app.get("/events", response_class=JSONResponse)
    async def get_events(
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict]:
        """Bare list of canonical fridge.event payloads, newest emitted first."""
        return await safe_read(read_store.get_events, limit)

    @app.get("/alerts", response_class=JSONResponse)
    async def get_alerts(
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict]:
        """Bare list of canonical events with status wrong_owner OR uncertain, newest emitted first."""
        return await safe_read(read_store.get_alerts, limit)

    @app.get("/inventory", response_class=JSONResponse)
    async def get_inventory() -> list[dict]:
        """Bare list of {item_id, item_label, owner_id, since_ts} projected over all history."""
        return await safe_read(read_store.get_inventory)

    @app.get("/people", response_class=JSONResponse)
    async def get_people() -> list[dict]:
        """Bare list of people roster records, sorted deterministically by person_id ASC."""
        return await safe_read(read_store.get_people)

    @app.post("/people", response_class=JSONResponse, status_code=status.HTTP_201_CREATED)
    async def create_person(payload: PersonCreate) -> dict:
        """Creates a new person metadata record with truthful unknown enrollment status."""
        try:
            return await safe_read(read_store.create_person, payload.person_id, payload.name)
        except DuplicatePersonError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    @app.get("/people/{person_id}", response_class=JSONResponse)
    async def get_person(person_id: str) -> dict:
        """Returns a single person metadata record by person_id or 404."""
        valid_id = _validate_path_person_id(person_id)
        person = await safe_read(read_store.get_person, valid_id)
        if person is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Person '{person_id}' not found")
        return person

    @app.put("/people/{person_id}", response_class=JSONResponse)
    async def update_person(person_id: str, payload: PersonUpdate) -> dict:
        """Updates display name for a person metadata record or 404."""
        valid_id = _validate_path_person_id(person_id)
        person = await safe_read(read_store.update_person, valid_id, payload.name)
        if person is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Person '{person_id}' not found")
        return person

    @app.get("/stream")
    async def sse_stream(
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        """Server-Sent Events stream of committed fridge.events.
        Resolves Last-Event-ID UUID string to internal outbox.id and streams strictly greater items.
        """
        if last_event_id is not None:
            if any(c in last_event_id for c in ("\r", "\n", "\0")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Last-Event-ID header",
                )
            resolved_id = await safe_read(read_store.resolve_outbox_id, last_event_id)
            if resolved_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unknown or invalid Last-Event-ID",
                )
            start_after_id = resolved_id
        else:
            start_after_id = 0

        async def event_generator() -> AsyncGenerator[str, None]:
            current_after_id = start_after_id
            clock = getattr(app.state, "clock_fn", time.monotonic)
            last_ping_time = clock()
            try:
                while True:
                    if await request.is_disconnected():
                        break

                    events = await safe_read(
                        read_store.get_stream_events, current_after_id, 50
                    )

                    now = clock()
                    if events:
                        for outbox_id, ev in events:
                            current_after_id = max(current_after_id, outbox_id)
                            eid = str(ev.get("event_id", ""))
                            if any(c in eid for c in ("\r", "\n", "\0")):
                                logger.error("Corrupted event_id with control characters detected: %r", eid)
                                return
                            payload_json = json.dumps(ev, ensure_ascii=False)
                            yield f"id: {eid}\nevent: fridge.event\ndata: {payload_json}\n\n"
                        last_ping_time = now
                    else:
                        if now - last_ping_time >= 15.0:
                            yield ": ping\n\n"
                            last_ping_time = now
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app
