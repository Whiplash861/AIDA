from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event
from aida.config import AidaConfig, get_config
from aida.logging_utils import get_logger
from aida.brain.system_prompt import AIDA_SYSTEM_PROMPT

log = get_logger(__name__)


class AIDABrain:
    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        config: AidaConfig | None = None,
    ) -> None:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is not set")
        if not deployment:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set")
        self.deployment = deployment
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
        self.event_bus = event_bus
        self.config = config or get_config()

    def think(self, user_input: str, context: Optional[List[str]] = None) -> str:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": AIDA_SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": "Context:\n" + "\n".join(context)})
        messages.append({"role": "user", "content": user_input})
        operation_id = str(uuid.uuid4())
        started = time.monotonic()
        self._publish(
            "brain_request",
            "started",
            operation_id=operation_id,
            metadata={"deployment": self.deployment, "context_messages": len(context or [])},
        )
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                resp = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.2,
                    max_completion_tokens=500,
                )
                content = (resp.choices[0].message.content or "").strip()
                if not content:
                    raise RuntimeError("Empty response from AIDA brain")
                usage = getattr(resp, "usage", None)
                duration_ms = (time.monotonic() - started) * 1000.0
                metadata: dict[str, Any] = {
                    "deployment": self.deployment,
                    "attempts": attempt,
                    "response_characters": len(content),
                }
                if usage is not None:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = getattr(usage, key, None)
                        if value is not None:
                            metadata[key] = int(value)
                self._publish(
                    "brain_request",
                    "completed",
                    operation_id=operation_id,
                    duration_ms=duration_ms,
                    metadata=metadata,
                )
                return content
            except Exception as exc:
                last_exc = exc
                log.warning("AIDA brain attempt %d failed: %s", attempt, exc)
                self._publish(
                    "brain_attempt",
                    "failed",
                    operation_id=operation_id,
                    error_category=type(exc).__name__,
                    metadata={"attempt": attempt, "error": str(exc), "deployment": self.deployment},
                )
                time.sleep(0.8 * attempt)
        duration_ms = (time.monotonic() - started) * 1000.0
        self._publish(
            "brain_request",
            "failed",
            operation_id=operation_id,
            duration_ms=duration_ms,
            error_category=type(last_exc).__name__ if last_exc else "UnknownError",
            metadata={"attempts": 3, "error": str(last_exc), "deployment": self.deployment},
        )
        raise RuntimeError(f"AIDA brain failed after retries: {last_exc}")

    def _publish(
        self,
        event_type: str,
        status: str,
        *,
        operation_id: str,
        duration_ms: float | None = None,
        error_category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            make_event(
                source="brain",
                event_type=event_type,
                status=status,
                aida_version=self.config.version,
                operation_id=operation_id,
                duration_ms=duration_ms,
                error_category=error_category,
                metadata=metadata or {},
            )
        )
