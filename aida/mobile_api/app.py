from __future__ import annotations

import os
import threading

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from aida.services_gateway.limits import BodyLimitMiddleware, RequestLimits

from aida.config import APP_FULL_NAME, VERSION

from .models import (
    ActivityResponse,
    CapabilitiesResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    OperationalStatusResponse,
)
from .security import verify_mobile_access
from .service import MobileAidaService, MobileBrainUnavailable


def create_app(service: MobileAidaService | None = None) -> FastAPI:
    mobile_service = service
    service_lock = threading.Lock()
    limits = RequestLimits(concurrency=4, per_minute=30)

    def current_service():
        nonlocal mobile_service
        with service_lock:
            if mobile_service is None:
                mobile_service = MobileAidaService()
        return mobile_service

    application = FastAPI(
        title="AIDA Mobile Bridge",
        description=(
            f"Authenticated local mobile bridge for {APP_FULL_NAME}."
        ),
        version=VERSION,
    )

    application.add_middleware(BodyLimitMiddleware)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse({"detail": "Request does not match the mobile bridge contract."}, status_code=422)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return current_service().health()

    @application.get(
        "/v1/capabilities",
        response_model=CapabilitiesResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def capabilities() -> CapabilitiesResponse:
        return current_service().capabilities()

    @application.get(
        "/v1/status",
        response_model=OperationalStatusResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def operational_status() -> OperationalStatusResponse:
        return current_service().operational_status()

    @application.get(
        "/v1/activity",
        response_model=ActivityResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def activity(
        limit: int = Query(default=20, ge=1, le=50),
    ) -> ActivityResponse:
        return current_service().activity(limit)

    @application.post(
        "/v1/chat",
        response_model=ChatResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def chat(request: ChatRequest) -> ChatResponse:
        try:
            with limits.acquire("paired-desktop-client"):
                return current_service().chat(request)
        except MobileBrainUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    return application


def _allowed_origins() -> list[str]:
    configured = (os.getenv("AIDA_MOBILE_ALLOWED_ORIGINS") or "").strip()
    if not configured:
        return [
            "http://localhost:8081",
            "http://localhost:8082",
            "http://localhost:19006",
        ]
    return [item.strip() for item in configured.split(",") if item.strip()]


app = create_app()
