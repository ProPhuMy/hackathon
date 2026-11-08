"""Read-only Model Context Protocol (FastMCP) STDIO server for Fridge Tracker.

Exposes exactly four read-only tools:
- get_inventory()
- get_history(limit=50)
- get_alerts(limit=50)
- get_trends(start_ts, end_ts, owner_id=None)

Enforces strict field sanitization (zero biometrics/face images/embeddings),
input validation before network dispatch, and an in-process 10-token bucket rate limiter.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from time import monotonic
from typing import Annotated, Any, Literal
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, StrictInt, TypeAdapter, ValidationError

from fridge_backend.store import validate_person_id, validate_trends_range

logger = logging.getLogger(__name__)


def validate_backend_url(url: str) -> str:
    """Validates that backend URL is a valid HTTP or HTTPS base URL without credentials, paths, or query strings.
    Preserves IPv6 brackets and port in netloc.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Backend URL must be a non-empty string")
    cleaned = url.strip()

    # Pre-check for credentials in authority component to avoid leaking credentials in errors
    if "://" in cleaned:
        scheme_part, rest = cleaned.split("://", 1)
        authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        if "@" in authority:
            raise ValueError("Backend URL must not contain user credentials")

    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except Exception as exc:
        raise ValueError(f"Invalid backend URL: {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Backend URL scheme must be http or https")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Backend URL must specify a valid host")
    if parsed.username or parsed.password:
        raise ValueError("Backend URL must not contain user credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Backend URL must not contain query parameters or fragments")
    if parsed.path and parsed.path != "/":
        raise ValueError("Backend URL must not contain a path component")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Backend URL has an invalid port number") from exc

    if port is not None and not (1 <= port <= 65535):
        raise ValueError("Port must be between 1 and 65535")

    # Retain exact validated netloc (preserves IPv6 brackets [::1] and port)
    return f"{parsed.scheme}://{parsed.netloc}"


class TokenBucket:
    """Process-global rate limiter: capacity 10 tokens, refills at 2 tokens/second.
    Rejects immediately without sleeping when tokens are exhausted.
    """

    def __init__(self) -> None:
        self.capacity: float = 10.0
        self.refill_rate: float = 2.0
        self.tokens: float = 10.0
        self.last_refill: float = monotonic()

    def acquire(self) -> bool:
        now = monotonic()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class InventoryItem(BaseModel):
    model_config = {"extra": "ignore", "strict": True}
    item_id: str
    item_label: str
    owner_id: str | None
    since_ts: str


class CanonicalEvent(BaseModel):
    model_config = {"extra": "ignore", "strict": True}
    event_id: str
    topic: Literal["fridge.event"]
    type: Literal["PUT", "TAKE"]
    item_id: str
    item_label: str
    person_id: str | None
    owner_id: str | None
    ts: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["ok", "wrong_owner", "uncertain"]


class WrongOwnerPair(BaseModel):
    model_config = {"extra": "ignore", "strict": True}
    person_id: str
    owner_id: str
    count: int = Field(ge=0)


class TrendsResponse(BaseModel):
    model_config = {"extra": "ignore", "strict": True}
    start_ts: str
    end_ts: str
    owner_id: str | None
    event_count: int = Field(ge=0)
    put_count: int = Field(ge=0)
    take_count: int = Field(ge=0)
    wrong_owner_count: int = Field(ge=0)
    uncertain_count: int = Field(ge=0)
    wrong_owner_by_pair: list[WrongOwnerPair]
    rankings_truncated: bool


