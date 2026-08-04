from aida.memory.privacy import sanitize_payload, sanitize_text


def test_redacts_bearer_and_jwt_tokens() -> None:
    value = (
        "Authorization: Bearer abc.def.ghi "
        "and eyJabcdefgh.ijklmnop.qrstuvwx"
    )

    sanitized = sanitize_text(value)

    assert "abc.def.ghi" not in sanitized
    assert "eyJabcdefgh.ijklmnop.qrstuvwx" not in sanitized
    assert "[REDACTED]" in sanitized


def test_redacts_nested_client_and_refresh_tokens() -> None:
    sanitized = sanitize_payload(
        {
            "client_secret": "secret-value",
            "nested": {"refresh_token": "refresh-value"},
            "ordinary": "keep this",
        }
    )

    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["nested"]["refresh_token"] == "[REDACTED]"
    assert sanitized["ordinary"] == "keep this"
