from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from aida.aegis.remote.models import (
    RemoteSessionEvidence,
    RemoteSupportAuthorization,
    RemoteToolEvidence,
    SupportMatch,
    utc_now,
)
from aida.aegis.remote.store import RemoteSecurityStore


class RemoteSupportService:
    """Time-bounded user authorization context for legitimate remote support.

    A support authorization does not whitelist software, suppress Defender, or
    turn observed behavior into training truth. It only gives Aegis context for
    distinguishing expected support from unexplained remote access.
    """

    def __init__(self, store: RemoteSecurityStore) -> None:
        self.store = store

    def authorize(
        self,
        vendor_label: str,
        *,
        duration_minutes: int = 120,
        expected_tools: tuple[str, ...] = (),
        expected_accounts: tuple[str, ...] = (),
        expected_source_addresses: tuple[str, ...] = (),
        note: str = "",
    ) -> RemoteSupportAuthorization:
        vendor = " ".join(vendor_label.strip().split())
        if not vendor:
            raise ValueError("A support vendor or support-session label is required.")
        now = utc_now()
        authorization = RemoteSupportAuthorization(
            vendor_label=vendor,
            starts_at=now,
            expires_at=now + timedelta(minutes=max(5, min(int(duration_minutes), 8 * 60))),
            expected_tools=_normalized(expected_tools),
            expected_accounts=_normalized(expected_accounts),
            expected_source_addresses=_normalized(expected_source_addresses),
            note=note.strip(),
        )
        self.store.store_support_authorization(authorization)
        return authorization

    def active_authorizations(self) -> tuple[RemoteSupportAuthorization, ...]:
        return tuple(item for item in self.store.list_support_authorizations() if item.active)

    def revoke(self, identifier: str = "") -> RemoteSupportAuthorization:
        normalized = identifier.strip().lower()
        active = list(self.active_authorizations())
        if normalized:
            matches = [
                item
                for item in active
                if item.authorization_id.lower().startswith(normalized)
                or item.vendor_label.lower() == normalized
                or normalized in item.vendor_label.lower()
            ]
        else:
            matches = active[:1]
        if len(matches) != 1:
            raise RuntimeError(
                "A unique active remote-support authorization could not be resolved."
            )
        revoked = replace(matches[0], revoked_at=utc_now())
        self.store.store_support_authorization(revoked)
        return revoked

    def best_match(
        self,
        *,
        sessions: tuple[RemoteSessionEvidence, ...],
        tools: tuple[RemoteToolEvidence, ...],
    ) -> SupportMatch | None:
        candidates: list[SupportMatch] = []
        accounts = {session.account.lower() for session in sessions if session.account}
        source_addresses = {
            session.client_address.lower()
            for session in sessions
            if session.client_address
        }
        tool_keys = {tool.tool_key.lower() for tool in tools}
        for authorization in self.active_authorizations():
            expected_accounts = {item.lower() for item in authorization.expected_accounts}
            expected_sources = {
                item.lower() for item in authorization.expected_source_addresses
            }
            expected_tools = {item.lower() for item in authorization.expected_tools}

            matched_accounts = tuple(sorted(accounts & expected_accounts))
            matched_sources = tuple(sorted(source_addresses & expected_sources))
            matched_tools = tuple(sorted(tool_keys & expected_tools))

            score = 0.45
            reasons = [
                "A user-authorized remote-support window is currently active."
            ]
            if expected_accounts:
                if matched_accounts:
                    score += 0.20
                    reasons.append("The observed account matches the support authorization.")
                else:
                    score -= 0.18
            if expected_tools:
                if matched_tools:
                    score += 0.20
                    reasons.append("Observed remote-support tooling matches the authorization.")
                else:
                    score -= 0.18
            if expected_sources:
                if matched_sources:
                    score += 0.12
                    reasons.append("The observed client address matches the authorization.")
                else:
                    score -= 0.12

            # A generic support window is context, not strong identity evidence.
            if not expected_accounts and not expected_tools and not expected_sources:
                reasons.append(
                    "No account, tool, or source fingerprint was supplied, so the support match remains contextual rather than verified."
                )

            candidates.append(
                SupportMatch(
                    authorization_id=authorization.authorization_id,
                    vendor_label=authorization.vendor_label,
                    confidence=max(0.0, min(0.95, score)),
                    matched_tools=matched_tools,
                    matched_accounts=matched_accounts,
                    matched_source_addresses=matched_sources,
                    reasons=tuple(reasons),
                )
            )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.confidence)


def _normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            " ".join(value.strip().split())
            for value in values
            if value and value.strip()
        )
    )
