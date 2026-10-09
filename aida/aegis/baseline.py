from __future__ import annotations

import os

from aida.aegis.models import BaselineDelta, PersistenceEntity, SecuritySnapshot


def compare_snapshots(
    baseline: SecuritySnapshot | None,
    current: SecuritySnapshot,
) -> BaselineDelta:
    if baseline is None:
        return BaselineDelta(baseline_available=False)

    baseline_processes = {
        _path_key(process.executable)
        for process in baseline.processes
        if process.executable
    }
    current_process_map = {
        _path_key(process.executable): process.executable
        for process in current.processes
        if process.executable
    }
    baseline_process_map = {
        _path_key(process.executable): process.executable
        for process in baseline.processes
        if process.executable
    }

    baseline_persistence = {
        _persistence_key(item): item for item in baseline.persistence
    }
    current_persistence = {
        _persistence_key(item): item for item in current.persistence
    }

    baseline_listeners = set(baseline.listeners)
    current_listeners = set(current.listeners)

    return BaselineDelta(
        baseline_available=True,
        new_process_paths=tuple(
            sorted(
                current_process_map[key]
                for key in current_process_map.keys() - baseline_processes
            )
        ),
        removed_process_paths=tuple(
            sorted(
                baseline_process_map[key]
                for key in baseline_process_map.keys() - current_process_map.keys()
            )
        ),
        new_persistence=tuple(
            current_persistence[key]
            for key in sorted(current_persistence.keys() - baseline_persistence.keys())
        ),
        removed_persistence=tuple(
            baseline_persistence[key]
            for key in sorted(baseline_persistence.keys() - current_persistence.keys())
        ),
        new_listeners=tuple(sorted(current_listeners - baseline_listeners)),
        removed_listeners=tuple(sorted(baseline_listeners - current_listeners)),
    )


def _persistence_key(item: PersistenceEntity) -> tuple[str, str, str]:
    return (
        item.mechanism.strip().lower(),
        item.name.strip().lower(),
        _path_key(item.target),
    )


def _path_key(value: str) -> str:
    normalized = os.path.normcase(os.path.normpath(value.strip()))
    return normalized.lower()
