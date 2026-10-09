from __future__ import annotations

import asyncio
import base64
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aida.services_gateway.app import create_app
from aida.services_gateway.limits import BodyLimitMiddleware, RequestLimits
from aida.services_gateway.security import bearer_token, verify_gateway_access
from aida.services_gateway.service import AidaServicesGateway, DirectiveRouteResult
from aida.services_gateway.sessions import SessionStore


class FakeService:
    def __init__(self):
        self.contexts = []
        self.cleared = []
        self.fail = False

    def health(self):
        return dict(reasoning_configured=True, speech_configured=True, transcription_configured=True)

    def resolve(self, text, context):
        self.contexts.append(context)
        return DirectiveRouteResult(matched=False)

    def reason(self, text, context):
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError("SECRET_PROVIDER_PAYLOAD file://private")
        return SimpleNamespace(text="available")

    def clear_session(self, session):
        self.cleared.append(session)

    def transcribe(self, audio, *, file_extension):
        if file_extension not in {".wav", ".m4a"}:
            raise ValueError("PRIVATE_PATH")
        return SimpleNamespace(text="transcript")

    def speak(self, text):
        return SimpleNamespace(audio=b"audio", content_type="audio/mpeg")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDA_SERVICES_GATEWAY_TOKEN", "bootstrap-test-token")
    service = FakeService()
    store = SessionStore(tmp_path / "sessions.sqlite3")
    with TestClient(create_app(service, sessions=store)) as client:
        yield client, store, service


def enroll(client):
    result = client.post("/v1/enroll", headers={"Authorization": "Bearer bootstrap-test-token"})
    assert result.status_code == 200
    return result.json()


def session_headers(result):
    return {"Authorization": "Bearer " + result["token"]}


def test_bootstrap_only_enrolls_and_session_only_uses_providers(api):
    client, _, _ = api
    assert client.get("/v1/ready", headers={"Authorization": "Bearer bootstrap-test-token"}).status_code == 401
    session = enroll(client)
    assert client.get("/v1/ready", headers=session_headers(session)).json()["protocol_version"] == 2
    assert client.post("/v1/enroll", headers=session_headers(session)).status_code == 401


def test_identity_cannot_be_spoofed_and_revocation_is_device_scoped(api):
    client, _, service = api
    first, second = enroll(client), enroll(client)
    body = {"input": "identify yourself", "context": {"instanceId": "same-device", "conversationId": "same-conversation"}}
    for session in (first, second):
        assert client.post("/v1/resolve", json=body, headers=session_headers(session)).status_code == 200
    assert service.contexts[0]["instanceId"] == first["device_id"]
    assert service.contexts[1]["instanceId"] == second["device_id"]
    assert service.contexts[0]["sessionId"] != service.contexts[1]["sessionId"]
    assert client.delete("/v1/session", headers=session_headers(first)).json() == {"revoked": True}
    assert client.get("/v1/ready", headers=session_headers(first)).status_code == 401
    assert client.get("/v1/ready", headers=session_headers(second)).status_code == 200
    assert len(service.cleared) == 1


def test_session_tokens_are_hashed_and_expire(api):
    client, store, _ = api
    session = enroll(client)
    assert session["token"].encode() not in store.path.read_bytes()
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert client.get("/v1/ready", headers=session_headers(session)).status_code == 401


@pytest.mark.parametrize("authorization", ["Bearer cafÃƒÂ©", "Bearer " + "x" * 513, "Basic abc", "Bearer", None])
def test_bad_bearer_returns_401_without_compare_digest_type_error(authorization):
    with pytest.raises(HTTPException) as error:
        bearer_token(authorization)
    assert error.value.status_code == 401


def test_bootstrap_unicode_is_rejected(monkeypatch):
    monkeypatch.setenv("AIDA_SERVICES_GATEWAY_TOKEN", "ascii-token")
    with pytest.raises(HTTPException) as error:
        verify_gateway_access("Bearer cafÃƒÂ©")
    assert error.value.status_code == 401


@pytest.mark.parametrize("context", [
    {"conversationContext": ["SECRET"] * 13},
    {"deviceModel": "SECRET" * 100},
    {"sessionId": "spoofed"},
    {"conversationContext": [{"private": "SECRET"}]},
])
def test_context_contract_is_bounded_and_never_echoes_invalid_input(api, context):
    client, _, _ = api
    response = client.post("/v1/reasoning", headers=session_headers(enroll(client)), json={"input": "question", "context": context})
    assert response.status_code == 422
    assert "SECRET" not in response.text and "spoofed" not in response.text


def test_provider_error_payload_is_not_exposed(api):
    client, _, service = api
    service.fail = True
    result = client.post("/v1/reasoning", headers=session_headers(enroll(client)), json={"input": "question"})
    assert result.status_code == 503
    assert "SECRET" not in result.text and "private" not in result.text


def test_input_and_raw_body_size_limits(api):
    client, _, _ = api
    headers = session_headers(enroll(client))
    assert client.post("/v1/reasoning", headers=headers, json={"input": "x" * 8001}).status_code == 422
    assert client.post("/v1/reasoning", headers=headers, content=b"x" * 65537).status_code == 413


