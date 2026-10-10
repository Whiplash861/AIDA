from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from aida.frontend.security_alert_bridge import SecurityAlertBridge
from aida.frontend.threat_center_dialog import ThreatCenterDialog
from aida.investigations.models import SecurityAlert, TimelineEntry
from aida.investigations.presentation import alert_explanation, render_alert


STAMP = "2026-10-10T15:03:17+00:00"


def notice(kind, data, *, severity="warning", message="Original technical summary"):
    alert = SecurityAlert("ALERT-1", "CASE-1", "EPISODE-1", severity, message, STAMP, STAMP)
    event = TimelineEntry("EVENT-1", "CASE-1", kind, STAMP, STAMP, message,
                          "gap:Security:0:source", "observed", data)
    return alert, SimpleNamespace(event=event, channel="Security", provenance="exact")


def test_unavailable_history_is_not_presented_as_a_detection_or_an_all_clear():
    alert, context = notice("coverage_gap", {"gaps": ["channel_access_unavailable"]})
    text = render_alert(alert, context)
    assert text.startswith("Check incomplete")
    assert "could not read Windows sign-in and security history" in text
    assert "not a malware detection" in text
    assert "What you can do" in text
    assert "channel_access_unavailable" not in text and "WARNING" not in text
    assert "channel_access_unavailable" in render_alert(alert, context, technical=True)
    assert alert.severity == "warning"  # Display labels never rewrite stored priority.


def test_zero_detections_and_no_baseline_do_not_imply_malware_or_drift():
    alert, context = notice("aegis_assessment", {
        "provider_detection_count": 0, "analyzed_file_count": 8,
        "coverage": {"provider": 1}, "baseline_delta": {"baseline_available": False},
        "risk": {"likelihood": .25, "impact": .9}, "learning_warmup": True,
        "evidence_nodes": [{"kind": "file", "label": "example.exe", "attributes": {
            "assessment": "low_concern", "running_processes": 2, "persistence_references": 1}}],
    }, message="Aegis identified elevated security risk from correlated local evidence and baseline drift.")
    text = render_alert(alert, context)
    assert text.startswith("Security review needs context")
    assert "No antivirus detections were recorded" in text and "8 file reviews" in text
    assert "example.exe: lower concern" in text and "running programs" in text
    assert "did not have an approved saved comparison" in text
    assert "baseline drift" not in text and "elevated security risk" not in text
    assert "baseline drift" in render_alert(alert, context, technical=True)


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_confirmed_and_high_priority_findings_remain_prominent(severity):
    alert, context = notice("aegis_assessment", {
        "provider_detection_count": 1, "evidence_nodes": [
            {"kind": "provider_detection", "label": "Example threat", "attributes": {"active": True}}],
    }, severity=severity)
    text = render_alert(alert, context)
    assert text.startswith("Urgent review:")
    assert "Example threat" in text and "Protection history" in text
    assert "Check incomplete" not in text
    assert render_alert(alert).startswith("Urgent review: supporting details unavailable")


def test_unavailable_provider_results_are_not_presented_as_zero_or_safe():
    alert, context = notice("aegis_assessment", {"provider_detection_count": None, "coverage": {"provider": None}})
    assert "An antivirus detection result was not recorded" in render_alert(alert, context)
    assert "No antivirus detections" not in render_alert(alert, context)
    context.event = replace(context.event, data={"provider_detection_count": 0, "coverage": {"provider": None}})
    assert "zero count is not an all-clear" in render_alert(alert, context)


def test_notification_and_dialog_share_explanation_and_hide_technical_codes():
    qt = QApplication.instance() or QApplication([])
    alert, context = notice("coverage_gap", {"gaps": ["channel_access_unavailable"]})
    output = []
    bridge = SecurityAlertBridge(lambda: None, SimpleNamespace(add_system=lambda text, **kw: output.append((text, kw))))
    dialog = ThreatCenterDialog(SimpleNamespace(list_recent=lambda **kw: []),
        SimpleNamespace(list_active=lambda: []), SimpleNamespace())
    try:
        dialog._apply_investigations(([], [alert], {alert.alert_id: context}))
        assert dialog.alert_list.item(0).text().startswith(alert_explanation(alert, context).title)
        assert "channel_access_unavailable" not in dialog.alert_detail.toPlainText()
        bridge.deliver([(alert, context)])
        assert dialog.alert_detail.toPlainText() in output[0][0]
        assert output[0][1]["include_in_context"] is False
        dialog.alert_technical_details.setChecked(True)
        assert "channel_access_unavailable" in dialog.alert_detail.toPlainText()
        assert "Marking this notice as read" in dialog.alert_detail.toPlainText()
    finally:
        bridge.close()
        dialog.dispose()
        dialog.close()


def test_historical_notice_does_not_claim_current_activity_or_resolution():
    alert, context = notice("windows_event", {"event_id": 1116}, message="Defender history")
    historical = replace(alert, ended_at=STAMP, acknowledged_at=STAMP)
    text = render_alert(historical, context)
    assert "already been handled" in text and "Historical notice" in text
    assert "does not by itself mean the issue was fixed" in text
    assert "Marked as read" in text


def test_missing_remote_results_do_not_become_zero_or_observed_activity():
    alert, context = notice("remote_assessment", {"active_sessions": None, "remote_tools": None})
    text = render_alert(alert, context)
    assert text.startswith("Remote-access result unavailable")
    assert "result was not recorded" in text and "enough information" in text
    assert "Recorded remote sessions: 0" not in text and "AIDA observed remote-access activity" not in text


def test_alert_poll_deduplication_keeps_active_notices_when_cache_is_compacted():
    qt = QApplication.instance() or QApplication([])
    old, context = notice("coverage_gap", {"gaps": ["channel_access_unavailable"]})
    new = replace(old, alert_id="ALERT-new")
    output, lookups = [], []
    service = SimpleNamespace(list_alerts=lambda **kw: [old, new],
        get_alert_context=lambda ident: lookups.append(ident) or context)
    bridge = SecurityAlertBridge(lambda: service, SimpleNamespace(add_system=lambda *args, **kw: output.append(args)))
    bridge._shown = {old.alert_id} | {f"previous-{i}" for i in range(1999)}
    stopped = [False]
    bridge._stop = SimpleNamespace(is_set=lambda: stopped[0], wait=lambda seconds: stopped.__setitem__(0, True))
    bridge._run()
    assert lookups == [new.alert_id] and len(output) == 1
    assert old.alert_id in bridge._shown and new.alert_id in bridge._shown


@pytest.mark.parametrize("kind,data", [
    ("coverage_gap", {"gaps": None}),
    ("aegis_assessment", {"evidence_nodes": [{"kind": "file", "attributes": None}]}),
    ("aegis_assessment", {"evidence_nodes": None, "coverage": None, "baseline_delta": None}),
])
def test_null_supporting_data_cannot_hide_an_urgent_notice(kind, data):
    alert, context = notice(kind, data, severity="critical")
    text = render_alert(alert, context)
    assert text.startswith("Urgent review:")
    assert "Review this notice promptly" in text
    assert "not recorded" in text or "does not include the reason" in text
