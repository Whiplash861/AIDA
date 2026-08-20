from __future__ import annotations

import sys
from pathlib import Path


# Running a script by path makes its containing directory (tools/) Python's
# import root. Add the repository root explicitly so the sibling aida package
# is importable without requiring PYTHONPATH or an editable installation.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from aida.security.windows.discovery import WindowsAntivirusDiscovery


def main() -> int:
    try:
        discovery = WindowsAntivirusDiscovery().discover()
    except Exception as exc:
        print(f"Provider discovery failed: {type(exc).__name__}: {exc}")
        return 1

    print("Registered antivirus products:")
    if not discovery.products:
        print("  None reported by Windows Security Center")

    for product in discovery.products:
        state = product.state.name if product.state is not None else "UNKNOWN"
        signatures = product.signatures_current
        print(
            f"  {product.display_name} | state={state} | "
            f"signatures_current={signatures}"
        )

    selected = (
        discovery.selected_product.display_name
        if discovery.selected_product is not None
        else "None"
    )
    print(f"Selected product: {selected}")
    print(f"AIDA adapter: {discovery.provider.display_name}")
    print(f"Discovery detail: {discovery.detail}")

    try:
        status = discovery.provider.get_status()
    except Exception as exc:
        print(f"Status read failed: {type(exc).__name__}: {exc}")
        return 1

    print(
        "Provider status: "
        f"active={status.active}, "
        f"healthy={status.healthy}, "
        f"real_time_protection={status.real_time_protection}, "
        f"signatures_current={status.signatures_current}"
    )
    if status.detail:
        print(f"Status detail: {status.detail}")

    print("Read-only provider probe complete. No scan was started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
