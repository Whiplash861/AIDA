from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class MobileDevice(BaseModel):
    platform: str = Field(default="unknown", max_length=64)
    model: str = Field(default="unknown", max_length=128)
    app_version: str = Field(default="unknown", max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    history: list[ConversationMessage] = Field(default_factory=list, max_length=20)
    device: MobileDevice | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex)


class ChatResponse(BaseModel):
    request_id: str
    reply: str
    status: Literal["complete"] = "complete"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HealthResponse(BaseModel):
    service: str = "AIDA Mobile Bridge"
    status: Literal["ready", "degraded"]
    version: str
    brain_configured: bool
    pairing_configured: bool


class Capability(BaseModel):
    id: str
    label: str
    status: Literal[
        "supported",
        "limited",
        "permission_required",
        "unavailable",
    ]
    detail: str


class CapabilitiesResponse(BaseModel):
    platform: str = "mobile"
    capabilities: list[Capability]


class SubsystemStatus(BaseModel):
    id: str
    label: str
    value: str
    tone: Literal["ready", "active", "warning", "error", "idle", "offline"]


class AutonomySnapshot(BaseModel):
    enabled: bool
    label: str


class OperationalStatusResponse(BaseModel):
    host_platform: str
    desktop_online: bool
    updated_at: datetime
    heartbeat_at: datetime
    statuses: list[SubsystemStatus]
    autonomy: AutonomySnapshot


class ActivityItem(BaseModel):
    id: str
    category: str
    message: str
    severity: Literal["info", "warning", "error"]
    source: str
    created_at: datetime


class ActivityResponse(BaseModel):
    items: list[ActivityItem]
