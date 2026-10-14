"""Consistent user-facing reports, without changing evidence or action policy."""
from __future__ import annotations

from collections.abc import Iterable


def render_report(title: str, *, found: Iterable[str], unknown: Iterable[str],
                  next_steps: Iterable[str], details: Iterable[str] = (),
                  interpretation: str = "") -> str:
    """Render supplied facts and limits; never infer success from empty results.

    Callers own the evidence interpretation. Internal status codes and saved
    records stay unchanged, and technical details remain available after the
    everyday explanation. Short progress and acknowledgement messages do not
    need this format.
    """
    sections = (
        ("What AIDA found", _items(found) or ("No findings were supplied with this report.",)),
        ("What remains unknown", _items(unknown) or (
            "No specific limitations were supplied; this does not establish that every check completed.",)),
        ("What to do next", _items(next_steps) or (
            "Review the available information before choosing another check or a response.",)),
    )
    lines = [str(title).strip() or "AIDA report"]
    for heading, items in sections:
        lines.extend(["", heading, *["• " + item for item in items]])
        if heading == "What AIDA found" and interpretation.strip():
            lines.extend(["", "What this means", interpretation.strip()])
    recorded_details = _items(details)
    if recorded_details:
        lines.extend(["", "Technical details", *recorded_details])
    return "\n".join(lines)


def _items(value: Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    return tuple(dict.fromkeys(str(item).strip() for item in value if item is not None and str(item).strip()))
