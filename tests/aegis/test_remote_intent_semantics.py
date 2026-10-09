from __future__ import annotations

import pytest

from aida.frontend.command_router import CommandRouter, CommandType


@pytest.mark.parametrize(
    "text",
    [
        "somebody is in my computer",
        "someone is remotely connected to my computer",
        "check for unauthorized remote access",
        "check for remote intrusion",
    ],
)
def test_remote_intrusion_language_routes_to_aegis(text: str) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is CommandType.SECURITY_REMOTE_INTRUSION_CHECK
    assert command.local_only is True


def test_user_alarm_wording_marks_remote_access_as_unexpected() -> None:
    command = CommandRouter().route("somebody is in my computer")
    assert command is not None
    assert command.slots["unexpected_remote_access"] is True


def test_authorize_named_support_vendor_with_natural_duration() -> None:
    command = CommandRouter().route("authorize Northstar support for two hours")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_REMOTE_SUPPORT_AUTHORIZE
    assert command.slots["support_vendor"] == "Northstar"
    assert command.slots["duration_minutes"] == 120


def test_authorize_support_can_capture_expected_tool() -> None:
    command = CommandRouter().route(
        "authorize Northstar support using ScreenConnect for 2 hours"
    )
    assert command is not None
    assert command.command_type is CommandType.SECURITY_REMOTE_SUPPORT_AUTHORIZE
    assert command.slots["support_vendor"] == "Northstar"
    assert command.slots["expected_tools"] == ("screenconnect",)
    assert command.slots["duration_minutes"] == 120


def test_list_and_revoke_support_route_without_confusing_scan_cancel() -> None:
    router = CommandRouter()
    listed = router.route("show remote support authorizations")
    assert listed is not None
    assert listed.command_type is CommandType.SECURITY_REMOTE_SUPPORT_LIST

    revoked = router.route("revoke Northstar support")
    assert revoked is not None
    assert revoked.command_type is CommandType.SECURITY_REMOTE_SUPPORT_REVOKE
    assert revoked.slots["support_vendor"] == "Northstar"


@pytest.mark.parametrize(
    "text",
    [
        "confirm attacker",
        "that's not support that's an attacker",
        "this remote access is unauthorized",
    ],
)
def test_attacker_confirmation_is_distinct_from_initial_detection(text: str) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is CommandType.SECURITY_REMOTE_ATTACKER_CONFIRM


def test_dynamic_sentry_exact_phrase_routes_with_plan_id() -> None:
    plan_id = "SENTRY-20260904-123456-a1b2c3d4"
    command = CommandRouter().route(f"CONFIRM SENTRY ATTACK {plan_id}")
    assert command is not None
    assert command.command_type is CommandType.SENTRY_ATTACK_CONFIRM
    assert command.slots["sentry_plan_id"] == plan_id
    assert command.local_only is True
