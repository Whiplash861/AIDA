from __future__ import annotations
import asyncio
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from fastapi import HTTPException
from starlette.responses import JSONResponse

class RequestLimits:
    def __init__(self, *, concurrency: int = 8, per_minute: int = 60):
        self._slots = threading.BoundedSemaphore(concurrency)
        self._lock = threading.Lock()
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self.per_minute = per_minute

    @contextmanager
    def acquire(self, identity: str):
        now = time.monotonic()
        with self._lock:
            history = self._requests.setdefault(identity, deque())
            self._requests.move_to_end(identity)
            while history and now - history[0] >= 60:
                history.popleft()
            if len(history) >= self.per_minute:
                raise HTTPException(429, "Gateway request limit reached.", headers={"Retry-After": "60"})
            history.append(now)
            while len(self._requests) > 2048:
                self._requests.popitem(last=False)
        if not self._slots.acquire(blocking=False):
            raise HTTPException(503, "Gateway is busy. Please retry shortly.", headers={"Retry-After": "2"})
        try:
            yield
        finally:
            self._slots.release()

class BodyLimitMiddleware:
    """Bound the body before JSON parsing, including chunked requests."""
    def __init__(self, app, *, concurrency: int = 8):
        self.app = app
        self._ingress = threading.BoundedSemaphore(concurrency)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not self._ingress.acquire(blocking=False):
            return await JSONResponse({"detail": "Gateway upload capacity is busy."}, 503)(scope, receive, send)
        try:
            return await self._bounded_request(scope, receive, send)
        finally:
            self._ingress.release()

    async def _bounded_request(self, scope, receive, send):
        limit = 16_800_000 if scope.get("path") == "/v1/transcription" else 65_536
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length."}, 400)(scope, receive, send)
        if length > limit or length < 0:
            return await JSONResponse({"detail": "Request exceeds the gateway size limit."}, 413)(scope, receive, send)
        chunks, total = [], 0
        deadline = time.monotonic() + 30
        while True:
            try:
                event = await asyncio.wait_for(receive(), timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                return await JSONResponse({"detail": "Request upload timed out."}, 408)(scope, receive, send)
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            total += len(chunk)
            if total > limit:
                return await JSONResponse({"detail": "Request exceeds the gateway size limit."}, 413)(scope, receive, send)
            chunks.append(chunk)
            if not event.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)
