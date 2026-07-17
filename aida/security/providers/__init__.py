"""Antivirus provider interfaces and adapters."""

from aida.security.providers.base import (
    AntivirusProvider,
    UnsupportedAntivirusProvider,
)
from aida.security.providers.defender import (
    MicrosoftDefenderError,
    MicrosoftDefenderProvider,
)

__all__ = [
    "AntivirusProvider",
    "MicrosoftDefenderError",
    "MicrosoftDefenderProvider",
    "UnsupportedAntivirusProvider",
]
