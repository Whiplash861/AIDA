
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    action_id: str
    summary: str
    scope: dict[str, Any]
    requested_by: str
    required_phrase: str
    expires_at: datetime
    risk: str
    confirmation_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: ConfirmationStatus = ConfirmationStatus.PENDING

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_id cannot be empty")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if not self.required_phrase.strip():
            raise ValueError("required_phrase cannot be empty")


class ConfirmationService:
    """In-process, single-use confirmation tokens bound to exact action scope."""

    def __init__(self) -> None:
        self._requests: dict[str, ConfirmationRequest] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        action_id: str,
        summary: str,
        scope: dict[str, Any],
        requested_by: str,
        required_phrase: str,
        risk: str,
        ttl_seconds: int = 120,
    ) -> ConfirmationRequest:
        now = datetime.now(timezone.utc)
        request = ConfirmationRequest(
            action_id=action_id,
            summary=summary,
            scope=dict(scope),
            requested_by=requested_by,
            required_phrase=required_phrase,
            expires_at=now + timedelta(seconds=max(15, ttl_seconds)),
            risk=risk,
        )
        with self._lock:
            self._expire_locked(now)
            # A newer request for the same action supersedes an older pending
            # token so the user can never be trapped by two valid prompts.
            for confirmation_id, existing in tuple(self._requests.items()):
                if (
                    existing.action_id == action_id
                    and existing.status is ConfirmationStatus.PENDING
                ):
                    self._requests[confirmation_id] = _replace_status(
                        existing,
                        ConfirmationStatus.REJECTED,
                    )
            self._requests[request.confirmation_id] = request
        return request

    def pending_for_action(self, action_id: str) -> ConfirmationRequest | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._expire_locked(now)
            pending = [
                request
                for request in self._requests.values()
                if request.action_id == action_id
                and request.status is ConfirmationStatus.PENDING
            ]
        if len(pending) != 1:
            return None
        return pending[0]

    def confirm(
        self,
        *,
        action_id: str,
        phrase: str,
    ) -> ConfirmationRequest:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._expire_locked(now)
            request = self.pending_for_action(action_id)
            if request is None:
                raise RuntimeError(
                    "No unique pending confirmation exists for this action."
                )
            if _normalize(phrase) != _normalize(request.required_phrase):
                raise RuntimeError("The confirmation phrase did not match.")
            confirmed = _replace_status(
                request,
                ConfirmationStatus.CONFIRMED,
            )
            self._requests[request.confirmation_id] = confirmed
            return confirmed

    def consume(
        self,
        confirmation_id: str,
        *,
        action_id: str,
        expected_scope: dict[str, Any] | None = None,
    ) -> ConfirmationRequest:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._expire_locked(now)
            request = self._requests.get(confirmation_id)
            if request is None:
                raise RuntimeError("Unknown confirmation.")
            if request.status is not ConfirmationStatus.CONFIRMED:
                raise RuntimeError("Confirmation is not valid for execution.")
            if request.action_id != action_id:
                raise RuntimeError("Confirmation belongs to a different action.")
            if expected_scope is not None and request.scope != expected_scope:
                raise RuntimeError("Confirmation scope no longer matches.")
            consumed = _replace_status(
                request,
                ConfirmationStatus.CONSUMED,
            )
            self._requests[confirmation_id] = consumed
            return consumed

    def reject(self, confirmation_id: str) -> ConfirmationRequest:
        with self._lock:
            request = self._requests.get(confirmation_id)
            if request is None:
                raise RuntimeError("Unknown confirmation.")
            rejected = _replace_status(
                request,
                ConfirmationStatus.REJECTED,
            )
            self._requests[confirmation_id] = rejected
            return rejected

    def invalidate_all(self) -> None:
        with self._lock:
            for confirmation_id, request in tuple(self._requests.items()):
                if request.status is ConfirmationStatus.PENDING:
                    self._requests[confirmation_id] = _replace_status(
                        request,
                        ConfirmationStatus.EXPIRED,
                    )

    def _expire_locked(self, now: datetime) -> None:
        for confirmation_id, request in tuple(self._requests.items()):
            if (
                request.status is ConfirmationStatus.PENDING
                and request.expires_at <= now
            ):
                self._requests[confirmation_id] = _replace_status(
                    request,
                    ConfirmationStatus.EXPIRED,
                )


def _replace_status(
    request: ConfirmationRequest,
    status: ConfirmationStatus,
) -> ConfirmationRequest:
    return ConfirmationRequest(
        confirmation_id=request.confirmation_id,
        action_id=request.action_id,
        summary=request.summary,
        scope=request.scope,
        requested_by=request.requested_by,
        required_phrase=request.required_phrase,
        expires_at=request.expires_at,
        risk=request.risk,
        created_at=request.created_at,
        status=status,
    )


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())
