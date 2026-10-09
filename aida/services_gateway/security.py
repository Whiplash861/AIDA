from __future__ import annotations
import hmac
import os
from fastapi import Header, HTTPException

def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or not token.isascii() or len(token) > 512:
        raise HTTPException(401, "Invalid or missing gateway credential.", headers={"WWW-Authenticate": "Bearer"})
    return token

def verify_gateway_access(authorization: str | None = Header(default=None)) -> None:
    """Bootstrap credential is accepted only by enrollment, never service routes."""
    configured = (os.getenv("AIDA_SERVICES_GATEWAY_TOKEN") or "").strip()
    if not configured:
        raise HTTPException(503, "Gateway enrollment is not configured.")
    supplied = bearer_token(authorization)
    if not configured.isascii() or not hmac.compare_digest(supplied, configured):
        raise HTTPException(401, "Invalid gateway enrollment credential.", headers={"WWW-Authenticate": "Bearer"})
