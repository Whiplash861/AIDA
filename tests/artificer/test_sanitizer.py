from __future__ import annotations

from aida.artificer.sanitizer import PayloadSanitizer


def test_sanitizer_removes_secrets_paths_emails_and_ips() -> None:
    sanitized = PayloadSanitizer().sanitize(
        {
            "api_key": "super-secret",
            "detail": "Bearer abc.def C:\\Users\\Austin\\secret.txt austin@example.com 192.168.1.10",
        }
    )
    assert sanitized["api_key"] == "<REDACTED_SECRET>"
    detail = sanitized["detail"]
    assert "abc.def" not in detail
    assert "Austin" not in detail
    assert "example.com" not in detail
    assert "192.168.1.10" not in detail
