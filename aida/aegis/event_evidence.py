"""Bounded, read-only Windows event collection with transactional bookmarks.

The collector never changes audit policy or requests elevation. Missing access,
log reset/wrap, initial backfill limits and pending pages are evidence gaps.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from aida.investigations.service import _append, _alert, _end_episode, _get_case, _save_case
from aida.investigations.models import InvestigationCase, utc_now
from aida.investigations.store import encode
from aida.aegis.remote.windows_sessions import _parse_event_stream, _child, _local_name
from aida.aegis.remote.models import RemoteLogonEvent


CHANNELS = {"Security": (4624, 4625, 1102), "Microsoft-Windows-Windows Defender/Operational": (1000, 1001, 1002, 1116, 1117, 5007)}


@dataclass(frozen=True, slots=True)
class NativeEvent:
    channel: str
    record_id: int
    event_id: int
    occurred_at: str
    provider: str
    data: dict[str, str]

    def to_record(self):
        return {"channel": self.channel, "record_id": self.record_id, "event_id": self.event_id,
            "occurred_at": self.occurred_at, "provider": self.provider, "data": self.data}

    @property
    def fingerprint(self):
        return hashlib.sha256(encode(self.to_record()).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[NativeEvent, ...]
    checkpoint: NativeEvent | None
    gaps: tuple[str, ...] = ()
    reset: bool = False


class WindowsEventSource:
    def __init__(self, *, runner=None, platform_name: str | None = None):
        self.runner = runner or subprocess.run
        self.platform = platform_name or os.name

    def read(self, channel: str, bookmark: dict | None, *, limit: int = 128) -> EventPage:
        if channel not in CHANNELS:
            raise ValueError("Unsupported evidence event channel.")
        if self.platform != "nt":
            return EventPage((), None, ("platform_unsupported",))
        limit = max(1, min(int(limit), 256))
        try:
            latest = self._query(channel, "*", count=1, newest=True)
            if not latest:
                return EventPage((), None, ("channel_empty",), reset=bookmark is not None)
            newest = latest[0]
            reset = False
            gaps = []
            cursor = int(bookmark["record_id"]) if bookmark else 0
            if bookmark:
                anchor = self._query(channel, f"*[System[EventRecordID={cursor}]]", count=1)
                if newest.record_id < cursor or not anchor or anchor[0].fingerprint != bookmark["fingerprint"]:
                    reset, cursor = True, 0
                    gaps.append("bookmark_reset_or_log_wrap")
            ids = " or ".join(f"EventID={event_id}" for event_id in CHANNELS[channel])
            if cursor:
                query = f"*[System[({ids}) and EventRecordID>{cursor}]]"
                rows = self._query(channel, query, count=limit + 1)
            else:
                # Initial enrollment/reset is bounded to one day and newest page.
                query = f"*[System[({ids}) and TimeCreated[timediff(@SystemTime)<=86400000]]]"
                rows = self._query(channel, query, count=limit + 1, newest=True)
                gaps.append("initial_backfill_window_limited")
            truncated = len(rows) > limit
            if truncated:
                gaps.append("backfill_page_pending" if cursor else "initial_backfill_truncated")
            selected = tuple(sorted(rows[:limit], key=lambda row: row.record_id))
            checkpoint = selected[-1] if truncated and cursor else max((newest, *selected), key=lambda row: row.record_id)
            return EventPage(selected, checkpoint, tuple(gaps), reset)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            return EventPage((), None, ("channel_access_unavailable",))
        except (ValueError, TypeError, KeyError, ET.ParseError):
            return EventPage((), None, ("event_parse_failed",))

    def _query(self, channel, query, *, count, newest=False):
        completed = self.runner(["wevtutil.exe", "qe", channel, "/q:" + query, "/f:xml", f"/c:{count}", "/rd:" + ("true" if newest else "false")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        if completed.returncode:
            raise RuntimeError("Event log unavailable.")
        if len(completed.stdout.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("Event output exceeds its bounded collection limit.")
        return tuple(_native_event(channel, event) for event in _parse_event_stream(completed.stdout))


class IncrementalEventCollector:
    def __init__(self, investigations, *, source=None):
        self.investigations = investigations
        self.store = investigations.store
        self.source = source or WindowsEventSource()
        self._lock = threading.Lock()

    def poll(self, *, channels=None, cancel_check=None) -> dict[str, tuple[str, ...]]:
        if not self._lock.acquire(blocking=False):
            return {"collector": ("collection_already_running",)}
        try:
            results = {}
            for channel in channels or tuple(CHANNELS):
                if cancel_check and cancel_check():
                    break
                try:
                    results[channel] = self._poll_channel(channel, cancel_check=cancel_check)
                except _CollectionCancelled:
                    results[channel] = ("collection_cancelled",)
                    break
            with self.store.connect() as connection:
                for row in connection.execute("SELECT channel,gaps FROM event_coverage WHERE uncertain_until>?", (utc_now().isoformat(),)):
                    if row["channel"] in results:
                        results[row["channel"]] = tuple(dict.fromkeys(results[row["channel"]] + tuple(json.loads(row["gaps"]))))
            return results
        finally:
            self._lock.release()

    def _poll_channel(self, channel, *, cancel_check=None):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM event_bookmarks WHERE channel=?", (channel,)).fetchone()
            previous = dict(row) if row else None
        page = self.source.read(channel, previous, limit=128)
        if cancel_check and cancel_check():
            return ("collection_cancelled",)
        alerts = []
        with _collection_transaction(self.store, cancel_check) as connection:
            row = connection.execute("SELECT * FROM event_bookmarks WHERE channel=?", (channel,)).fetchone()
            if (dict(row) if row else None) != previous:
                return ("bookmark_changed_retry_required",)
            now = utc_now().isoformat()
            epoch = (previous["epoch"] if previous else 0) + int(page.reset)
            case_id = "CASE-EVENTS-" + hashlib.sha256(channel.encode()).hexdigest()[:16]
            case = _get_case(connection, case_id)
            if case is None:
                case = InvestigationCase(case_id, "Windows event evidence: " + channel, "review_required", now, now,
                    "event_channel", channel, "local-evidence", "Incremental event evidence; current state needs independent verification.", 1)
                _save_case(connection, case)
            for event in page.events:
                if event.channel != channel or event.record_id <= 0 or event.event_id not in CHANNELS[channel]:
                    raise ValueError("Event identity does not match its permitted channel.")
                reference = f"{channel}:{epoch}:{event.record_id}"
                inserted = connection.execute("INSERT OR IGNORE INTO collected_events VALUES(?,?,?,?,?,?)",
                    (channel, epoch, event.record_id, event.occurred_at, event.event_id, encode(event.to_record()))).rowcount
                if inserted:
                    _append(connection, case_id, "windows_event", f"Windows event {event.event_id} observed in {channel}.", reference,
                        "observed", event.to_record(), event.occurred_at)
                if inserted and event.event_id in {1116, 1102}:
                    alert = _alert(connection, "event:" + channel, case_id, reference, "warning",
                        "Provider threat evidence was recorded; review current findings." if event.event_id == 1116 else "The Windows security log was cleared; review the evidence gap.")
                    if alert:
                        alerts.append(alert)
            irreversible = tuple(gap for gap in page.gaps if gap in {"initial_backfill_truncated", "bookmark_reset_or_log_wrap"})
            if irreversible:
                _retain_coverage_gap(connection, channel, irreversible, utc_now() + timedelta(minutes=30))
            evicted = connection.execute("SELECT channel,MAX(occurred_at) AS newest FROM (SELECT channel,occurred_at FROM collected_events ORDER BY occurred_at DESC LIMIT -1 OFFSET 10000) GROUP BY channel").fetchall()
            for discarded in evicted:
                until = datetime.fromisoformat(discarded["newest"]) + timedelta(minutes=30)
                if until > utc_now():
                    _retain_coverage_gap(connection, discarded["channel"], ("recent_event_cache_evicted",), until)
            connection.execute("DELETE FROM collected_events WHERE rowid IN (SELECT rowid FROM collected_events ORDER BY occurred_at DESC LIMIT -1 OFFSET 10000)")
            retained = connection.execute("SELECT * FROM event_coverage WHERE channel=? AND uncertain_until>?", (channel, now)).fetchone()
            gaps = tuple(dict.fromkeys(page.gaps + (tuple(json.loads(retained["gaps"])) if retained else ())))
            if gaps:
                signature = "|".join(sorted(gap for gap in gaps if gap not in {"initial_backfill_window_limited", "backfill_page_pending"})) or "bounded_backfill"
                episode = connection.execute("SELECT signature FROM security_episodes WHERE channel=? AND active=1", ("coverage:" + channel,)).fetchone()
                if episode is None or episode[0] != signature:
                    _append(connection, case_id, "coverage_gap", "Event coverage: " + ", ".join(gaps),
                        f"gap:{channel}:{epoch}:" + hashlib.sha256((signature + now).encode()).hexdigest()[:16], "incomplete", {"gaps": list(gaps)})
                alert = _alert(connection, "coverage:" + channel, case_id, signature, "warning", "Event evidence is incomplete: " + ", ".join(gaps),
                    notify=any(gap not in {"initial_backfill_window_limited", "backfill_page_pending"} for gap in gaps))
                if alert:
                    alerts.append(alert)
            else:
                _end_episode(connection, "coverage:" + channel)
            if page.checkpoint is not None:
                checkpoint = page.checkpoint
                connection.execute("INSERT INTO event_bookmarks VALUES(?,?,?,?,?) ON CONFLICT(channel) DO UPDATE SET epoch=excluded.epoch,record_id=excluded.record_id,observed_at=excluded.observed_at,fingerprint=excluded.fingerprint",
                    (channel, epoch, checkpoint.record_id, checkpoint.occurred_at, checkpoint.fingerprint))
        for alert in alerts:
            self.investigations._notify(alert)
        return gaps

    def recent_remote_logons(self, *, cancel_check=None):
        result = self.poll(channels=("Security",), cancel_check=cancel_check)
        gaps = result.get("Security", result.get("collector", ("collection_unavailable",)))
        since = (utc_now() - timedelta(minutes=30)).isoformat()
        with self.store.connect() as connection:
            rows = connection.execute("SELECT payload FROM collected_events WHERE channel='Security' AND occurred_at>=? AND event_id IN (4624,4625) ORDER BY occurred_at DESC LIMIT 513", (since,)).fetchall()
            retained = connection.execute("SELECT gaps FROM event_coverage WHERE channel='Security' AND uncertain_until>?", (utc_now().isoformat(),)).fetchone()
            if retained:
                gaps = tuple(dict.fromkeys(gaps + tuple(json.loads(retained[0]))))
        if len(rows) > 512:
            gaps += ("recent_logon_window_truncated",)
        events = []
        for row in rows[:512]:
            record = json.loads(row[0]); data = record["data"]
            kind = data.get("LogonType", "")
            if kind not in {"3", "10", "12"}:
                continue
            user, domain = data.get("TargetUserName", ""), data.get("TargetDomainName", "")
            events.append(RemoteLogonEvent(record["event_id"], datetime.fromisoformat(record["occurred_at"]), int(kind),
                domain + "\\" + user if domain and user else user or domain, data.get("IpAddress", ""), data.get("IpPort", ""), record["event_id"] == 4624))
        return tuple(events), tuple(gap for gap in gaps if gap != "initial_backfill_window_limited")


def _retain_coverage_gap(connection, channel, gaps, until):
    current = connection.execute("SELECT * FROM event_coverage WHERE channel=?", (channel,)).fetchone()
    active = current is not None and current["uncertain_until"] > utc_now().isoformat()
    previous = tuple(json.loads(current["gaps"])) if active else ()
    deadline = max(until.isoformat(), current["uncertain_until"]) if active else until.isoformat()
    connection.execute("INSERT INTO event_coverage VALUES(?,?,?) ON CONFLICT(channel) DO UPDATE SET uncertain_until=excluded.uncertain_until,gaps=excluded.gaps",
        (channel, deadline, json.dumps(sorted(set(previous + tuple(gaps))))))


class _CollectionCancelled(Exception):
    pass


@contextmanager
def _collection_transaction(store, cancel_check):
    with store.connect(write=True) as connection:
        if cancel_check and cancel_check():
            raise _CollectionCancelled()
        yield connection
        if cancel_check and cancel_check():
            raise _CollectionCancelled()


def _native_event(channel, event):
    system = _child(event, "System")
    if system is None:
        raise ValueError("Event system identity is absent.")
    record = _child(system, "EventRecordID"); event_id = _child(system, "EventID")
    timestamp = _child(system, "TimeCreated"); provider = _child(system, "Provider")
    if record is None or event_id is None or timestamp is None:
        raise ValueError("Event record identity is incomplete.")
    created = datetime.fromisoformat(timestamp.attrib["SystemTime"].replace("Z", "+00:00"))
    if created.tzinfo is None:
        raise ValueError("Event timestamp lacks its timezone.")
    data_node = _child(event, "EventData")
    data = {}
    if data_node is not None:
        for item in list(data_node)[:64]:
            if _local_name(item.tag) == "Data" and str(item.attrib.get("Name", "")) in {
                "LogonType", "TargetUserName", "TargetDomainName", "IpAddress", "IpPort",
                "Threat Name", "Threat ID", "Path", "Process Name", "Detection ID", "Scan ID", "Scan Parameters",
            }:
                data[str(item.attrib.get("Name", ""))[:160]] = str(item.text or "")[:4000]
    return NativeEvent(channel, int(record.text), int(event_id.text), created.astimezone(timezone.utc).isoformat(),
        str(provider.attrib.get("Name", "")) if provider is not None else "unknown", data)
