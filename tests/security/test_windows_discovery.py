from __future__ import annotations

from aida.security.providers.base import UnsupportedAntivirusProvider
from aida.security.providers.defender import MicrosoftDefenderProvider
from aida.security.windows.discovery import WindowsAntivirusDiscovery
from aida.security.windows.security_center import (
    WindowsAntivirusProduct,
    WindowsProductState,
    WindowsSignatureStatus,
)


class FakeProductSource:
    def __init__(self, products: tuple[WindowsAntivirusProduct, ...]) -> None:
        self.products = products

    def list_antivirus_products(self) -> tuple[WindowsAntivirusProduct, ...]:
        return self.products


class FakeRunner:
    def run_json(self, script: str, timeout: float = 15.0):
        del script, timeout
        return {}

    def start(self, script: str):
        raise AssertionError(script)


def product(
    name: str,
    state: WindowsProductState,
) -> WindowsAntivirusProduct:
    return WindowsAntivirusProduct(
        product_id=name.lower().replace(" ", "-"),
        display_name=name,
        state=state,
        signature_status=WindowsSignatureStatus.UP_TO_DATE,
    )


def test_discovery_selects_active_defender_adapter() -> None:
    discovery = WindowsAntivirusDiscovery(
        FakeProductSource((
            product("Other AV", WindowsProductState.OFF),
            product("Microsoft Defender Antivirus", WindowsProductState.ON),
        )),
        FakeRunner(),
    ).discover()
    assert isinstance(discovery.provider, MicrosoftDefenderProvider)
    assert discovery.selected_product is not None
    assert discovery.selected_product.display_name == "Microsoft Defender Antivirus"


def test_discovery_returns_unsupported_adapter_for_active_third_party_av() -> None:
    discovery = WindowsAntivirusDiscovery(
        FakeProductSource((product("McAfee", WindowsProductState.ON),)),
        FakeRunner(),
    ).discover()
    assert isinstance(discovery.provider, UnsupportedAntivirusProvider)
    assert discovery.provider.display_name == "McAfee"


def test_discovery_fails_safe_when_no_provider_is_active() -> None:
    discovery = WindowsAntivirusDiscovery(
        FakeProductSource((product("Other AV", WindowsProductState.OFF),)),
        FakeRunner(),
    ).discover()
    assert isinstance(discovery.provider, UnsupportedAntivirusProvider)
    assert discovery.selected_product is None
