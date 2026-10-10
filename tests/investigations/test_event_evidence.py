from dataclasses import replace
from types import SimpleNamespace
from datetime import timedelta
import json
import pytest

from aida.aegis.event_evidence import EventPage, IncrementalEventCollector, NativeEvent, WindowsEventSource
from aida.investigations import InvestigationService, InvestigationStore
from aida.investigations.models import utc_now


def event(record_id=1):
    return NativeEvent("Security", record_id, 4625, utc_now().isoformat(), "Microsoft-Windows-Security-Auditing",
        {"LogonType": "10", "TargetUserName": "sample", "TargetDomainName": "test", "IpAddress": "192.0.2.1"})


class Source:
    def __init__(self, page):
        self.page = page
        self.bookmarks = []

    def read(self, channel, bookmark, *, limit):
        self.bookmarks.append(bookmark)
        return self.page


def collector(tmp_path, source):
    return IncrementalEventCollector(InvestigationService(InvestigationStore(tmp_path / "events.db")), source=source)


def test_event_and_bookmark_commit_together_and_restart_does_not_duplicate(tmp_path):
    item = event()
    source = Source(EventPage((item,), item))
    first = collector(tmp_path, source)
    first.poll(channels=("Security",))
    restarted = collector(tmp_path, source)
    restarted.poll(channels=("Security",))
    with restarted.store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM collected_events").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM investigation_timeline WHERE kind='windows_event'").fetchone()[0] == 1
    assert source.bookmarks[1]["record_id"] == item.record_id


def test_access_failure_never_advances_bookmark_and_gap_alert_dedupes(tmp_path):
    item = event()
    source = Source(EventPage((item,), item))
    read = collector(tmp_path, source)
    read.poll(channels=("Security",))
    source.page = EventPage((), None, ("channel_access_unavailable",))
    read.poll(channels=("Security",)); read.poll(channels=("Security",))
    with read.store.connect() as connection:
        assert connection.execute("SELECT record_id FROM event_bookmarks").fetchone()[0] == item.record_id
    assert len(read.investigations.list_alerts()) == 1


def test_gap_alert_explains_incomplete_check_and_preserves_exact_machine_evidence(tmp_path):
    read = collector(tmp_path, Source(EventPage((), None, ("channel_access_unavailable",))))
    read.poll(channels=("Security",))
    alert = read.investigations.list_alerts()[0]
    assert alert.severity == "warning"
    assert "could not read Windows sign-in and security history" in alert.message
    assert "does not establish why" in alert.message
    assert "channel_access_unavailable" not in alert.message
    context = read.investigations.get_alert_context(alert.alert_id)
    assert context.provenance == "exact"
    assert context.event.kind == "coverage_gap"
    assert context.event.data["gaps"] == ["channel_access_unavailable"]
    assert context.event.data["channel"] == "Security"
    read.poll(channels=("Security",))
    assert read.investigations.get_alert_context(alert.alert_id).event.event_id == context.event.event_id


@pytest.mark.parametrize("event_id, channel, expected", [
    (1116, "Microsoft-Windows-Windows Defender/Operational", "recorded a threat detection"),
    (1102, "Security", "Security event log was cleared"),
])
def test_native_event_alert_preserves_finding_and_original_event_context(tmp_path, event_id, channel, expected):
    item = NativeEvent(channel, 1, event_id, utc_now().isoformat(), "Windows", {"Threat Name": "Test threat"})
    read = collector(tmp_path, Source(EventPage((item,), item)))
    read.poll(channels=(channel,))
    alert = read.investigations.list_alerts()[0]
    assert alert.severity == "warning"
    assert expected in alert.message
    context = read.investigations.get_alert_context(alert.alert_id)
    assert context.provenance == "exact"
    assert context.event.data["event_id"] == event_id


def test_reset_reuses_record_number_in_new_epoch_and_retains_gap(tmp_path):
    item = event()
    source = Source(EventPage((item,), item))
    read = collector(tmp_path, source)
    read.poll(channels=("Security",))
    changed = replace(item, occurred_at=utc_now().isoformat(), data={"LogonType": "10"})
    source.page = EventPage((changed,), changed, ("bookmark_reset_or_log_wrap",), reset=True)
    read.poll(channels=("Security",))
    with read.store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM collected_events").fetchone()[0] == 2
        assert connection.execute("SELECT epoch FROM event_bookmarks").fetchone()[0] == 1


def test_cancel_during_native_read_does_not_write_events_or_bookmark(tmp_path):
    item = event(); cancelled = [False]
    class Cancelling(Source):
        def read(self, *args, **kwargs):
            cancelled[0] = True
            return super().read(*args, **kwargs)
    read = collector(tmp_path, Cancelling(EventPage((item,), item)))
    read.poll(channels=("Security",), cancel_check=lambda: cancelled[0])
    assert read.investigations.list_cases() == []


