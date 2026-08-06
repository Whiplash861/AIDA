from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status


def mobile_pairing_configured() -> bool:
    return bool(_configured_token()) or _allow_insecure_dev()


def verify_mobile_access(
    authorization: str | None = Header(default=None),
) -> None:
    configured = _configured_token()

    if not configured:
        if _allow_insecure_dev():
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AIDA mobile pairing is not configured. Set "
                "AIDA_MOBILE_TOKEN or explicitly enable insecure development mode."
            ),
        )

    supplied = _bearer_token(authorization)
    if not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing AIDA mobile pairing token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _configured_token() -> str:
    return (os.getenv("AIDA_MOBILE_TOKEN") or "").strip()


def _allow_insecure_dev() -> bool:
    return (os.getenv("AIDA_MOBILE_ALLOW_INSECURE_DEV") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bearer_token(value: str | None) -> str:
    if not value:
        return ""
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()
