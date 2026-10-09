from __future__ import annotations
import base64
import binascii
import os
import threading
from typing import Annotated, Any
from uuid import uuid4
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from .limits import BodyLimitMiddleware, RequestLimits
from .security import bearer_token, verify_gateway_access
from .service import AidaServicesGateway
from .sessions import DeviceSession, SessionStore

ShortText = Annotated[str, Field(max_length=256)]
ContextLine = Annotated[str, Field(max_length=4000)]

class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    platform: ShortText = "unknown"
    platformVersion: ShortText = ""
    deviceModel: ShortText = ""
    instanceId: ShortText = ""  # Replaced by authenticated identity.
    conversationId: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,96}$")] = "default"
    supportedCapabilities: list[ShortText] = Field(default_factory=list, max_length=32)
    conversationContext: list[ContextLine] = Field(default_factory=list, max_length=12)

class DirectiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=8000)
    context: RuntimeContext = Field(default_factory=RuntimeContext)

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

class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)

class TranscriptionRequest(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=16_777_216)
    file_extension: str = Field(default=".m4a", min_length=1, max_length=16)

def create_app(service: AidaServicesGateway | None = None, *, sessions: SessionStore | None = None) -> FastAPI:
    # No provider objects, configuration directories or session DB on import.
    gateway = service
    gateway_lock = threading.Lock()
    store = sessions or SessionStore()
    limits = RequestLimits()
    enrollment_limits = RequestLimits(concurrency=2, per_minute=6)
    app = FastAPI(title="AIDA Services Gateway", version="0.2.0")
    app.add_middleware(BodyLimitMiddleware)
    origins = [origin.strip() for origin in os.getenv("AIDA_GATEWAY_CORS_ORIGINS", "").split(",") if origin.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"], allow_credentials=False)

    def get_gateway():
        nonlocal gateway
        with gateway_lock:
            if gateway is None:
                gateway = AidaServicesGateway()
        return gateway

    def access(authorization: str | None = Header(default=None)) -> DeviceSession:
        session = store.authenticate(bearer_token(authorization))
        if session is None:
            raise HTTPException(401, "Gateway session expired or revoked. Enroll again.", headers={"WWW-Authenticate": "Bearer"})
        return session

    def context_for(request: DirectiveRequest, session: DeviceSession):
        context = request.context.model_dump()
        context["instanceId"] = session.device_id
        context["sessionId"] = session.session_id
        return context

    def invoke(session: DeviceSession, operation):
        with limits.acquire(session.session_id):
            try:
                return operation()
            except HTTPException:
                raise
            except ValueError as exc:
                raise HTTPException(400, "The requested operation or supplied media is invalid.") from exc
            except Exception as exc:
                raise HTTPException(503, f"AIDA provider unavailable. Reference {uuid4().hex}.") from exc

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        # Default validation errors echo the rejected input, possibly voice/secrets.
        return JSONResponse({"detail": "Request does not match the bounded gateway contract."}, status_code=422)

    @app.get("/health")
    def health():
        return {"service": "AIDA Services Gateway", "status": "online", "protocol_version": 2}

    @app.post("/v1/enroll", dependencies=[Depends(verify_gateway_access)])
    def enroll():
        with enrollment_limits.acquire("enrollment"):
            token, session = store.issue()
        return {"token": token, "device_id": session.device_id, "expires_at": session.expires_at, "protocol_version": 2}

    @app.delete("/v1/session")
    def revoke(session: DeviceSession = Depends(access)):
        store.revoke(session)
        if gateway is not None:
            gateway.clear_session(session.session_id)
        return {"revoked": True}

    @app.get("/v1/ready")
    def ready(session: DeviceSession = Depends(access)):
        return invoke(session, lambda: {**get_gateway().health(), "protocol_version": 2})

    @app.post("/v1/resolve", response_model=ResolveResponse)
    def resolve(request: DirectiveRequest, session: DeviceSession = Depends(access)):
        return invoke(session, lambda: get_gateway().resolve(request.input, context_for(request, session)))

    @app.post("/v1/reasoning")
    def reasoning(request: DirectiveRequest, session: DeviceSession = Depends(access)):
        return invoke(session, lambda: {"reply": get_gateway().reason(request.input, context_for(request, session)).text})

    @app.post("/v1/speech")
    def speech(request: SpeechRequest, session: DeviceSession = Depends(access)):
        def operation():
            result = get_gateway().speak(request.text)
            return {"audio_base64": base64.b64encode(result.audio).decode("ascii"), "content_type": result.content_type}
        return invoke(session, operation)

    @app.post("/v1/transcription")
    def transcription(request: TranscriptionRequest, session: DeviceSession = Depends(access)):
        def operation():
            try:
                audio = base64.b64decode(request.audio_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(400, "Voice recording is not valid base64 audio.") from exc
            return {"transcript": get_gateway().transcribe(audio, file_extension=request.file_extension).text}
        return invoke(session, operation)


    return app

app = create_app()
