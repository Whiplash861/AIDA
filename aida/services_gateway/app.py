from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from .security import verify_gateway_access
from .service import AidaServicesGateway


class DirectiveRequest(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)
    context: dict = Field(default_factory=dict)


class ResolveResponse(BaseModel):
    matched: bool
    command_type: str = ""
    intent_id: str = ""
    local_only: bool = False
    confidence: float | None = None
    requires_confirmation: bool = False
    target_path: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    clarification_text: str = ""


class ReasoningResponse(BaseModel):
    reply: str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)


class SpeechResponse(BaseModel):
    audio_base64: str
    content_type: str


class TranscriptionRequest(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=18_000_000)
    file_extension: str = Field(default=".m4a", min_length=1, max_length=16)


class TranscriptionResponse(BaseModel):
    transcript: str


def create_app(service: AidaServicesGateway | None = None) -> FastAPI:
    gateway = service or AidaServicesGateway()

    app = FastAPI(
        title="AIDA Services Gateway",
        description=(
            "Authenticated service boundary for AIDA intent resolution, "
            "reasoning, speech, and disposable voice transcription. "
            "Provider credentials remain server-side."
        ),
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict:
        return gateway.health()

    @app.get(
        "/v1/ready",
        dependencies=[Depends(verify_gateway_access)],
    )
    def ready() -> dict:
        return gateway.health()

    @app.post(
        "/v1/resolve",
        response_model=ResolveResponse,
        dependencies=[Depends(verify_gateway_access)],
    )
    def resolve(request: DirectiveRequest) -> ResolveResponse:
        try:
            result = gateway.resolve(request.input, request.context)
            return ResolveResponse(
                matched=result.matched,
                command_type=result.command_type,
                intent_id=result.intent_id,
                local_only=result.local_only,
                confidence=result.confidence,
                requires_confirmation=result.requires_confirmation,
                target_path=result.target_path,
                slots=result.slots or {},
                clarification_text=result.clarification_text,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.post(
        "/v1/reasoning",
        response_model=ReasoningResponse,
        dependencies=[Depends(verify_gateway_access)],
    )
    def reasoning(request: DirectiveRequest) -> ReasoningResponse:
        try:
            result = gateway.reason(request.input, request.context)
            return ReasoningResponse(reply=result.text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @app.post(
        "/v1/speech",
        response_model=SpeechResponse,
        dependencies=[Depends(verify_gateway_access)],
    )
    def speech(request: SpeechRequest) -> SpeechResponse:
        try:
            result = gateway.speak(request.text)
            return SpeechResponse(
                audio_base64=base64.b64encode(result.audio).decode("ascii"),
                content_type=result.content_type,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @app.post(
        "/v1/transcription",
        response_model=TranscriptionResponse,
        dependencies=[Depends(verify_gateway_access)],
    )
    def transcription(request: TranscriptionRequest) -> TranscriptionResponse:
        try:
            audio = base64.b64decode(request.audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Voice recording payload is not valid base64 audio.",
            ) from exc

        try:
            result = gateway.transcribe(
                audio,
                file_extension=request.file_extension,
            )
            return TranscriptionResponse(transcript=result.text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    return app


app = create_app()