def test_invalid_audio_never_reaches_provider(api):
    client, _, _ = api
    headers = session_headers(enroll(client))
    assert client.post("/v1/transcription", headers=headers, json={"audio_base64": "!INVALID!"}).status_code == 400
    result = client.post("/v1/transcription", headers=headers, json={"audio_base64": base64.b64encode(b"audio").decode(), "file_extension": ".secret"})
    assert result.status_code == 400 and "PRIVATE" not in result.text


def test_chunked_body_bound_is_applied_before_downstream():
    events = iter([{"type": "http.request", "body": b"x" * 40000, "more_body": True}, {"type": "http.request", "body": b"x" * 40000}])
    sent = []
    async def downstream(*_args):
        pytest.fail("Oversized body reached downstream")
    async def receive():
        return next(events)
    async def send(message):
        sent.append(message)
    asyncio.run(BodyLimitMiddleware(downstream)({"type": "http", "path": "/v1/reasoning", "headers": []}, receive, send))
    assert sent[0]["status"] == 413


def test_concurrency_slot_released_after_error_and_rate_is_per_identity():
    limits = RequestLimits(concurrency=1, per_minute=2)
    with pytest.raises(ValueError):
        with limits.acquire("a"):
            with pytest.raises(HTTPException) as error:
                with limits.acquire("b"):
                    pass
            assert error.value.status_code == 503
            raise ValueError()
    with limits.acquire("a"):
        pass
    with pytest.raises(HTTPException) as error:
        with limits.acquire("a"):
            pass
    assert error.value.status_code == 429
    with limits.acquire("other"):
        pass


def test_router_context_is_separate_for_session_and_conversation():
    gateway = AidaServicesGateway()
    for session, conversation in [("one", "chat1"), ("two", "chat1"), ("one", "chat2")]:
        gateway.resolve("run a quick scan", {"sessionId": session, "conversationId": conversation})
    routers = [entry[1] for entry in gateway._routers.values()]
    assert len({id(router) for router in routers}) == 3
    gateway.clear_session("one")
    assert list(gateway._routers) == ["two:chat1"]


def test_failed_transcription_still_removes_temporary_audio(tmp_path, monkeypatch):
    gateway = AidaServicesGateway()
    seen = []
    class Broken:
        def transcribe(self, path):
            seen.append(path)
            assert path.read_bytes() == b"voice"
            raise RuntimeError("provider failure")
    gateway._transcriber = Broken()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    with pytest.raises(RuntimeError):
        gateway.transcribe(b"voice")
    assert seen and not seen[0].exists()


def test_speech_path_cleanup_preserves_following_sentence():
    from aida.audio.text import clean_for_tts
    assert clean_for_tts('Status: "C:\\private folder\\a.exe" is ready') == "Status. file path is ready"
    assert clean_for_tts("C:\\private\\a.exe is ready") == "file path is ready"

def test_ingress_admission_rejects_before_reading_and_releases_on_disconnect():
    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()
        sent = []
        reads = 0
        async def downstream(*_args):
            pytest.fail("Disconnected request reached downstream")
        async def receive():
            nonlocal reads
            reads += 1
            started.set()
            await release.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            sent.append(message)
        app = BodyLimitMiddleware(downstream, concurrency=1)
        scope = {"type": "http", "path": "/v1/transcription", "headers": []}
        first = asyncio.create_task(app(scope, receive, send))
        await started.wait()
        await app(scope, receive, send)
        assert sent[0]["status"] == 503
        assert reads == 1
        release.set()
        await first
        await app(scope, receive, send)
        assert reads == 2
    asyncio.run(scenario())


def test_tts_failed_playback_removes_disposable_audio(tmp_path, monkeypatch):
    import sys
    from aida.audio import voice
    captured = []
    def fail(path, **_kwargs):
        captured.append(path)
        assert __import__("pathlib").Path(path).read_bytes() == b"voice"
        raise RuntimeError("PRIVATE_PATH")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    monkeypatch.setitem(sys.modules, "playsound", SimpleNamespace(playsound=fail))
    voice._play_mp3_bytes_blocking(b"voice")
    assert captured and not __import__("pathlib").Path(captured[0]).exists()

def test_tones_use_builtin_windows_audio_without_simpleaudio(tmp_path, monkeypatch):
    import sys
    from aida.audio import tones
    (tmp_path / "aida_start.wav").write_bytes(b"fake WAV handled by mocked player")
    calls = []
    fake = SimpleNamespace(SND_FILENAME=1, SND_NODEFAULT=2, SND_ASYNC=4, PlaySound=lambda path, flags: calls.append((path, flags)))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    monkeypatch.setattr(tones, "os", SimpleNamespace(name="nt", path=__import__("os").path))
    tones.play_start_tone(SimpleNamespace(sounds_dir=tmp_path), blocking=True)
    assert calls[0][1] == 3


def test_missing_optional_nonwindows_tone_backend_is_graceful(tmp_path, monkeypatch):
    import builtins
    from aida.audio import tones
    (tmp_path / "aida_start.wav").write_bytes(b"fake")
    original_import = builtins.__import__
    def optional_import(name, *args, **kwargs):
        if name == "simpleaudio":
            raise ImportError("optional dependency absent")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(tones, "os", SimpleNamespace(name="posix", path=__import__("os").path))
    monkeypatch.setattr(builtins, "__import__", optional_import)
    tones.play_start_tone(SimpleNamespace(sounds_dir=tmp_path))