def xml(record_id, *, event_id=4625, at="2026-10-09T10:00:00Z"):
    return f'<Event><System><EventID>{event_id}</EventID><EventRecordID>{record_id}</EventRecordID><TimeCreated SystemTime="{at}"/><Provider Name="test"/></System><EventData><Data Name="LogonType">10</Data><Data Name="Password">never retain</Data></EventData></Event>'


def test_windows_source_queries_forward_after_verified_anchor_and_bounds_output():
    calls = []
    outputs = [xml(5), xml(1), xml(2) + xml(3) + xml(4)]
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=outputs.pop(0))
    source = WindowsEventSource(runner=run, platform_name="nt")
    from aida.aegis.event_evidence import _native_event
    from aida.aegis.remote.windows_sessions import _parse_event_stream
    anchor = _native_event("Security", _parse_event_stream(xml(1))[0])
    page = source.read("Security", {"record_id": 1, "fingerprint": anchor.fingerprint}, limit=2)
    assert [row.record_id for row in page.events] == [2, 3]
    assert page.checkpoint.record_id == 3
    assert page.gaps == ("backfill_page_pending",)
    assert "Password" not in page.events[0].data
    assert "EventRecordID>1" in " ".join(calls[-1][0])
    assert "/rd:false" in calls[-1][0]
    assert all(kwargs["timeout"] == 5 for _, kwargs in calls)


def test_windows_source_denied_or_bad_xml_returns_unknown_not_clean():
    denied = WindowsEventSource(runner=lambda *a, **k: SimpleNamespace(returncode=5, stdout=""), platform_name="nt")
    assert denied.read("Security", None).gaps == ("channel_access_unavailable",)
    broken = WindowsEventSource(runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="<broken>"), platform_name="nt")
    assert broken.read("Security", None).gaps == ("event_parse_failed",)


def test_discarded_window_remains_unknown_after_quiet_poll_and_restart(tmp_path, monkeypatch):
    item = event()
    source = Source(EventPage((item,), item, ("initial_backfill_truncated", "initial_backfill_window_limited")))
    read = collector(tmp_path, source)
    read.poll(channels=("Security",))
    source.page = EventPage((), item)
    restarted = collector(tmp_path, source)
    assert "initial_backfill_truncated" in restarted.recent_remote_logons()[1]
    assert len(restarted.investigations.list_alerts(include_acknowledged=True)) == 1
    later = utc_now() + timedelta(minutes=31)
    monkeypatch.setattr("aida.aegis.event_evidence.utc_now", lambda: later)
    assert "initial_backfill_truncated" not in restarted.recent_remote_logons()[1]


def test_recent_logon_limit_reports_missing_remote_interactive_evidence(tmp_path):
    item = event()
    source = Source(EventPage((), item))
    read = collector(tmp_path, source)
    now = utc_now()
    with read.store.connect(write=True) as connection:
        for index in range(513):
            row = replace(item, record_id=index + 1, occurred_at=(now - timedelta(seconds=513-index)).isoformat(),
                data={"LogonType": "10" if index == 0 else "3"})
            connection.execute("INSERT INTO collected_events VALUES(?,?,?,?,?,?)",
                ("Security", 0, row.record_id, row.occurred_at, row.event_id, json.dumps(row.to_record())))
    events, gaps = read.recent_remote_logons()
    assert len(events) == 512
    assert "recent_logon_window_truncated" in gaps


def test_invalid_event_rolls_back_entire_batch_and_checkpoint(tmp_path):
    item = event()
    invalid = replace(item, record_id=2, channel="wrong")
    read = collector(tmp_path, Source(EventPage((item, invalid), item)))
    with pytest.raises(ValueError):
        read.poll(channels=("Security",))
    with read.store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM event_bookmarks").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM collected_events").fetchone()[0] == 0
    assert read.investigations.list_cases() == []


def test_competing_collector_cannot_replace_newer_checkpoint(tmp_path):
    item = event(1)
    other_item = event(2)
    second = collector(tmp_path, Source(EventPage((other_item,), other_item)))
    class Racing(Source):
        def read(self, *args, **kwargs):
            second.poll(channels=("Security",))
            return super().read(*args, **kwargs)
    first = collector(tmp_path, Racing(EventPage((item,), item)))
    assert first.poll(channels=("Security",))["Security"] == ("bookmark_changed_retry_required",)
    with first.store.connect() as connection:
        assert connection.execute("SELECT record_id FROM event_bookmarks").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM collected_events").fetchone()[0] == 1


def test_cancellation_while_waiting_for_database_lock_cannot_write_afterwards(tmp_path, monkeypatch):
    from contextlib import contextmanager
    item = event()
    read = collector(tmp_path, Source(EventPage((item,), item)))
    cancelled = [False]
    original = read.store.connect
    @contextmanager
    def delayed(*, write=False):
        with original(write=write) as connection:
            if write:
                cancelled[0] = True
            yield connection
    monkeypatch.setattr(read.store, "connect", delayed)
    assert read.poll(channels=("Security",), cancel_check=lambda: cancelled[0])["Security"] == ("collection_cancelled",)
    assert read.investigations.list_cases() == []
