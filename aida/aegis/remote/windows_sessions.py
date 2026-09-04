from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import xml.etree.ElementTree as ET
from ctypes import wintypes
from datetime import datetime, timezone

from aida.aegis.remote.models import RemoteLogonEvent, RemoteSessionEvidence


_WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
_WTS_INFO_USERNAME = 5
_WTS_INFO_DOMAIN = 7
_WTS_INFO_CLIENT_NAME = 10
_WTS_INFO_CLIENT_ADDRESS = 14
_WTS_INFO_PROTOCOL = 16

_STATE_NAMES = {
    0: "active",
    1: "connected",
    2: "connect_query",
    3: "shadow",
    4: "disconnected",
    5: "idle",
    6: "listen",
    7: "reset",
    8: "down",
    9: "init",
}


class _WTS_SESSION_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


class _WTS_CLIENT_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("AddressFamily", wintypes.DWORD),
        ("Address", ctypes.c_ubyte * 20),
    ]


def enumerate_remote_desktop_sessions() -> tuple[tuple[RemoteSessionEvidence, ...], tuple[str, ...]]:
    """Enumerate local Windows RDS/RDP sessions through WTS APIs.

    WTS protocol type 2 identifies RDP. Console sessions are deliberately
    excluded. Query failures are returned as degraded evidence rather than
    being interpreted as proof that no remote session exists.
    """

    if os.name != "nt":
        return (), ()

    errors: list[str] = []
    sessions: list[RemoteSessionEvidence] = []
    try:
        wts = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
    except OSError:
        return (), ("wts_api_unavailable",)

    wts.WTSEnumerateSessionsW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_WTS_SESSION_INFOW)),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wts.WTSEnumerateSessionsW.restype = wintypes.BOOL
    wts.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    wts.WTSFreeMemory.restype = None

    pointer = ctypes.POINTER(_WTS_SESSION_INFOW)()
    count = wintypes.DWORD(0)
    if not wts.WTSEnumerateSessionsW(
        _WTS_CURRENT_SERVER_HANDLE,
        0,
        1,
        ctypes.byref(pointer),
        ctypes.byref(count),
    ):
        return (), ("wts_session_enumeration_unavailable",)

    try:
        for index in range(int(count.value)):
            row = pointer[index]
            session_id = int(row.SessionId)
            protocol = _query_protocol(wts, session_id)
            if protocol != 2:
                continue
            username = _query_string(wts, session_id, _WTS_INFO_USERNAME)
            domain = _query_string(wts, session_id, _WTS_INFO_DOMAIN)
            client_name = _query_string(wts, session_id, _WTS_INFO_CLIENT_NAME)
            client_address = _query_client_address(wts, session_id)
            sessions.append(
                RemoteSessionEvidence(
                    session_id=session_id,
                    username=username,
                    domain=domain,
                    state=_STATE_NAMES.get(int(row.State), f"state_{int(row.State)}"),
                    protocol_type=protocol,
                    client_address=client_address,
                    client_name=client_name,
                )
            )
    except (OSError, ValueError, TypeError):
        errors.append("wts_session_query_partial")
    finally:
        if pointer:
            wts.WTSFreeMemory(pointer)

    return tuple(sessions), tuple(dict.fromkeys(errors))


def logoff_remote_desktop_session(session_id: int) -> bool:
    """Log off one exact RDS session.

    The caller must perform authorization and identity revalidation first.
    Windows requires Reset permission to log off another user's session.
    """

    if os.name != "nt" or session_id < 0:
        return False
    try:
        wts = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
    except OSError:
        return False
    wts.WTSLogoffSession.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    wts.WTSLogoffSession.restype = wintypes.BOOL
    return bool(
        wts.WTSLogoffSession(
            _WTS_CURRENT_SERVER_HANDLE,
            wintypes.DWORD(session_id),
            False,
        )
    )