def create_server(backend_url: str) -> FastMCP:
    """Creates a configured FastMCP server bound to the specified backend URL."""
    base_url = validate_backend_url(backend_url)
    bucket = TokenBucket()

    server = FastMCP(
        "fridge-tracker",
        instructions="Read-only access to Fridge Tracker inventory, history, alerts, and trends without biometrics.",
    )

    async def _fetch(path: str, params: dict[str, Any] | None = None) -> Any:
        if not bucket.acquire():
            raise RuntimeError("Rate limit exceeded: 10-token bucket empty (refill rate 2 tokens/sec).")

        target_url = f"{base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, trust_env=False) as client:
                resp = await client.get(target_url, params=params)
        except httpx.TimeoutException:
            raise RuntimeError("Backend request timed out after 5.0 seconds") from None
        except httpx.RequestError:
            raise RuntimeError("Failed to connect to backend service") from None

        if resp.status_code != 200:
            raise RuntimeError(f"Backend returned HTTP {resp.status_code}")

        try:
            return resp.json()
        except Exception:
            raise RuntimeError("Backend returned invalid JSON response") from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_inventory() -> list[dict[str, Any]]:
        """Read-only query of current fridge inventory. Returns items currently inside the fridge with labels, owners (nullable), and since_ts. Does not return face images or embeddings."""
        raw = await _fetch("/inventory")
        try:
            items = TypeAdapter(list[InventoryItem]).validate_python(raw)
            return [it.model_dump() for it in items]
        except ValidationError:
            raise RuntimeError("Backend returned unexpected inventory structure") from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_history(
        limit: Annotated[StrictInt, Field(default=50, ge=1, le=500)] = 50,
    ) -> list[dict[str, Any]]:
        """Read-only query of canonical event history (PUT and TAKE events), newest emitted first. 'limit' must be an integer between 1 and 500. Preserves actor/owner identities (nullable), confidence, and status ('ok', 'wrong_owner', 'uncertain'). Does not return face images or embeddings."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 500):
            raise ValueError(f"limit must be a strict integer between 1 and 500, got {limit!r}")
        raw = await _fetch("/events", params={"limit": limit})
        try:
            events = TypeAdapter(list[CanonicalEvent]).validate_python(raw)
            return [ev.model_dump() for ev in events]
        except ValidationError:
            raise RuntimeError("Backend returned unexpected events structure") from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_alerts(
        limit: Annotated[StrictInt, Field(default=50, ge=1, le=500)] = 50,
    ) -> list[dict[str, Any]]:
        """Read-only query of alert events (status 'wrong_owner' or 'uncertain'), newest emitted first. 'limit' must be an integer between 1 and 500. Preserves distinct alert semantics: wrong_owner indicates an item taken by someone other than the recorded owner; uncertain indicates identity or ownership uncertainty. Does not return face images or embeddings."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 500):
            raise ValueError(f"limit must be a strict integer between 1 and 500, got {limit!r}")
        raw = await _fetch("/alerts", params={"limit": limit})
        try:
            events = TypeAdapter(list[CanonicalEvent]).validate_python(raw)
            return [ev.model_dump() for ev in events]
        except ValidationError:
            raise RuntimeError("Backend returned unexpected alerts structure") from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_trends(start_ts: str, end_ts: str, owner_id: str | None = None) -> dict[str, Any]:
        """Read-only query of event trends over a half-open time range [start_ts, end_ts) up to 366 days, with optional owner_id filter. Both timestamps must be offset-aware ISO-8601 strings. Returns counts and top 20 wrong-owner pairs. Uncertain events are never accused."""
        _, _, start_iso, end_iso = validate_trends_range(start_ts, end_ts)
        valid_owner = validate_person_id(owner_id) if owner_id is not None else None

        params: dict[str, Any] = {"start_ts": start_iso, "end_ts": end_iso}
        if valid_owner is not None:
            params["owner_id"] = valid_owner

        raw = await _fetch("/trends", params=params)
        try:
            trends = TrendsResponse.model_validate(raw)
            return trends.model_dump()
        except ValidationError:
            raise RuntimeError("Backend returned unexpected trends structure") from None

    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fridge Tracker read-only FastMCP STDIO server"
    )
    parser.add_argument(
        "--backend-url",
        default=os.environ.get("MCP_BACKEND_URL", "http://127.0.0.1:8000"),
        help="Base URL of running fridge-backend service (default: MCP_BACKEND_URL or http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    server = create_server(args.backend_url)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
