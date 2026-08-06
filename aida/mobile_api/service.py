from __future__ import annotations

import os
from collections.abc import Callable

from aida.brain.llm_client import AIDABrain
from aida.config import APP_FULL_NAME, VERSION
from aida.logging_utils import get_logger

from .models import (
    CapabilitiesResponse,
    Capability,
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from .security import mobile_pairing_configured


log = get_logger(__name__)


class MobileBrainUnavailable(RuntimeError):
    """Raised when the configured AIDA reasoning provider cannot answer."""


class MobileAidaService:
    def __init__(
        self,
        brain_factory: Callable[[], AIDABrain] = AIDABrain,
    ) -> None:
        self._brain_factory = brain_factory
        self._brain: AIDABrain | None = None

    def health(self) -> HealthResponse:
        brain_configured = all(
            (os.getenv(name) or "").strip()
            for name in (
                "AZURE_OPENAI_ENDPOINT",
                "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_DEPLOYMENT",
            )
        )
        pairing_configured = mobile_pairing_configured()

        return HealthResponse(
            status=(
                "ready"
                if brain_configured and pairing_configured
                else "degraded"
            ),
            version=VERSION,
            brain_configured=brain_configured,
            pairing_configured=pairing_configured,
        )

    def capabilities(self) -> CapabilitiesResponse:
        return CapabilitiesResponse(
            capabilities=[
                Capability(
                    id="conversation",
                    label="AIDA conversation",
                    status="supported",
                    detail=(
                        f"Authenticated text conversation with {APP_FULL_NAME}."
                    ),
                ),
                Capability(
                    id="device_diagnostics",
                    label="Mobile device diagnostics",
                    status="limited",
                    detail=(
                        "Only information exposed by the mobile operating system and "
                        "explicitly granted by the user can be inspected."
                    ),
                ),
                Capability(
                    id="remote_commands",
                    label="Desktop command execution",
                    status="unavailable",
                    detail=(
                        "Remote diagnostic and corrective commands remain disabled "
                        "until a separate authorization layer is implemented."
                    ),
                ),
                Capability(
                    id="voice",
                    label="Voice interaction",
                    status="permission_required",
                    detail="Scheduled for the next mobile integration phase.",
                ),
                Capability(
                    id="image_analysis",
                    label="Image and screenshot analysis",
                    status="permission_required",
                    detail="Scheduled for the next mobile integration phase.",
                ),
            ]
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        context = self._context_for(request)

        log.info(
            "Mobile reasoning request received. request_id=%s history=%d",
            request.request_id,
            len(request.history),
        )

        try:
            reply = self._get_brain().think(
                request.message.strip(),
                context=context,
            )
        except Exception as exc:
            log.exception(
                "Mobile reasoning request failed. request_id=%s",
                request.request_id,
            )
            raise MobileBrainUnavailable(
                "AIDA's reasoning service is currently unavailable."
            ) from exc

        return ChatResponse(
            request_id=request.request_id,
            reply=reply,
        )

    def _get_brain(self) -> AIDABrain:
        if self._brain is None:
            self._brain = self._brain_factory()
        return self._brain

    @staticmethod
    def _context_for(request: ChatRequest) -> list[str]:
        context = [
            "The user is communicating through AIDA's authenticated mobile client.",
            (
                "Do not claim that mobile operating-system restrictions have been "
                "bypassed. Do not claim that a desktop diagnostic command ran unless "
                "the backend explicitly supplies such a result."
            ),
        ]

        if request.device is not None:
            context.append(
                "Mobile client: "
                f"platform={request.device.platform}; "
                f"model={request.device.model}; "
                f"app_version={request.device.app_version}."
            )

        if request.history:
            rendered_history = "\n".join(
                f"{item.role.upper()}: {item.content}"
                for item in request.history[-20:]
            )
            context.append(
                "Recent mobile conversation history:\n" + rendered_history
            )

        return context
