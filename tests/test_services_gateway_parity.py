from __future__ import annotations

from pathlib import Path
from typing import Any

import aida.services_gateway.service as gateway_module
from aida.services_gateway.service import AidaServicesGateway


def test_gateway_resolves_native_quickscan_before_reasoning() -> None:
    gateway = AidaServicesGateway()

    result = gateway.resolve(
        "run a quick scan",
        {"instanceId": "test-mobile-aida"},
    )

    assert result.matched is True
    assert result.command_type == "QUICKSCAN"
    assert result.intent_id == "diagnostics.quickscan"


def test_gateway_resolves_current_technomancer_hardware_trigger() -> None:
    gateway = AidaServicesGateway()

    result = gateway.resolve(
        "show hardware inventory",
        {"instanceId": "test-mobile-aida"},
    )

    assert result.matched is True
    assert result.command_type == "TECHNOMANCER_HARDWARE"
    assert result.intent_id == "technomancer.hardware"
    assert result.local_only is True


def test_identity_prompt_is_not_hijacked_by_generic_identify_action() -> None:
    gateway = AidaServicesGateway()

    result = gateway.resolve(
        "Identify yourself",
        {"instanceId": "test-mobile-aida"},
    )

    assert result.matched is False


def test_explicit_identify_hardware_still_routes_to_technomancer() -> None:
    gateway = AidaServicesGateway()

    result = gateway.resolve(
        "identify my hardware",
        {"instanceId": "test-mobile-aida"},
    )

    assert result.matched is True
    assert result.command_type == "TECHNOMANCER_HARDWARE"
    assert result.intent_id == "technomancer.hardware"


def test_reasoning_receives_native_recent_context_shape() -> None:
    gateway = AidaServicesGateway()
    captured: dict[str, Any] = {}

    class FakeBrain:
        def think(self, user_input: str, context: list[str] | None = None) -> str:
            captured["user_input"] = user_input
            captured["context"] = list(context or [])
            return "Diagnostic response."

    gateway._brain = FakeBrain()  # type: ignore[assignment]

    result = gateway.reason(
        "continue",
        {
            "conversationContext": [
                "System: Analytical Intelligent Diagnostic Agent is activated.",
                "AIDA: State malfunction parameters.",
                "User: First observation.",
                "AIDA: First analysis.",
            ],
            "platform": "Android",
            "platformVersion": "36",
            "deviceModel": "test-device",
            "instanceId": "test-mobile-aida",
            "supportedCapabilities": ["Native AIDA reasoning"],
        },
    )

    assert result.text == "Diagnostic response."
    assert captured["user_input"] == "continue"
    context = captured["context"]
    assert context[:4] == [
        "System: Analytical Intelligent Diagnostic Agent is activated.",
        "AIDA: State malfunction parameters.",
        "User: First observation.",
        "AIDA: First analysis.",
    ]
    assert "Platform: Android" in context
    assert "AIDA instance ID: test-mobile-aida" in context


def test_speech_uses_canonical_cleanup_before_shared_synthesis(monkeypatch) -> None:
    gateway = AidaServicesGateway()
    captured: dict[str, Any] = {}

    def fake_synthesize(text: str, config: Any) -> bytes:
        captured["text"] = text
        captured["config"] = config
        return b"aida-audio"

    monkeypatch.setattr(gateway_module, "synthesize_text", fake_synthesize)

    result = gateway.speak("Status: tool.exe | ready")

    assert result.audio == b"aida-audio"
    assert result.content_type == "audio/mpeg"
    assert captured["text"] == "Status. tool executable . ready"
    assert captured["config"] is gateway._config


def test_mobile_transcription_is_disposable_and_reuses_native_provider(monkeypatch) -> None:
    gateway = AidaServicesGateway()
    captured: dict[str, Any] = {}

    class FakeTranscriber:
        def transcribe(self, path: str | Path) -> str:
            candidate = Path(path)
            assert candidate.is_file()
            captured["path"] = candidate
            captured["bytes"] = candidate.read_bytes()
            return "Run a quick scan."

    monkeypatch.setenv("OPENAI_API_KEY", "test-transcription-key")
    gateway._transcriber = FakeTranscriber()  # type: ignore[assignment]

    result = gateway.transcribe(b"temporary-audio", file_extension=".m4a")

    assert result.text == "Run a quick scan."
    assert captured["bytes"] == b"temporary-audio"
    assert not captured["path"].exists()
