from __future__ import annotations

from dataclasses import dataclass

from aida.security.providers.base import (
    AntivirusProvider,
    UnsupportedAntivirusProvider,
)
from aida.security.providers.defender_recovering import (
    RecoveringMicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellRunner
from aida.security.windows.security_center import (
    AntivirusProductSource,
    NativeWindowsSecurityCenter,
    WindowsAntivirusProduct,
)


@dataclass(frozen=True, slots=True)
class WindowsProviderDiscovery:
    products: tuple[WindowsAntivirusProduct, ...]
    selected_product: WindowsAntivirusProduct | None
    provider: AntivirusProvider
    detail: str


class WindowsAntivirusDiscovery:
    def __init__(
        self,
        product_source: AntivirusProductSource | None = None,
        powershell_runner: PowerShellRunner | None = None,
    ) -> None:
        self._product_source = (
            product_source or NativeWindowsSecurityCenter()
        )
        self._powershell_runner = powershell_runner

    def discover(self) -> WindowsProviderDiscovery:
        products = self._product_source.list_antivirus_products()
        selected = _select_product(products)

        if selected is None:
            return WindowsProviderDiscovery(
                products=products,
                selected_product=None,
                provider=UnsupportedAntivirusProvider(
                    "No active antivirus provider"
                ),
                detail=(
                    "Windows Security Center did not report an active "
                    "antivirus product."
                ),
            )

        if _is_microsoft_defender(selected):
            provider = RecoveringMicrosoftDefenderProvider(
                runner=self._powershell_runner
            )
            detail = (
                "Microsoft Defender is active and direct scan control "
                "with provider scan recovery is available."
            )
        else:
            provider = UnsupportedAntivirusProvider(
                selected.display_name
            )
            detail = (
                f"{selected.display_name} is active, but AIDA does not "
                "yet have a supported direct-control adapter for it."
            )

        return WindowsProviderDiscovery(
            products=products,
            selected_product=selected,
            provider=provider,
            detail=detail,
        )


def _select_product(
    products: tuple[WindowsAntivirusProduct, ...],
) -> WindowsAntivirusProduct | None:
    active = [product for product in products if product.active]
    if not active:
        return None

    for product in active:
        if _is_microsoft_defender(product):
            return product
    return active[0]


def _is_microsoft_defender(product: WindowsAntivirusProduct) -> bool:
    haystack = (
        f"{product.display_name} {product.remediation_path}"
    ).lower()
    return (
        "microsoft defender" in haystack
        or "windows defender" in haystack
    )
