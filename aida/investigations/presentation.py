"""Plain-language views of recorded evidence; never a new security verdict."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Explanation:
    title: str
    observations: tuple[str, ...]
    meaning: str
    next_steps: tuple[str, ...]
    limitations: tuple[str, ...] = ()


def readable_time(value: str | None) -> str:
    if not value:
        return "Not recorded"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "Time zone not recorded"
        return stamp.astimezone().strftime("%b %d, %Y at %I:%M:%S %p %Z")
    except (ValueError, TypeError):
        return "Time unavailable"


def load_alert_context(service, alert):
    try:
        return service.get_alert_context(alert.alert_id)
    except Exception as exc:
        logging.getLogger(__name__).debug("Alert evidence lookup unavailable: %s", type(exc).__name__)
        return None


def explain_event(event, *, severity: str = "warning") -> Explanation:
    # Lazy import avoids the Aegis engine's investigation-service import cycle.
    from aida.aegis.explanations import baseline_observations, explain_event_gaps, explain_sensor_limitations

    if event is None:
        result = Explanation("Supporting details unavailable",
            ("AIDA saved a notice, but could not match it to its original supporting observation.",),
            "This notice alone cannot establish what happened or whether the computer is at risk.",
            ("Review the case and collect a fresh security assessment before choosing a response.",),
            ("Missing details do not mean that a check passed or that the computer is safe.",))
    else:
        data = event.data if isinstance(event.data, dict) else {}
        if event.kind == "coverage_gap":
            channel = data.get("channel") or _channel_from_reference(event.source_reference)
            gaps = _strings(data.get("gaps"))
            result = Explanation("Check incomplete",
                (explain_event_gaps(channel, gaps) if gaps else
                 "The saved record says an event-history check was incomplete, but does not include the reason.",),
                "This notice is about a check AIDA could not complete. It is not a malware detection; AIDA has an incomplete view of this part of the computer's security history.",
                ("Review the other available security results. Retry this check later; if access remains unavailable, ask the person who manages this computer to check log access.",),
                ("AIDA cannot use an unreadable or incomplete history to rule out a problem.",))
        elif event.kind == "aegis_assessment":
            result = _explain_aegis(data, baseline_observations, explain_sensor_limitations)
        elif event.kind == "remote_assessment":
            result = _explain_remote(data, explain_sensor_limitations)
        elif event.kind == "windows_event" and data.get("event_id") == 1116:
            result = Explanation("Antivirus recorded a detection",
                ("Microsoft Defender recorded a threat detection in its event history.",),
                "This is a recorded detection. The event alone does not show whether the item is still active or has already been handled.",
                ("Open Windows Security → Virus & threat protection → Protection history and review the matching item and its current status.",),
                ("AIDA has not confirmed the current outcome from this event alone.",))
        elif event.kind == "windows_event" and data.get("event_id") == 1102:
            result = Explanation("Security history was cleared",
                ("Windows recorded that its Security event log was cleared.",),
                "Some past activity may no longer be available to review. This can be an administrative action; the event alone does not identify why it happened.",
                ("Check whether you or your administrator cleared the log. If it was unexpected, review the case and run a fresh security check.",))
        else:
            result = Explanation("Security observation to review", (event.summary or "No explanation was recorded.",),
                "This is a saved observation. Review its source and any incomplete checks before drawing a conclusion.",
                ("Open the related case to review the available evidence.",))
    if severity in {"critical", "high"}:
        # Incomplete presentation must never hide an existing urgent classification.
        result = Explanation("Urgent review: " + result.title[:1].lower() + result.title[1:],
            result.observations, result.meaning,
            ("Review this notice promptly; AIDA recorded it at high priority.",) + result.next_steps,
            result.limitations)
    return result


def _explain_aegis(data, baseline_observations, explain_sensor_limitations) -> Explanation:
    count = data.get("provider_detection_count")
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    raw_nodes = data.get("evidence_nodes")
    nodes = [node for node in raw_nodes if isinstance(node, dict)] if isinstance(raw_nodes, (list, tuple)) else []
    files = [node for node in nodes if node.get("kind") == "file" and isinstance(node.get("attributes"), dict) and "assessment" in node["attributes"]]
    concerning = [node for node in files if node["attributes"]["assessment"] in {
        "suspicious", "likely_malicious", "provider_confirmed_malicious"}]
    confirmed = [node for node in files if node["attributes"]["assessment"] == "provider_confirmed_malicious"]
    observations, limitations = [], []
    if isinstance(count, int) and count > 0:
        observations.append(f"The antivirus report contained {count} {'detection' if count == 1 else 'detections'}.")
        names = [node.get("label", "Unnamed detection") for node in nodes if node.get("kind") == "provider_detection"]
        observations.extend("Reported detection: " + str(name or "Unnamed detection") for name in names[:5])
    elif count == 0:
        observations.append("No antivirus detections were recorded in this assessment.")
        if not isinstance(coverage.get("provider"), (int, float)) or coverage["provider"] < 1:
            limitations.append("Antivirus availability and health were not fully verified. A zero count is not an all-clear.")
    else:
        observations.append("An antivirus detection result was not recorded.")
    analyzed = data.get("analyzed_file_count")
    if isinstance(analyzed, int):
        observations.append(f"AIDA recorded {analyzed} {'file review' if analyzed == 1 else 'file reviews'}." if analyzed else "No files were individually reviewed in this assessment.")
    labels = {"low_concern": "lower concern in this local review", "suspicious": "needs further investigation",
        "likely_malicious": "likely harmful according to the local review", "provider_confirmed_malicious": "matched an antivirus detection",
        "unknown": "not enough information to assess this file", "insufficient_evidence": "not enough information for a conclusion"}
    for node in (concerning or files)[:5]:
        observations.append(f"{node.get('label') or 'Unnamed file'}: {labels.get(node['attributes']['assessment'], 'result needs review')}.")
    if len(files) > 5:
        observations.append("Additional file results are available in the case details.")
    running = sum(bool(node["attributes"].get("running_processes")) for node in files)
    startup = sum(bool(node["attributes"].get("persistence_references")) for node in files)
    if running or startup:
        observations.append(f"Among the reviewed files, {running} were linked to running programs and {startup} to automatic-start entries.")
    delta = data.get("baseline_delta") if isinstance(data.get("baseline_delta"), dict) else {}
    observations.extend(baseline_observations(delta))
    # Do not mistake a baseline's absence, routine running programs, or a numeric
    # risk score for observed malicious behavior.
    changes = sum(len(delta[key]) if isinstance(delta.get(key), (list, tuple)) else 0 for key in (
        "new_process_paths", "removed_process_paths", "new_persistence", "removed_persistence", "new_listeners", "removed_listeners")) if delta.get("baseline_available") else 0
    if (isinstance(count, int) and count > 0) or confirmed:
        title, meaning = "Antivirus findings need review", "An antivirus detection is recorded. Review its current status to learn whether it still needs a response."
        steps = ("Review the reported item in Windows Security → Virus & threat protection → Protection history, then choose a supported response if it is still needed.",)
    elif concerning:
        title, meaning = "File findings need review", "AIDA found reasons to investigate the listed files. A local assessment alone does not confirm an infection."
        steps = ("Review the named files and their evidence in the case. Use a fresh antivirus check to help confirm the findings before changing or removing anything.",)
    elif changes:
        title, meaning = "Computer changes need review", "These observations differ from an earlier saved comparison. Installing software or changing settings can also produce these differences."
        steps = ("Check whether the listed changes match an installation or update you expected. Review unexpected changes with a fresh security assessment.",)
    else:
        title, meaning = "Security review needs context", "AIDA's combined assessment requested a review, but the recorded file results do not identify a confirmed threat. Running programs, startup entries and network connections can be normal; their presence alone does not show that they are harmful."
        steps = ("Review the file results and incomplete checks below. A fresh security assessment can provide more information; this notice alone is not a reason to remove a file.",)
    if any(node.get("kind") == "file" and not isinstance(node.get("attributes"), dict) for node in nodes):
        limitations.append("Some saved file details are unavailable; AIDA cannot reconstruct those results from this notice.")
    raw_limits = _strings(data.get("remaining_uncertainty"))
    if raw_limits:
        limitations.extend(item for item in explain_sensor_limitations(raw_limits) if item not in observations)
    if data.get("learning_warmup"):
        limitations.append("At the time of this check, AIDA had not yet collected enough observations to learn this computer's usual activity.")
    limitations.append("These results describe the recorded check, not a guarantee about the computer's current safety.")
    return Explanation(title, tuple(observations), meaning, steps, tuple(dict.fromkeys(limitations)))


def _explain_remote(data, explain_sensor_limitations) -> Explanation:
    classification = data.get("classification", "unknown")
    sessions, tools = data.get("active_sessions"), data.get("remote_tools")
    observations = (f"Recorded remote sessions: {len(sessions)}." if isinstance(sessions, (list, tuple))
                    else "A remote-session result was not recorded.",
                    f"Recorded remote-access programs: {len(tools)}." if isinstance(tools, (list, tuple))
                    else "A remote-access program result was not recorded.")
    limits = tuple(explain_sensor_limitations(_strings(data.get("degraded_reasons"))))
    if classification == "degraded":
        return Explanation("Remote-access check incomplete", observations,
            "AIDA could not finish checking remote access. An incomplete check does not establish that someone is controlling this computer.",
            ("Review the unavailable checks and retry. If you are using technical support, verify the connection with the person you contacted.",), limits)
    activity_recorded = any(isinstance(value, (list, tuple)) and len(value) > 0 for value in (sessions, tools))
    fallback = ("AIDA observed remote-access activity. Remote support can be legitimate; check whether you expected this connection."
        if activity_recorded else "This record does not contain enough information to establish whether remote-access activity occurred.")
    meaning = {
        "confirmed_intrusion": "The recorded assessment classified this as an intrusion. Review the evidence and the available response promptly.",
        "likely_intrusion": "The recorded observations indicate a possible intrusion and need prompt review; AIDA cannot identify the person behind a connection from these records alone.",
        "unauthorized_suspected": "The recorded connection was not matched to expected support activity. That needs review, but does not by itself identify an attacker.",
        "support_session_anomalous": "AIDA noticed something unexpected during a support connection. Check that it matches the help you requested.",
        "authorized_support": "The recorded connection matched the support details provided to AIDA.",
    }.get(classification, fallback)
    title = "Remote connection needs review" if activity_recorded or classification not in {"unknown", None} else "Remote-access result unavailable"
    return Explanation(title, observations, meaning,
        ("Review the case's connection details and whether they match a support session you recognize. Use a supported response if the connection is unexpected.",), limits)


def _channel_from_reference(reference: str) -> str:
    reference = str(reference or "")
    return "Microsoft-Windows-Windows Defender/Operational" if "Defender" in reference else "Security" if "Security" in reference else "Windows event history"


def _strings(value) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, (list, tuple)) else ()


def alert_explanation(alert, context=None) -> Explanation:
    return explain_event(getattr(context, "event", None), severity=alert.severity)


def render_explanation(explanation: Explanation) -> str:
    lines = [explanation.title, "", "What AIDA observed", *["• " + item for item in explanation.observations],
             "", "What this means", explanation.meaning, "", "What you can do", *["• " + item for item in explanation.next_steps]]
    if explanation.limitations:
        lines.extend(["", "What AIDA could not verify", *["• " + item for item in explanation.limitations]])
    return "\n".join(lines)


def render_alert(alert, context=None, *, technical: bool = False) -> str:
    lines = [render_explanation(alert_explanation(alert, context)), "", "Notice recorded: " + readable_time(alert.created_at)]
    event = getattr(context, "event", None)
    if event:
        lines.append("Supporting observation: " + readable_time(event.occurred_at))
    if getattr(context, "provenance", "unavailable") == "legacy":
        lines.append("This explanation uses the matching evidence saved before this older notice was recorded.")
    if alert.ended_at:
        lines.append("Historical notice: this alert ended or was replaced. That does not by itself mean the issue was fixed.")
    lines.append("Read status: " + ("Marked as read" if alert.acknowledged_at else "Unread"))
    lines.append("Marking this notice as read only clears its unread status; it does not fix or close an investigation.")
    if technical:
        lines.extend(["", "Technical details", f"Alert: {alert.alert_id}", f"Case: {alert.case_id}",
            f"Recorded priority: {alert.severity}", f"Original message: {alert.message}"])
        if event:
            lines.extend([f"Evidence reference: {event.source_reference}", f"Evidence kind: {event.kind}",
                f"Evidence association: {getattr(context, 'provenance', 'unavailable')}",
                json.dumps(event.data, indent=2, ensure_ascii=False)[:16000]])
    return "\n".join(lines)
