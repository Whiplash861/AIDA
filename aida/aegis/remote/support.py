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
            matches = active
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
        active_sessions = tuple(session for session in sessions if session.is_active)
        tool_keys = {tool.tool_key.lower() for tool in tools}
        for authorization in self.active_authorizations():
            accounts = {item.casefold() for item in authorization.expected_accounts}
            sources = {item.casefold() for item in authorization.expected_source_addresses}
            expected_tools = {item.casefold() for item in authorization.expected_tools}
            # Account and address must belong to the same session. Independent
            # matches across different sessions never establish authorization.
            matched = tuple(session for session in active_sessions
                if accounts and sources and session.account.casefold() in accounts
                and session.client_address.casefold() in sources and session.logon_time is not None)
            matched_tools = tuple(sorted(tool_keys & expected_tools))
            reasons = ["A user-authorized support window is active; it supplies context only."]
            if matched:
                reasons.append(f"{len(matched)} session(s) match the account and client address in the same authorization.")
            if matched_tools:
                reasons.append("The expected tool is present; its presence does not identify who controls it.")
            fully_matched = bool(active_sessions and len(matched) == len(active_sessions) and not tools)
            candidates.append(SupportMatch(
                authorization_id=authorization.authorization_id,
                vendor_label=authorization.vendor_label,
                confidence=0.85 if fully_matched else 0.65 if matched else 0.35,
                matched_tools=matched_tools,
                matched_accounts=tuple(sorted({session.account for session in matched})),
                matched_source_addresses=tuple(sorted({session.client_address for session in matched})),
                matched_session_ids=tuple(session.session_id for session in matched),
                fully_matched=fully_matched,
                reasons=tuple(reasons),
            ))
        return max(candidates, key=lambda item: item.confidence) if candidates else None



def _normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            " ".join(value.strip().split())
            for value in values
            if value and value.strip()
        )
    )
