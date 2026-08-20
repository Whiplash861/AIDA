from __future__ import annotations

from aida.artificer.engine import ArtificerEngine
from aida.artificer.event_bus import EventBus
from aida.config import AidaConfig, get_config


def build_artificer_engine(
    config: AidaConfig | None = None,
    *,
    event_bus: EventBus | None = None,
) -> ArtificerEngine:
    """Construct the Artificer backend without starting or wiring it to a UI.

    Frontend and Perception Engine integration must explicitly receive this
    instance later. Merely importing this module never starts monitoring,
    schedules reviews, modifies source, or changes frontend state.
    """

    return ArtificerEngine(
        config=config or get_config(),
        event_bus=event_bus,
    )
