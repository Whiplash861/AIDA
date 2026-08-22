from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from .security import verify_gateway_access
from .service import AidaServicesGateway


class ReasoningRequest(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)
    context: dict = Field(default_factory=dict)


class ReasoningResponse(BaseModel):
    reply: str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)


def create_app(service: AidaServicesGateway | None = None) -> FastAPI:
    gateway = service or AidaServicesGateway()

    app = FastAPI(
        title="AIDA Services Gateway",
        description=(
            "Authenticated service boundary for AIDA reasoning and speech. "
            "Provider credentials remain server-side."
        ),
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict:
        return gateway.health()

    @app.post(
        "/v1/reasoning",
        response_model=ReasoningResponse,
        dependencies=[Depends(verify_gateway_access)],
    )
    def reasoning(request: ReasoningRequest) -> ReasoningResponse:
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
        dependencies=[Depends(verify_gateway_access)],
    )
    def speech(request: SpeechRequest) -> Response:
        try:
            result = gateway.speak(request.text)
            return Response(content=result.audio, media_type=result.content_type)
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
