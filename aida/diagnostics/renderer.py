"""Explain diagnostic observations without treating missing checks as success."""
from __future__ import annotations

from collections.abc import Iterable
import re
from aida.diagnostics.base import Finding
from aida.reporting import render_report


def check_incomplete(finding: Finding) -> bool:
    return (finding.id.endswith("_unavailable") or finding.id in {"sys.error", "sys.quickscan_error", "sec.authorization_required"}
            or finding.detail.strip().lower() == "unavailable"
            or (finding.id == "sec.defender" and finding.detail.lower().startswith("unknown"))
            or (finding.id == "perf.top_memory_processes" and not finding.evidence))


def render_findings(findings: Iterable[Finding], *, title: str) -> str:
    items = list(findings)
    found, unknown, steps, details = [], [], [], []
    for item in items:
        if check_incomplete(item):
            unknown.append(f"{item.title}: {item.detail or 'This check did not supply a result.'}")
        else:
            label = {"high": "Review promptly", "critical": "Urgent review", "medium": "Worth checking"}.get(item.severity.lower(), "Observation")
            found.append(f"{label} — {item.title}: {item.detail or 'No explanation was supplied with this observation.'}")
        if item.evidence:
            details.append(f"{item.title} ({item.id}): {item.evidence}")
        if item.recommended_next:
            steps.append(f"{item.title}: {item.recommended_next}")
        if item.id.startswith("perf.gpu_") and "unavailable" in item.detail.lower():
            unknown.append(f"{item.title}: one or more graphics measurements were unavailable; only reported values can be interpreted.")
    if not found:
        found.append("No usable diagnostic observations were returned.")
    unknown.append("This is a limited snapshot. It does not establish the cause of an intermittent problem or confirm that every component is healthy.")
    if any(check_incomplete(item) for item in items) or not items:
        steps.append("Repeat any unavailable check if it is relevant to your problem. Missing measurements alone do not mean the computer is damaged.")
    steps.append("If a problem continues, note what you were doing and run the check while it is happening. Save your work before closing applications.")
    if "quickscan" in title.lower():
        unknown.append("Quickscan reviews available system information; it is not a completed antivirus scan of every file.")
        unknown.append("Process and startup lists may be partial; an item missing from this report is not proof that it is absent from the computer.")
    return render_report(title, found=found, unknown=unknown, next_steps=steps, details=details)


def findings_speech(findings: Iterable[Finding], *, title: str) -> str:
    items = list(findings)
    if any(item.id == "sec.provider_result" for item in items):
        return f"{title}. The antivirus provider's recorded result is in the report. Read its findings, limitations, and next steps before deciding whether any action is needed."
    observed = [item for item in items if not check_incomplete(item)]
    urgent = sum(item.severity.lower() in {"high", "critical"} for item in observed)
    review = sum(item.severity.lower() == "medium" for item in observed)
    if not observed:
        result = "No usable measurements were returned, so I cannot assess the computer from this check."
    elif urgent:
        result = f"{urgent} observation{'s need' if urgent != 1 else ' needs'} prompt review."
    elif review:
        result = f"{review} observation{'s are' if review != 1 else ' is'} worth checking."
    else:
        result = "The returned observations did not flag a high-priority condition. This is a limited snapshot."
    if observed and len(observed) != len(items):
        result += " Some checks could not provide information."
    return f"{title}. {result} Review the report for what remains unknown and the next steps."


def render_resource_comparison(previous: Iterable[Finding], current: Iterable[Finding]) -> str:
    """Retain the CLI's between-scan comparison without inferring a cause."""
    def readings(items):
        result = {}
        labels = {"perf.ram_usage": "Memory use", "perf.memory_usage": "Memory use", "perf.cpu_usage": "Processor use"}
        for item in items:
            if item.id not in labels or check_incomplete(item):
                continue
            match = re.match(r"\s*(\d+(?:\.\d+)?)%", item.detail)
            if match and 0 <= float(match.group(1)) <= 100:
                result[labels[item.id]] = float(match.group(1))
        return result
    before, after = readings(previous), readings(current)
    found = [f"{name}: {before[name]:.1f}% earlier and {after[name]:.1f}% now ({after[name] - before[name]:+.1f} percentage points)."
             for name in before.keys() & after.keys()]
    if not found:
        return ""
    return render_report("Resource comparison with the previous scan", found=sorted(found),
        unknown=["The workload may differ between scans. A change in resource use does not establish its cause or prove that a repair worked."],
        next_steps=["Compare readings during similar tasks and note whether the problem itself improved."])
