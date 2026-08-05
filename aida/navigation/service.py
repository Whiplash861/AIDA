from __future__ import annotations

import hashlib
import os
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterable

from aida.assistance.models import AssistanceCancelled
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.navigation.models import (
    EvidenceLocateResult,
    EvidenceMatch,
    EvidenceMatchType,
)


CancelCheck = Callable[[], bool]
Launcher = Callable[[list[str]], object]


class EvidenceNavigationService:
    """Safe file-location and Explorer navigation without opening the target."""

    def __init__(
        self,
        memory: MemoryService | None = None,
        *,
        launcher: Launcher | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_files: int = 25_000,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.memory = memory
        self.launcher = launcher or _launch
        self.clock = clock
        self.max_files = max(100, max_files)
        self.timeout_seconds = max(1.0, timeout_seconds)

    def open_containing_folder(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        folder = target if target.is_dir() else target.parent
        if not folder.is_dir():
            raise FileNotFoundError(f"Containing folder is unavailable: {folder}")
        if os.name == "nt":
            self.launcher(["explorer.exe", str(folder)])
        else:
            self.launcher(["xdg-open", str(folder)])
        self._log(
            "EVIDENCE_FOLDER_OPENED",
            f"Opened the containing folder for {target.name}.",
            target,
        )
        return folder

    def select_in_explorer(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(f"Evidence target is unavailable: {target}")
        if os.name == "nt":
            self.launcher(["explorer.exe", f"/select,{target}"])
        else:
            self.open_containing_folder(target)
        self._log(
            "EVIDENCE_SELECTED_IN_EXPLORER",
            f"Selected {target.name} in the system file browser.",
            target,
        )
        return target

    def locate(
        self,
        requested_path: str | Path,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
        expected_modified_ns: int | None = None,
        roots: Iterable[str | Path] | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> EvidenceLocateResult:
        started = self.clock()
        requested = Path(requested_path).expanduser()
        try:
            resolved_requested = requested.resolve()
        except OSError:
            resolved_requested = requested.absolute()
        matches: list[EvidenceMatch] = []
        files_examined = 0
        truncated = False

        if resolved_requested.is_file():
            current_hash = None
            if expected_sha256:
                current_hash = _sha256(resolved_requested, cancel_check)
            exact = (
                not expected_sha256
                or current_hash.lower() == expected_sha256.lower()
            )
            if exact:
                matches.append(
                    EvidenceMatch(
                        path=resolved_requested,
                        match_type=EvidenceMatchType.EXACT_PATH,
                        confidence=1.0,
                        reason="The original path exists and its supplied identity still matches.",
                        sha256=current_hash,
                    )
                )
                return self._result(
                    resolved_requested,
                    matches,
                    files_examined=1,
                    started=started,
                    truncated=False,
                )

        search_roots = _search_roots(resolved_requested, roots)
        queue: deque[Path] = deque(search_roots)
        seen_dirs: set[str] = set()
        filename = resolved_requested.name.lower()
        while queue:
            _raise_if_cancelled(cancel_check)
            if files_examined >= self.max_files:
                truncated = True
                break
            if self.clock() - started >= self.timeout_seconds:
                truncated = True
                break
            folder = queue.popleft()
            folder_key = _path_key(folder)
            if folder_key in seen_dirs:
                continue
            seen_dirs.add(folder_key)
            try:
                entries = list(os.scandir(folder))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                _raise_if_cancelled(cancel_check)
                if files_examined >= self.max_files:
                    truncated = True
                    break
                if self.clock() - started >= self.timeout_seconds:
                    truncated = True
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        queue.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    files_examined += 1
                    candidate = Path(entry.path)
                    stat = entry.stat(follow_symlinks=False)
                except (OSError, PermissionError):
                    continue

                same_name = candidate.name.lower() == filename
                same_size = expected_size is None or stat.st_size == expected_size
                same_modified = (
                    expected_modified_ns is None
                    or stat.st_mtime_ns == expected_modified_ns
                )
                if expected_sha256 and same_size and (same_name or expected_size is not None):
                    try:
                        candidate_hash = _sha256(candidate, cancel_check)
                    except OSError:
                        continue
                    if candidate_hash.lower() == expected_sha256.lower():
                        matches.append(
                            EvidenceMatch(
                                path=candidate,
                                match_type=EvidenceMatchType.EXACT_HASH,
                                confidence=1.0,
                                reason="The candidate matches the recorded SHA-256 identity.",
                                sha256=candidate_hash,
                            )
                        )
                        continue
                if same_name and same_size and same_modified:
                    matches.append(
                        EvidenceMatch(
                            path=candidate,
                            match_type=EvidenceMatchType.EXACT_IDENTITY,
                            confidence=0.92,
                            reason="Filename, size, and modification identity match; no full hash was available.",
                        )
                    )
                elif same_name:
                    matches.append(
                        EvidenceMatch(
                            path=candidate,
                            match_type=EvidenceMatchType.POSSIBLE_FILENAME,
                            confidence=0.45,
                            reason="The filename matches, but the complete recorded identity does not.",
                        )
                    )

        matches = sorted(
            _deduplicate(matches),
            key=lambda item: (-item.confidence, str(item.path).lower()),
        )[:50]
        result = self._result(
            resolved_requested,
            matches,
            files_examined=files_examined,
            started=started,
            truncated=truncated,
        )
        self._log(
            "EVIDENCE_LOCATION_COMPLETED",
            (
                f"Evidence location examined {files_examined} file(s) and found "
                f"{len(matches)} candidate(s)."
            ),
            resolved_requested,
            payload={
                "exact_match_found": result.exact_match_found,
                "truncated": truncated,
                "matches": [
                    {
                        "path": str(item.path),
                        "match_type": item.match_type.value,
                        "confidence": item.confidence,
                    }
                    for item in matches
                ],
            },
        )
        return result

    def _result(
        self,
        requested: Path,
        matches: list[EvidenceMatch],
        *,
        files_examined: int,
        started: float,
        truncated: bool,
    ) -> EvidenceLocateResult:
        return EvidenceLocateResult(
            requested_path=requested,
            matches=tuple(matches),
            files_examined=files_examined,
            elapsed_seconds=max(0.0, self.clock() - started),
            truncated=truncated,
            exact_match_found=any(
                item.match_type
                in {EvidenceMatchType.EXACT_PATH, EvidenceMatchType.EXACT_HASH}
                for item in matches
            ),
        )

    def _log(
        self,
        event_type: str,
        summary: str,
        target: Path,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        if self.memory is None:
            return
        details = {"path": str(target)}
        details.update(payload or {})
        self.memory.log_event(
            event_type,
            "navigation.evidence",
            summary,
            payload=details,
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=1.0,
            promote=False,
        )


def render_location_result(result: EvidenceLocateResult) -> str:
    lines = [
        "EVIDENCE LOCATION RESULT",
        "",
        f"Requested path: {result.requested_path}",
        f"Files examined: {result.files_examined}",
        f"Elapsed: {result.elapsed_seconds:.2f} seconds",
        f"Search truncated: {'yes' if result.truncated else 'no'}",
        "",
    ]
    if not result.matches:
        lines.append("No matching or probable file was located within the permitted search scope.")
        return "\n".join(lines)
    for index, match in enumerate(result.matches, start=1):
        label = (
            "EXACT IDENTITY MATCH"
            if match.match_type
            in {EvidenceMatchType.EXACT_PATH, EvidenceMatchType.EXACT_HASH}
            else "POSSIBLE MATCH — USER VERIFICATION REQUIRED"
        )
        lines.extend(
            [
                f"{index}. {label}",
                f"   Path: {match.path}",
                f"   Basis: {match.reason}",
                f"   Confidence: {round(match.confidence * 100)} percent",
            ]
        )
    return "\n".join(lines)


def _search_roots(
    requested: Path,
    roots: Iterable[str | Path] | None,
) -> tuple[Path, ...]:
    if roots is not None:
        raw = [Path(item).expanduser() for item in roots]
    else:
        home = Path.home()
        raw = [
            requested.parent,
            home / "Downloads",
            home / "Desktop",
            home / "Documents",
            home / "OneDrive",
        ]
    output: list[Path] = []
    seen: set[str] = set()
    for item in raw:
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item.absolute()
        key = _path_key(resolved)
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        output.append(resolved)
    return tuple(output)


def _sha256(path: Path, cancel_check: CancelCheck | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            _raise_if_cancelled(cancel_check)
            digest.update(block)
    return digest.hexdigest()


def _raise_if_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise AssistanceCancelled("The user cancelled the evidence-location task.")


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _deduplicate(matches: list[EvidenceMatch]) -> list[EvidenceMatch]:
    selected: dict[str, EvidenceMatch] = {}
    for match in matches:
        key = _path_key(match.path)
        current = selected.get(key)
        if current is None or match.confidence > current.confidence:
            selected[key] = match
    return list(selected.values())


def _launch(arguments: list[str]) -> object:
    return subprocess.Popen(
        arguments,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
