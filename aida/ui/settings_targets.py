from __future__ import annotations

from aida.platform.windows import WindowsAdapter

# Backward-compatible alias. New navigation code resolves targets through the active adapter.
SETTINGS_URIS = dict(WindowsAdapter.SETTINGS_URIS)
