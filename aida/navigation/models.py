from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EvidenceMatchType(StrEnum):
    EXACT_PATH = "exact_path"
    EXACT_HASH = "exact_hash"
    EXACT_IDENTITY = "exact_identity"
    POSSIBLE_FILENAME = "possible_filename"


@dataclass(frozen=True, slots=True)
class EvidenceMatch:
    path: Path
    match_type: EvidenceMatchType
    confidence: float
    reason: str
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceLocateResult:
    requested_path: Path
    matches: tuple[EvidenceMatch, ...]
    files_examined: int
    elapsed_seconds: float
    truncated: bool
    exact_match_found: bool


class NavigationAction(StrEnum):
    OPEN_CONTAINING_FOLDER = "open_containing_folder"
    SELECT_IN_EXPLORER = "select_in_explorer"
    COPY_PATH = "copy_path"
    LOCATE = "locate"
