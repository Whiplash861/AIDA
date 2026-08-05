from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class Finding:
    id: str
    title: str
    severity: str = "info"
    detail: str = ""
    evidence: str = ""
    recommended_next: str = ""
