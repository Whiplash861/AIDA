from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

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
    mobile_service = service or MobileAidaService()

    application = FastAPI(
        title="AIDA Mobile Bridge",
        description=(
            f"Authenticated local mobile bridge for {APP_FULL_NAME}."
        ),
        version=VERSION,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return mobile_service.health()

    @application.get(
        "/v1/capabilities",
        response_model=CapabilitiesResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def capabilities() -> CapabilitiesResponse:
        return mobile_service.capabilities()

    @application.get(
        "/v1/status",
        response_model=OperationalStatusResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def operational_status() -> OperationalStatusResponse:
        return mobile_service.operational_status()

    @application.get(
        "/v1/activity",
        response_model=ActivityResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def activity(
        limit: int = Query(default=20, ge=1, le=50),
    ) -> ActivityResponse:
        return mobile_service.activity(limit)

    @application.post(
        "/v1/chat",
        response_model=ChatResponse,
        dependencies=[Depends(verify_mobile_access)],
    )
    def chat(request: ChatRequest) -> ChatResponse:
        try:
            return mobile_service.chat(request)
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
