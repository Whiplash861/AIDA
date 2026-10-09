from __future__ import annotations

from aida.artificer.ledger_core import LedgerCore, LedgerIntegrityError
from aida.artificer.ledger_events import LedgerEventsMixin
from aida.artificer.ledger_findings import LedgerFindingsMixin
from aida.artificer.ledger_operations import LedgerOperationsMixin
from aida.artificer.ledger_reviews import LedgerReviewsMixin


class ArtificerLedger(
    LedgerEventsMixin,
    LedgerFindingsMixin,
    LedgerOperationsMixin,
    LedgerReviewsMixin,
    LedgerCore,
):
    """Durable Artificer state and append-oriented audit history."""


__all__ = ["ArtificerLedger", "LedgerIntegrityError"]
