from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RemoteAccessClassification(StrEnum):
    NO_REMOTE_ACTIVITY = "no_remote_activity"
    AUTHORIZED_SUPPORT = "authorized_support"
    SUPPORT_SESSION_ANOMALOUS = "support_session_anomalous"
    REMOTE_ACCESS_OBSERVED = "remote_access_observed"
    UNAUTHORIZED_SUSPECTED = "unauthorized_suspected"
    LIKELY_INTRUSION = "likely_intrusion"
    CONFIRMED_INTRUSION = "confirmed_intrusion"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class RemoteSessionEvidence:
    session_id: int
    username: str
    domain: str
    state: str
    protocol_type: int
    client_address: str = ""
    client_name: str = ""
    source: str = "wts"

    @property
    def account(self) -> str:
        if self.domain and self.username:
            return f"{self.domain}\\{self.username}"
        return self.username or self.domain

    @property
    def is_remote_interactive(self) -> bool:
        return self.protocol_type == 2

    @property
    def is_active(self) -> bool:
        return self.state.lower() in {"active", "connected", "shadow"}


@dataclass(frozen=True, slots=True)
class RemoteLogonEvent:
    event_id: int
    observed_at: datetime
    logon_type: int | None
    account: str
    source_address: str = ""
    source_port: str = ""
    success: bool = False
    provider: str = "security_event_log"


@dataclass(frozen=True, slots=True)
class RemoteToolEvidence:
    tool_key: str
    display_name: str
    pid: int
    parent_pid: int | None
    name: str
    executable: str
    create_time: float | None
    remote_endpoints: tuple[str, ...] = ()
    listening_endpoints: tuple[str, ...] = ()
    child_pids: tuple[int, ...] = ()
    security_sensitive_children: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemoteSupportAuthorization:
    vendor_label: str
    starts_at: datetime
    expires_at: datetime
    expected_tools: tuple[str, ...] = ()
    expected_accounts: tuple[str, ...] = ()
    expected_source_addresses: tuple[str, ...] = ()
    note: str = ""
    authorization_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        now = utc_now()
        return self.revoked_at is None and self.starts_at <= now < self.expires_at

    def to_record(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class SupportMatch:
    authorization_id: str
    vendor_label: str
    confidence: float
    matched_tools: tuple[str, ...] = ()
    matched_accounts: tuple[str, ...] = ()
    matched_source_addresses: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemoteIntrusionAssessment:
    assessment_id: str
    created_at: datetime
    classification: RemoteAccessClassification
    intrusion_likelihood: float
    confidence: float
    urgency: float
    active_sessions: tuple[RemoteSessionEvidence, ...]
    recent_logons: tuple[RemoteLogonEvent, ...]
    remote_tools: tuple[RemoteToolEvidence, ...]
    support_match: SupportMatch | None
    provider_detection_count: int
    baseline_change_count: int
    learning_anomaly_score: float
    learning_confidence: float
    evidence: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    degraded_reasons: tuple[str, ...] = ()
    recommended_action: str = "observe"
    user_confirmed_attacker: bool = False

    @classmethod
    def create(
        cls,
        **kwargs: Any,
    ) -> "RemoteIntrusionAssessment":
        return cls(
            assessment_id=uuid4().hex,
            created_at=utc_now(),
            **kwargs,
        )

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["classification"] = self.classification.value
        return _json_safe(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
