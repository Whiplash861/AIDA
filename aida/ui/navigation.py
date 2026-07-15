from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def _is_windows() -> bool:
    return os.name == "nt"


def _known_folder_path(folder_id: str) -> Optional[Path]:
    """
    Return a Windows Known Folder path via SHGetKnownFolderPath.

    Example GUID:
      Desktop = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
    """
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

        def parse_guid(g: str) -> GUID:
            g = g.strip("{}")
            parts = g.split("-")
            d1 = int(parts[0], 16)
            d2 = int(parts[1], 16)
            d3 = int(parts[2], 16)
            d4 = bytes.fromhex(parts[3] + parts[4])

            guid = GUID()
            guid.Data1 = d1
            guid.Data2 = d2
            guid.Data3 = d3
            for i in range(8):
                guid.Data4[i] = d4[i]
            return guid

        fid = parse_guid(folder_id)

        # SHGetKnownFolderPath allocates memory for the returned string.
        ppath = ctypes.c_wchar_p()

        hr = shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ppath))
        if hr != 0 or not ppath.value:
            return None

        resolved = Path(str(ppath.value))
        ole32.CoTaskMemFree(ppath)

        return resolved if resolved.exists() else None

    except Exception:
        return None


def _desktop_paths() -> List[Path]:
    """
    Collect likely Desktop paths:
    - Known Folder Desktop (most reliable)
    - home/Desktop fallback
    - OneDrive/Desktop fallbacks
    """
    paths: List[Path] = []

    desktop = _known_folder_path("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
    if desktop:
        paths.append(desktop)

    home_desktop = Path.home() / "Desktop"
    if home_desktop.exists():
        paths.append(home_desktop)

    for env_key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        od = os.environ.get(env_key)
        if od:
            p = Path(od) / "Desktop"
            if p.exists():
                paths.append(p)

    # De-dupe preserving order
    uniq: List[Path] = []
    seen: set[str] = set()
    for p in paths:
        rp = str(p.resolve()).lower()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


# ---------------- Windows navigation ----------------

def open_explorer_select(target: Path) -> None:
    """
    Open File Explorer and select the file/folder. Windows only.
    """
    if not _is_windows():
        raise RuntimeError("Explorer navigation is only supported on Windows.")
    target = target.resolve()
    subprocess.run(["explorer", "/select,", str(target)], check=False)


def open_explorer_folder(folder: Path) -> None:
    """
    Open File Explorer at a folder. Windows only.
    """
    if not _is_windows():
        raise RuntimeError("Explorer navigation is only supported on Windows.")
    folder = folder.resolve()
    subprocess.run(["explorer", str(folder)], check=False)


def open_settings(uri: str) -> None:
    """
    Open a Windows Settings page via ms-settings URI.
    Example: ms-settings:bluetooth
    """
    if not _is_windows():
        raise RuntimeError("Settings navigation is only supported on Windows.")
    subprocess.run(["cmd", "/c", "start", "", uri], shell=False, check=False)


# ---------------- File search (name-only) ----------------

def default_search_roots() -> List[Path]:
    """
    User-friendly defaults. Includes real Desktop even when OneDrive redirects it.
    """
    home = Path.home()
    candidates: List[Path] = []
    candidates += _desktop_paths()

    for p in (home / "Documents", home / "Downloads", home / "Pictures"):
        if p.exists():
            candidates.append(p)

    # De-dupe preserving order
    uniq: List[Path] = []
    seen: set[str] = set()
    for p in candidates:
        rp = str(p.resolve()).lower()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def find_file_by_name(
    filename: str,
    roots: Optional[Iterable[Path]] = None,
    max_results: int = 8,
    max_dirs_scanned: int = 8000,
) -> Tuple[List[Path], int]:
    """
    Search for a file by name only (no content inspection).

    Matches (case-insensitive):
      - exact filename
      - exact stem match (qFlipper matches qFlipper.lnk)
      - begins-with stem match
      - contains-stem match for shortcuts (.lnk) only
    """
    name = (filename or "").strip().strip('"').strip("'")
    if not name:
        return ([], 0)

    roots_list = list(roots) if roots is not None else default_search_roots()

    query_l = name.lower()
    query_stem_l = Path(query_l).stem.lower()

    matches: List[Path] = []
    dirs_scanned = 0

    for root in roots_list:
        if not root.exists() or not root.is_dir():
            continue

        for dirpath, _, filenames in os.walk(root):
            dirs_scanned += 1
            if dirs_scanned >= max_dirs_scanned:
                return (matches, dirs_scanned)

            for fn in filenames:
                fn_l = fn.lower()
                fn_stem_l = Path(fn_l).stem.lower()
                full_path = Path(dirpath) / fn

                exact_name = (fn_l == query_l)
                exact_stem = (fn_stem_l == query_stem_l)
                starts_stem = fn_stem_l.startswith(query_stem_l)

                # Forgiving match for Windows shortcuts only (safe + fixes app shortcuts)
                contains_stem_for_shortcut = (
                    full_path.suffix.lower() == ".lnk" and query_stem_l in fn_stem_l
                )

                if exact_name or exact_stem or starts_stem or contains_stem_for_shortcut:
                    matches.append(full_path)
                    if len(matches) >= max_results:
                        return (matches, dirs_scanned)

    return (matches, dirs_scanned)