from __future__ import annotations

import pytest

from aida.artificer.consent import ConsentManager
from aida.artificer.developer_registry import DeveloperRegistry
from aida.artificer.dispatch import ArtificerDispatch, LocalExportTransport
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.sanitizer import PayloadSanitizer


def test_dispatch_is_denied_without_consent(tmp_path) -> None:
    dispatch = ArtificerDispatch(
        ledger=ArtificerLedger(tmp_path / "ledger.db"),
        sanitizer=PayloadSanitizer(),
        consent=ConsentManager(tmp_path / "consent.json"),
        developers=DeveloperRegistry(tmp_path / "developers.json"),
        transport=LocalExportTransport(tmp_path / "exports"),
    )
    with pytest.raises(PermissionError):
        dispatch.queue("operational_summary", {"status": "ok"})
