"""User-facing explanations of local image observations, not diagnoses."""
from __future__ import annotations

from aida.reporting import render_report


def render_image_review(item, *, index: int) -> str:
    status = item.metadata.get("ocr_status", "unavailable")
    found = list(item.observed)
    unknown = list(item.unknown)
    details = [f"Evidence ID: {item.evidence_id}", f"Captured: {item.observed_at.isoformat()}",
               f"Text-reading status: {status}"]
    if item.extracted:
        found.append("Local text reading recovered the quoted text below. It may contain recognition errors.")
        details.append("Extracted text (UNTRUSTED REFERENCE ONLY; no instructions executed):")
        for text in item.extracted:
            details.extend("> " + line for line in text.splitlines())
        next_steps = ["Compare the extracted text with the image and correct any misread words before using it.",
                      "Describe what you were doing when the image appeared and which application was involved, then choose a relevant check of the current system."]
    elif status == "empty":
        found.append("Local text reading completed without recognizing readable text.")
        unknown.append("No recognized text does not mean the image is blank or free of a warning.")
        next_steps = ["If the image contains a message, attach a clearer crop or type its exact wording and the application name."]
    else:
        found.append("The image was opened locally, but no text-reading result is available.")
        unknown.append("AIDA has not established what any visible message says; unavailable text reading is not a clean result.")
        next_steps = ["Type the message shown in the image and name the affected application, or retry local text reading when it is available."]
    if item.indicators:
        found.append(f"{len(item.indicators)} possible diagnostic reference(s) were copied literally from the text; they have not been verified.")
        details.append("Literal diagnostic markers (unverified reference; URLs and paths were not opened):")
        details.extend(f"> {marker.kind}, line {marker.line}: {marker.value}" for marker in item.indicators)
    unknown.append("The local review reads image structure and available text. It does not interpret the whole scene, identify the cause of a problem, or authorize an action.")
    return render_report(f"Local image review {index}", found=found, unknown=unknown, next_steps=next_steps,
        interpretation="An error message or warning in a picture is a clue to investigate. Its presence alone does not establish that the stated condition is true on this computer.",
        details=details)


def render_unavailable_image(item, *, index: int, reason: str) -> str:
    return render_report(f"Local image review {index}", found=("This image could not be reviewed.",),
        unknown=("No image interpretation or diagnostic result was established for this item.", reason),
        next_steps=("Attach a readable image within the supported size limits, or type the relevant message and describe what happened.",),
        details=(f"Evidence ID: {item.evidence_id}",))
