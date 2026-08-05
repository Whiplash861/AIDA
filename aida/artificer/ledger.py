from __future__ import annotations

from aida.artificer.ledger_core import LedgerCore, LedgerIntegrityError
from aida.artificer.ledger_events import LedgerEventsMixin
from aida.artificer.ledger_findings import LedgerFindingsMixin
from aida.artificer.ledger_operations import LedgerOperationsMixin


class ArtificerLedger(
    LedgerEventsMixin,
    LedgerFindingsMixin,
    LedgerOperationsMixin,
    LedgerCore,
):
    """Durable Artificer state and append-oriented audit history."""


__all__ = ["ArtificerLedger", "LedgerIntegrityError"]
