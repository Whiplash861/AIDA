from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class Finding:
    id: str
    title: str
    severity: str = "info"
    detail: str = ""
    evidence: str = ""
    recommended_next: str = ""
