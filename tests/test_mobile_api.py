from __future__ import annotations

import pytest
from fastapi import HTTPException

from aida.mobile_api.models import ChatRequest, ConversationMessage, MobileDevice
from aida.mobile_api.security import verify_mobile_access
from aida.mobile_api.service import MobileAidaService
from aida.operational_state import OperationalStateStore


class StubBrain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []

    def think(self, user_input: str, context: list[str] | None = None) -> str:
        self.calls.append((user_input, context))
        return "Mobile bridge response."


def test_mobile_service_forwards_history_and_device_context(tmp_path) -> None:
    brain = StubBrain()
    service = MobileAidaService(
        brain_factory=lambda: brain,  # type: ignore[arg-type]
        state_store=OperationalStateStore(tmp_path / "state.json"),
    )

    response = service.chat(
        ChatRequest(
            message="Status report",
            history=[
                ConversationMessage(role="user", content="Previous question"),
                ConversationMessage(role="assistant", content="Previous answer"),
            ],
            device=MobileDevice(
                platform="ios 19",
                model="iPhone",
                app_version="1.0.0",
            ),
        )
    )

    assert response.reply == "Mobile bridge response."
    assert brain.calls[0][0] == "Status report"
    rendered_context = "\n".join(brain.calls[0][1] or [])
    assert "ios 19" in rendered_context
    assert "Previous question" in rendered_context
    assert "desktop diagnostic command" in rendered_context


def test_mobile_service_returns_operational_status_and_activity(tmp_path) -> None:
    store = OperationalStateStore(tmp_path / "state.json")
    store.mark_online("STANDBY")
    store.set_status("artificer", "REVIEWING")
    store.add_activity("ARTIFICER review started")

    service = MobileAidaService(
        brain_factory=StubBrain,  # type: ignore[arg-type]
        state_store=store,
    )

    snapshot = service.operational_status()
    activity = service.activity(10)

    assert snapshot.desktop_online is True
    artificer = next(item for item in snapshot.statuses if item.id == "artificer")
    assert artificer.value == "REVIEWING"
    assert artificer.tone == "active"
    assert activity.items[0].category == "ARTIFICER"
    assert activity.items[0].message == "ARTIFICER review started"


def test_mobile_access_requires_pairing_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIDA_MOBILE_TOKEN", raising=False)
    monkeypatch.delenv("AIDA_MOBILE_ALLOW_INSECURE_DEV", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        verify_mobile_access(None)

    assert exc_info.value.status_code == 503


def test_mobile_access_accepts_matching_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDA_MOBILE_TOKEN", "test-pairing-token")
    monkeypatch.delenv("AIDA_MOBILE_ALLOW_INSECURE_DEV", raising=False)

    verify_mobile_access("Bearer test-pairing-token")
