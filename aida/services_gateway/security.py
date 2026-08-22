from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def verify_gateway_access(authorization: str | None = Header(default=None)) -> None:
    configured = (os.getenv("AIDA_SERVICES_GATEWAY_TOKEN") or "").strip()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AIDA services gateway token is not configured.",
        )

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing AIDA gateway bearer token.",
        )

    supplied = authorization[len(prefix) :].strip()
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid AIDA gateway bearer token.",
        )