def read_recent_remote_logons(
    *,
    lookback_minutes: int = 30,
    max_events: int = 96,
) -> tuple[tuple[RemoteLogonEvent, ...], tuple[str, ...]]:
    """Read recent Windows Security 4624/4625 remote-logon evidence.

    Logon type 10 is RemoteInteractive/RDP. Type 3 is a network logon and is
    intentionally treated as weaker evidence because normal SMB/service access
    can also generate it. Security-log access may require elevated/event-log
    permissions; failure lowers coverage instead of producing a clean verdict.
    """

    if os.name != "nt":
        return (), ()
    milliseconds = max(1, min(int(lookback_minutes), 24 * 60)) * 60 * 1000
    count = max(1, min(int(max_events), 512))
    query = (
        "*[System[((EventID=4624) or (EventID=4625)) and "
        f"TimeCreated[timediff(@SystemTime) <= {milliseconds}]]]"
    )
    command = [
        "wevtutil.exe",
        "qe",
        "Security",
        f"/q:{query}",
        "/f:xml",
        f"/c:{count}",
        "/rd:true",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired):
        return (), ("security_log_remote_logon_query_unavailable",)
    if completed.returncode != 0:
        return (), ("security_log_remote_logon_access_unavailable",)

    events: list[RemoteLogonEvent] = []
    try:
        root = _parse_event_stream(completed.stdout)
        for event in root:
            parsed = _parse_logon_event(event)
            if parsed is not None and parsed.logon_type in {3, 10, 12}:
                events.append(parsed)
    except (ET.ParseError, ValueError, TypeError):
        return (), ("security_log_remote_logon_parse_failed",)
    return tuple(events), ()


def _query_string(wts: object, session_id: int, info_class: int) -> str:
    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD(0)
    if not wts.WTSQuerySessionInformationW(
        _WTS_CURRENT_SERVER_HANDLE,
        wintypes.DWORD(session_id),
        info_class,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        return ""
    try:
        return str(buffer.value or "")
    finally:
        if buffer:
            wts.WTSFreeMemory(buffer)


def _query_protocol(wts: object, session_id: int) -> int:
    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD(0)
    if not wts.WTSQuerySessionInformationW(
        _WTS_CURRENT_SERVER_HANDLE,
        wintypes.DWORD(session_id),
        _WTS_INFO_PROTOCOL,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        return -1
    try:
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))
        return int(pointer.contents.value)
    except (ValueError, TypeError):
        return -1
    finally:
        if buffer:
            wts.WTSFreeMemory(buffer)


def _query_client_address(wts: object, session_id: int) -> str:
    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD(0)
    if not wts.WTSQuerySessionInformationW(
        _WTS_CURRENT_SERVER_HANDLE,
        wintypes.DWORD(session_id),
        _WTS_INFO_CLIENT_ADDRESS,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        return ""
    try:
        address = ctypes.cast(buffer, ctypes.POINTER(_WTS_CLIENT_ADDRESS)).contents
        raw = bytes(address.Address)
        if int(address.AddressFamily) == socket.AF_INET:
            return socket.inet_ntop(socket.AF_INET, raw[2:6])
        if int(address.AddressFamily) == socket.AF_INET6:
            return socket.inet_ntop(socket.AF_INET6, raw[2:18])
        return ""
    except (OSError, ValueError, TypeError):
        return ""
    finally:
        if buffer:
            wts.WTSFreeMemory(buffer)


def _parse_event_stream(raw: str) -> ET.Element:
    text = raw.strip()
    if not text:
        return ET.Element("Events")
    text = text.replace("<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\"?>", "")
    text = text.replace("<?xml version=\"1.0\" encoding=\"utf-8\"?>", "")
    if text.startswith("<Events"):
        return ET.fromstring(text)
    return ET.fromstring(f"<Events>{text}</Events>")


def _parse_logon_event(event: ET.Element) -> RemoteLogonEvent | None:
    system = _child(event, "System")
    event_data = _child(event, "EventData")
    if system is None or event_data is None:
        return None
    event_id_node = _child(system, "EventID")
    if event_id_node is None or not (event_id_node.text or "").strip():
        return None
    event_id = int((event_id_node.text or "0").strip())
    data = {
        str(node.attrib.get("Name") or ""): str(node.text or "")
        for node in event_data
        if _local_name(node.tag) == "Data"
    }
    logon_text = data.get("LogonType", "").strip()
    logon_type = int(logon_text) if logon_text.isdigit() else None
    user = data.get("TargetUserName", "").strip()
    domain = data.get("TargetDomainName", "").strip()
    account = f"{domain}\\{user}" if domain and user else user or domain
    time_node = next(
        (child for child in system if _local_name(child.tag) == "TimeCreated"),
        None,
    )
    timestamp = _parse_time(
        str(time_node.attrib.get("SystemTime") or "") if time_node is not None else ""
    )
    return RemoteLogonEvent(
        event_id=event_id,
        observed_at=timestamp,
        logon_type=logon_type,
        account=account,
        source_address=data.get("IpAddress", "").strip(),
        source_port=data.get("IpPort", "").strip(),
        success=(event_id == 4624),
    )


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    return next(
        (child for child in parent if _local_name(child.tag) == name),
        None,
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_time(value: str) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
