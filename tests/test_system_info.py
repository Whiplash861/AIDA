from __future__ import annotations

from utils.system_info import collect_system_info


def test_collect_system_info_returns_normalized_values() -> None:
    info = collect_system_info()
    assert info.os_family
    assert info.logical_cores >= 1
    assert info.total_memory_gb > 0
