from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from aida.platform.registry import get_platform_adapter


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _known_folder_path(folder_id: str) -> Optional[Path]:
    """Resolve a Windows Known Folder path; return None on other platforms."""
    if not _is_windows():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

        def parse_guid(value: str) -> GUID:
            parts = value.strip("{}").split("-")
            raw = bytes.fromhex(parts[3] + parts[4])
            guid = GUID()
            guid.Data1 = int(parts[0], 16)
            guid.Data2 = int(parts[1], 16)
            guid.Data3 = int(parts[2], 16)
            for index in range(8):
                guid.Data4[index] = raw[index]
            return guid

        folder_guid = parse_guid(folder_id)
        output = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_guid), 0, None, ctypes.byref(output)
        )
        if result != 0 or not output.value:
            return None
        resolved = Path(str(output.value))
        ole32.CoTaskMemFree(output)
        return resolved if resolved.exists() else None
    except Exception:
        return None


def _desktop_paths() -> List[Path]:
    paths: List[Path] = []
    known_desktop = _known_folder_path("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
    if known_desktop:
        paths.append(known_desktop)
    home_desktop = Path.home() / "Desktop"
    if home_desktop.exists():
        paths.append(home_desktop)
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(key)
        if root:
            candidate = Path(root) / "Desktop"
            if candidate.exists():
                paths.append(candidate)
    return _dedupe_paths(paths)


def _dedupe_paths(paths: Iterable[Path]) -> List[Path]:
    unique: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            identity = str(path.resolve()).casefold()
        except OSError:
            identity = str(path).casefold()
        if identity not in seen:
            seen.add(identity)
            unique.append(path)
    return unique


def open_explorer_select(target: Path) -> None:
    """Reveal a target through the active platform adapter."""
    get_platform_adapter().reveal_path(target.resolve())


def open_explorer_folder(folder: Path) -> None:
    """Open a folder through the active platform adapter."""
    get_platform_adapter().open_folder(folder.resolve())


def open_settings(target: str) -> None:
    """Open a normalized settings target through the active platform adapter."""
    get_platform_adapter().open_settings(target)


def default_search_roots() -> List[Path]:
    home = Path.home()
    candidates: List[Path] = []
    candidates.extend(_desktop_paths())
    for path in (
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
    ):
        if path.exists():
            candidates.append(path)
    return _dedupe_paths(candidates)


def find_file_by_name(
    filename: str,
    roots: Optional[Iterable[Path]] = None,
    max_results: int = 8,
    max_dirs_scanned: int = 8000,
) -> Tuple[List[Path], int]:
    """Search file names only. File contents are never inspected."""
    name = (filename or "").strip().strip('"').strip("'")
    if not name:
        return [], 0
    roots_list = list(roots) if roots is not None else default_search_roots()
    query_lower = name.casefold()
    query_stem = Path(query_lower).stem.casefold()
    matches: List[Path] = []
    directories_scanned = 0

    for root in roots_list:
        if not root.exists() or not root.is_dir():
            continue
        for directory, _, filenames in os.walk(root):
            directories_scanned += 1
            if directories_scanned >= max_dirs_scanned:
                return matches, directories_scanned
            for candidate_name in filenames:
                name_lower = candidate_name.casefold()
                stem_lower = Path(name_lower).stem.casefold()
                candidate = Path(directory) / candidate_name
                exact_name = name_lower == query_lower
                exact_stem = stem_lower == query_stem
                begins_with = stem_lower.startswith(query_stem)
                shortcut_contains = (
                    candidate.suffix.casefold() == ".lnk" and query_stem in stem_lower
                )
                if exact_name or exact_stem or begins_with or shortcut_contains:
                    matches.append(candidate)
                    if len(matches) >= max_results:
                        return matches, directories_scanned
    return matches, directories_scanned
