from __future__ import annotations

import re
from typing import Optional, Tuple

ALIASES = {
    "outlook": ["outlook", "out look", "otlouk", "otlook", "outlok", "microsoft outlook"],
    "word": ["word", "microsoft word", "ms word"],
    "excel": ["excel", "exel", "microsoft excel"],
    "powerpoint": ["powerpoint", "power point", "ppt", "powerpnt"],
    "teams": ["teams", "ms teams", "microsoft teams"],
    "chrome": ["chrome", "google chrome", "chrme", "chorme"],
    "edge": ["edge", "microsoft edge", "ms edge"],
}

def infer_app_local(text: str) -> Tuple[Optional[str], float]:
    t = (text or "").lower()
    t = re.sub(r"\s+", " ", t).strip()

    hits = []
    for app, patterns in ALIASES.items():
        for p in patterns:
            if p in t:
                hits.append(app)
                break

    if not hits:
        return None, 0.0
    if len(set(hits)) > 1:
        return None, 0.3
    return hits[0], 0.8
