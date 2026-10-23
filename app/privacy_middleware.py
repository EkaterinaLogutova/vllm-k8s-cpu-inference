"""ASGI middleware that authenticates and logs without touching payloads.

The middleware intentionally never reads ``receive`` and never stores response
messages. Therefore prompt text, token ids and generated text cannot be emitted
by this code, even when an exception occurs.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Awaitable, Callable

ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]

LOGGER = logging.getLogger("privacy_access")
PUBLIC_PATHS = frozenset({"/health", "/metrics", "/version"})


def _configure_logger() -> None:
    """Attach a deterministic stderr handler inside the vLLM process."""
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


def _headers(scope: dict[str, Any]) -> dict[bytes, bytes]:
    return {key.lower(): value for key, value in scope.get("headers", [])}


def _bearer_token(headers: dict[bytes, bytes]) -> str:
    raw = headers.get(b"authorization", b"").decode("latin-1")
    scheme, separator, value = raw.partition(" ")
    if separator and scheme.lower() == "bearer":
        return value.strip()
    return headers.get(b"x-api-key", b"").decode("latin-1").strip()


class PrivacyAndAuthMiddleware:
    """Require a bearer token and emit one metadata-only JSON event."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        _configure_logger()
        self.api_token = os.environ.get("API_TOKEN", "")
        if not self.api_token:
            raise RuntimeError("API_TOKEN is required")

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        headers = _headers(scope)
        request_id = headers.get(b"x-request-id", b"").decode("latin-1") or str(uuid.uuid4())
        path = scope.get("path", "")
        method = scope.get("method", "")
        status_code = 500

        if path not in PUBLIC_PATHS and not hmac.compare_digest(
            _bearer_token(headers), self.api_token
        ):
            status_code = 401
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"error":"unauthorized"}',
                }
            )
        else:

            async def capture_status(message: dict[str, Any]) -> None:
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = int(message.get("status", 500))
                await send(message)

            await self.app(scope, receive, capture_status)

        event = {
            "event": "inference_http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if path not in PUBLIC_PATHS:
            LOGGER.info(json.dumps(event, separators=(",", ":"), ensure_ascii=True))

