
import pytest
from aida.authorization.confirmation import ConfirmationService, ConfirmationStatus

def test_confirmation_is_exact_bound_and_single_use():
    svc=ConfirmationService()
    req=svc.create(action_id="security.scan.cancel", summary="cancel", scope={"scan_id":"1"}, requested_by="Austin", required_phrase="confirm scan cancellation", risk="high")
    with pytest.raises(RuntimeError):
        svc.confirm(action_id="security.scan.cancel", phrase="yes")
    confirmed=svc.confirm(action_id="security.scan.cancel", phrase="confirm scan cancellation")
    consumed=svc.consume(confirmed.confirmation_id,action_id="security.scan.cancel",expected_scope={"scan_id":"1"})
    assert consumed.status is ConfirmationStatus.CONSUMED
    with pytest.raises(RuntimeError):
        svc.consume(confirmed.confirmation_id,action_id="security.scan.cancel")

def test_new_request_supersedes_older_pending_request():
    service = ConfirmationService()
    first = service.create(
        action_id="security.scan.cancel",
        summary="first",
        scope={"scan_id": "one"},
        requested_by="Austin",
        required_phrase="confirm scan cancellation",
        risk="high",
    )
    second = service.create(
        action_id="security.scan.cancel",
        summary="second",
        scope={"scan_id": "two"},
        requested_by="Austin",
        required_phrase="confirm scan cancellation",
        risk="high",
    )

    pending = service.pending_for_action("security.scan.cancel")
    assert pending is not None
    assert pending.confirmation_id == second.confirmation_id
    with pytest.raises(RuntimeError):
        service.consume(
            first.confirmation_id,
            action_id="security.scan.cancel",
        )
