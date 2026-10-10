"""Plain-language descriptions of recorded observations, never new verdicts."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


def _value(record, name, default=None):
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def baseline_observations(delta) -> tuple[str, ...]:
    """Accept a live BaselineDelta or its saved dictionary representation."""
    available = _value(delta, "baseline_available")
    if available is False:
        return ("At the time of this check, AIDA did not have an approved saved comparison of this computer's programs and settings (a baseline). That comparison could not be used to identify changes.",)
    if available is not True:
        return ("This saved record does not say whether AIDA had an approved saved comparison of this computer's programs and settings (a baseline). Its comparison status is unknown.",)
    changes = []
    unknown_categories = []
    for field, description in (
        ("new_process_paths", "program file(s) running at the time of that check that were not running in the saved comparison"),
        ("removed_process_paths", "program file(s) seen running in the saved comparison but not in this check"),
        ("new_persistence", "automatic-start entry or entries present at the time of that check but not in the saved comparison"),
        ("removed_persistence", "automatic-start entry or entries seen in the saved comparison but not in this check"),
        ("new_listeners", "network address(es) where programs accepted connections at the time of that check but not in the saved comparison"),
        ("removed_listeners", "network address(es) where programs accepted connections in the saved comparison but not in this check"),
    ):
        entries = _value(delta, field)
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            category = "running programs" if "process" in field else "automatic-start entries" if "persistence" in field else "network addresses where programs accept connections"
            unknown_categories.append(category)
            continue
        count = len(entries)
        if count:
            changes.append(f"{count} {description}")
    unknown = ("The saved comparison details are missing or unreadable for " + ", ".join(dict.fromkeys(unknown_categories))
        + ". Those comparison results are unknown.") if unknown_categories else ""
    if not changes:
        return (unknown,) if unknown else ("At the time of that check, the running programs, automatic-start entries and network addresses where programs accepted connections matched the approved saved comparison of this computer's programs and settings (a baseline).",)
    notes = ["Using the approved saved comparison of this computer's programs and settings (a baseline), AIDA recorded: " + "; ".join(changes) + ".",
        "A difference does not identify its cause: normal program use, installations and updates can also change these records."]
    if unknown:
        notes.append(unknown)
    return tuple(notes)


def explain_event_gaps(channel: str, gaps: Iterable[str] | None) -> str:
    if gaps is None:
        return "The saved record does not include details about this event-history check. Its completion and limitations are unknown."
    history = {"Security": "Windows sign-in and security history",
        "Microsoft-Windows-Windows Defender/Operational": "Microsoft Defender's event history"}.get(channel, "the requested Windows event history")
    descriptions = {
        "channel_access_unavailable": f"AIDA could not read {history}. The saved result does not establish why the read failed.",
        "platform_unsupported": "This event-history check is available only on Windows; it did not run on this system.",
        "channel_empty": f"The request returned no entries from {history}. That does not establish whether relevant events were recorded or retained.",
        "event_parse_failed": f"AIDA received a result for {history} but could not interpret it reliably.",
        "bookmark_reset_or_log_wrap": f"AIDA could not continue from its saved position in {history}. Older records may have been cleared or replaced; the reason is not established.",
        "initial_backfill_window_limited": f"The first check of {history} was limited to the last 24 hours; earlier history was not reviewed.",
        "initial_backfill_truncated": f"There were more entries in {history} than this check could read. Some earlier entries in the time window were not reviewed.",
        "backfill_page_pending": f"AIDA has more entries in {history} left to read. This review is not complete yet.",
        "recent_event_cache_evicted": "AIDA keeps a limited copy of event history for these checks. Some recent records fell outside that copy, so the recent-history review is incomplete.",
        "recent_logon_window_truncated": "There were more recent sign-in records than AIDA could examine in one check, so some sign-in activity has not been reviewed.",
        "collection_already_running": "Another event-history check was already running. This request did not complete a fresh check.",
        "collection_cancelled": "The event-history check stopped before it completed.",
        "collection_unavailable": "AIDA did not receive a completed event-history check.",
        "bookmark_changed_retry_required": "Another check advanced the saved event-history position. This check must be retried before its result can be used.",
    }
    messages = [descriptions.get(str(gap), "AIDA recorded an event-history limitation whose meaning is not available in this version.") for gap in dict.fromkeys(gaps)]
    if not messages:
        return "No event-history limitation was supplied to this explanation; this is not a new security check."
    return " ".join(dict.fromkeys(messages)) + " An incomplete check does not by itself confirm a threat or show that the computer is safe."


def explain_windows_event(event_id: int, data: Mapping | None = None) -> str:
    if event_id == 1116:
        name = " ".join(str((data or {}).get("Threat Name", "")).split())[:160]
        finding = f" ({name})" if name else ""
        return (f"Microsoft Defender recorded a threat detection{finding}. This event alone does not establish whether the threat is still active or has already been handled. Review the current antivirus findings.")
    if event_id == 1102:
        return ("Windows recorded that its Security event log was cleared. Earlier sign-in and security history may no longer be available. This record alone does not establish who cleared it or why.")
    return f"Windows recorded event {event_id}. Its meaning and current relevance need review."


def explain_sensor_limitations(errors: Iterable[str]) -> tuple[str, ...]:
    descriptions = {
        "No antivirus-provider detection was linked to this analysis snapshot.": "This file review was not matched to an antivirus detection. That does not mean the file is safe.",
        "No deterministic static suspicion indicator was observed.": "The recorded file checks did not flag a suspicious feature. Those checks cannot establish that the file is safe.",
        "Read-only analysis cannot prove runtime behavior that was not directly observed.": "This review does not establish everything the program does when it runs.",
        "network_connection_limit_reached": "AIDA reached the connection limit for this check, so some network activity was not reviewed.",
        "network_snapshot_unavailable": "AIDA could not complete the network-connection check.",
        "process_snapshot_limit_reached": "AIDA reached the program limit for this check, so some running programs were not reviewed.",
        "process_identity_partially_unavailable": "AIDA could not identify every running program reliably; some program details remain unknown.",
        "process_snapshot_unavailable": "AIDA could not complete the running-program check.",
        "provider_health_unavailable": "AIDA could not verify the antivirus protection status.",
        "security_provider_unavailable": "AIDA could not obtain current information from the antivirus provider.",
        "registry_persistence_unavailable": "AIDA could not read the Windows settings checked for automatic program startup.",
        "user_startup_unavailable": "AIDA could not read this user's automatic-start folder.",
        "machine_startup_unavailable": "AIDA could not read the computer's shared automatic-start folder.",
    }
    notes = []
    event_groups: dict[str, list[str]] = {}
    for error in dict.fromkeys(errors):
        legacy_prefix = "One or more read-only security sensors returned incomplete coverage: "
        if error.startswith(legacy_prefix):
            notes.extend(explain_sensor_limitations(item.strip() for item in error[len(legacy_prefix):].split(",") if item.strip()))
            continue
        if error.startswith("No established Aegis machine baseline"):
            notes.append(baseline_observations({"baseline_available": False})[0])
            continue
        if error == "The assessment describes evidence observable during this scan and does not prove that no hidden threat exists.":
            notes.append("This review covers only what AIDA could observe during the check; it cannot rule out every threat.")
            continue
        if error.startswith("event_evidence:") and ":" in error[len("event_evidence:"):]:
            channel, gap = error[len("event_evidence:"):].rsplit(":", 1)
            event_groups.setdefault(channel, []).append(gap)
        else:
            # Existing file-analysis uncertainty can already be useful prose.
            # Preserve it rather than replacing actual evidence with a guess.
            notes.append(descriptions.get(error, error if any(character.isspace() for character in error)
                else "AIDA recorded a check it could not complete or fully interpret. Review its technical details before relying on the result."))
    notes.extend(explain_event_gaps(channel, gaps) for channel, gaps in event_groups.items())
    return tuple(dict.fromkeys(notes))
