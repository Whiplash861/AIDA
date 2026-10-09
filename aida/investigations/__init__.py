"""Local investigation records. Stored evidence never grants action authority."""
from .service import InvestigationService
from .store import InvestigationStore

__all__ = ["InvestigationService", "InvestigationStore"]
