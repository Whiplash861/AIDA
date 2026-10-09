from __future__ import annotations

import base64
import json
import hashlib
from urllib.parse import urlsplit
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from aida.artificer.consent import ConsentManager
from aida.artificer.developer_registry import DeveloperRegistry
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.sanitizer import PayloadSanitizer
from aida.artificer.models import utc_now, TelemetryLevel


@dataclass(frozen=True, slots=True)
class DispatchResult:
    success: bool
    status: str
    detail: str


class DispatchTransport(Protocol):
    def send(self, bundle: dict[str, Any]) -> DispatchResult:
        ...


class DisabledTransport:
    def send(self, bundle: dict[str, Any]) -> DispatchResult:
        del bundle
        return DispatchResult(False, "disabled", "Remote dispatch is disabled")


class LocalExportTransport:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def send(self, bundle: dict[str, Any]) -> DispatchResult:
        dispatch_id = str(bundle.get("dispatch_id", uuid.uuid4()))
        path = self.directory / f"artificer_dispatch_{dispatch_id}.json"
        path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        return DispatchResult(True, "exported", str(path))


class HTTPSDispatchTransport:
    def __init__(self, endpoint: str, *, timeout_seconds: int = 20) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Dispatch requires an HTTPS endpoint without embedded credentials")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def send(self, bundle: dict[str, Any]) -> DispatchResult:
        data = json.dumps(bundle, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "AIDA-Artificer/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if 200 <= response.status < 300:
                    return DispatchResult(True, "sent", f"HTTP {response.status}")
                return DispatchResult(False, "retry", f"HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return DispatchResult(False, "retry", str(exc))


class EnvelopeEncryptor:
    """Hybrid RSA/AES encryption. Refuses remote plaintext when unavailable."""

    def encrypt(self, payload: dict[str, Any], public_key_pem: str) -> dict[str, str]:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("cryptography is required for encrypted remote dispatch") from exc

        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        aes_key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext, None)
        wrapped_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return {
            "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
            "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }


class ArtificerDispatch:
    def __init__(
        self,
        *,
        ledger: ArtificerLedger,
        sanitizer: PayloadSanitizer,
        consent: ConsentManager,
        developers: DeveloperRegistry,
        transport: DispatchTransport,
    ) -> None:
        self.ledger = ledger
        self.sanitizer = sanitizer
        self.consent = consent
        self.developers = developers
        self.transport = transport
        self.encryptor = EnvelopeEncryptor()

    def queue(self, report_type: str, payload: dict[str, Any]) -> str:
        if not self.consent.permits(report_type):
            raise PermissionError(f"Current consent does not permit {report_type} dispatch")
        sanitized = self.sanitizer.sanitize(payload)
        if self.consent.state.telemetry_level is TelemetryLevel.ANONYMOUS:
            sanitized = _anonymous_summary(sanitized)
        recipients = self.developers.list_active(report_type)
        if not recipients:
            raise RuntimeError(f"No authorized recipients exist for {report_type}")
        dispatch_id = str(uuid.uuid4())
        recipient_payloads: list[dict[str, Any]] = []
        for recipient in recipients:
            base = {
                "dispatch_id": dispatch_id,
                "report_type": report_type,
                "recipient_id": recipient.developer_id,
                "created_at_utc": utc_now().isoformat(),
                "payload": sanitized,
            }
            if recipient.public_key_pem:
                encrypted = self.encryptor.encrypt(base, recipient.public_key_pem)
                recipient_payloads.append(
                    {
                        "recipient_id": recipient.developer_id,
                        "encrypted": True,
                        "key_fingerprint": hashlib.sha256(recipient.public_key_pem.encode()).hexdigest(),
                        "envelope": encrypted,
                    }
                )
            elif isinstance(self.transport, HTTPSDispatchTransport):
                raise RuntimeError(
                    f"Remote recipient {recipient.developer_id} does not have an encryption key"
                )
            else:
                recipient_payloads.append(
                    {"recipient_id": recipient.developer_id, "encrypted": False, "envelope": base}
                )
        bundle = {
            "dispatch_id": dispatch_id,
            "report_type": report_type,
            "recipients": recipient_payloads,
            "consent_revision": self.consent.state.updated_at_utc,
            "telemetry_level": self.consent.state.telemetry_level.value,
        }
        self.ledger.queue_dispatch(
            dispatch_id=dispatch_id, report_type=report_type, payload=bundle
        )
        return dispatch_id

    def flush(self, limit: int = 20) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for queued in self.ledger.list_queued_dispatches(limit=limit):
            bundle = queued["payload"]
            state = self.consent.state
            authorized = {record.developer_id: record for record in self.developers.list_active(queued["report_type"])}
            valid = (self.consent.permits(queued["report_type"])
                     and bundle.get("consent_revision") == state.updated_at_utc
                     and bundle.get("telemetry_level") == state.telemetry_level.value)
            recipients = bundle.get("recipients", [])
            valid = valid and bool(recipients)
            for item in recipients:
                recipient = authorized.get(item.get("recipient_id"))
                if recipient is None:
                    valid = False
                    continue
                if item.get("encrypted"):
                    valid = valid and bool(recipient.public_key_pem) and item.get("key_fingerprint") == hashlib.sha256((recipient.public_key_pem or "").encode()).hexdigest()
                elif isinstance(self.transport, HTTPSDispatchTransport):
                    valid = False
            if not valid:
                result = DispatchResult(False, "blocked", "Consent, recipient authorization or encryption changed; create a new report.")
                results.append(result)
                self.ledger.update_dispatch_status(queued["dispatch_id"], "blocked", error=result.detail)
                continue
            result = self.transport.send(bundle)
            results.append(result)
            self.ledger.update_dispatch_status(
                queued["dispatch_id"],
                "sent" if result.success else "retry",
                error=None if result.success else result.detail,
            )
        return results


def _anonymous_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Anonymous reports contain aggregate measurements, never stable IDs/text."""
    import math
    allowed = {"count", "status", "duration_ms", "error_count", "finding_count", "sample_count", "success", "failed", "version", "engine", "category"}
    output = {}
    for key, value in payload.items():
        if key not in allowed and not key.endswith("_count"):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)) and math.isfinite(value):
            output[key] = value
        elif key in {"status", "version", "engine", "category"} and isinstance(value, str):
            import re
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", value):
                output[key] = value
    return output
