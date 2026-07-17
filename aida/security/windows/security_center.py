from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol
from uuid import UUID, NAMESPACE_URL, uuid5


class WindowsSecurityCenterError(RuntimeError):
    pass


class WindowsProductState(IntEnum):
    ON = 0
    OFF = 1
    SNOOZED = 2
    EXPIRED = 3


class WindowsSignatureStatus(IntEnum):
    OUT_OF_DATE = 0
    UP_TO_DATE = 1


@dataclass(frozen=True, slots=True)
class WindowsAntivirusProduct:
    product_id: str
    display_name: str
    state: WindowsProductState | None
    signature_status: WindowsSignatureStatus | None
    remediation_path: str = ""
    state_timestamp: str = ""

    @property
    def active(self) -> bool:
        return self.state is WindowsProductState.ON

    @property
    def signatures_current(self) -> bool | None:
        if self.signature_status is None:
            return None
        return self.signature_status is WindowsSignatureStatus.UP_TO_DATE

    @property
    def healthy(self) -> bool:
        return self.active and self.signatures_current is not False


class AntivirusProductSource(Protocol):
    def list_antivirus_products(self) -> tuple[WindowsAntivirusProduct, ...]:
        ...


class NativeWindowsSecurityCenter:
    """Reads antivirus registration through the official Windows Security Center COM API."""

    _CLSID_PRODUCT_LIST = UUID("17072f7b-9abe-4a74-a261-1eb76b55107a")
    _IID_PRODUCT_LIST = UUID("722a338c-6e8e-4e72-ac27-1417fb0c81c2")
    _WSC_SECURITY_PROVIDER_ANTIVIRUS = 0x4

    def list_antivirus_products(self) -> tuple[WindowsAntivirusProduct, ...]:
        if os.name != "nt":
            raise WindowsSecurityCenterError(
                "Windows Security Center is only available on Windows"
            )

        api = _ComApi()
        initialized = api.initialize_com()
        product_list = ctypes.c_void_p()

        try:
            api.create_product_list(product_list)
            api.initialize_product_list(
                product_list,
                self._WSC_SECURITY_PROVIDER_ANTIVIRUS,
            )
            count = api.get_count(product_list)

            products: list[WindowsAntivirusProduct] = []
            for index in range(max(0, count)):
                product = api.get_item(product_list, index)
                try:
                    name = api.get_bstr(product, 7)
                    state_value = api.get_long(product, 8)
                    signature_value = api.get_long(product, 9)
                    remediation_path = api.get_bstr(product, 10)
                    timestamp = api.get_bstr(product, 11)

                    products.append(
                        WindowsAntivirusProduct(
                            product_id=_stable_product_id(
                                name,
                                remediation_path,
                            ),
                            display_name=name or "Unnamed antivirus product",
                            state=_enum_or_none(
                                WindowsProductState,
                                state_value,
                            ),
                            signature_status=_enum_or_none(
                                WindowsSignatureStatus,
                                signature_value,
                            ),
                            remediation_path=remediation_path,
                            state_timestamp=timestamp,
                        )
                    )
                finally:
                    api.release(product)

            return tuple(products)
        finally:
            if product_list.value:
                api.release(product_list)
            if initialized:
                api.uninitialize_com()


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: UUID) -> "_Guid":
        raw = value.bytes_le
        return cls(
            int.from_bytes(raw[0:4], "little"),
            int.from_bytes(raw[4:6], "little"),
            int.from_bytes(raw[6:8], "little"),
            (ctypes.c_ubyte * 8)(*raw[8:16]),
        )


class _ComApi:
    _COINIT_APARTMENTTHREADED = 0x2
    _CLSCTX_INPROC_SERVER = 0x1
    _RPC_E_CHANGED_MODE = -2147417850

    def __init__(self) -> None:
        self._ole32 = ctypes.OleDLL("ole32")
        self._oleaut32 = ctypes.OleDLL("oleaut32")
        self._hresult_type = ctypes.c_long
        self._method_type = ctypes.WINFUNCTYPE

        self._ole32.CoInitializeEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        self._ole32.CoInitializeEx.restype = self._hresult_type
        self._ole32.CoUninitialize.argtypes = []
        self._ole32.CoUninitialize.restype = None

        self._ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._ole32.CoCreateInstance.restype = self._hresult_type

        self._oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
        self._oleaut32.SysFreeString.restype = None

    def initialize_com(self) -> bool:
        result = self._ole32.CoInitializeEx(
            None,
            self._COINIT_APARTMENTTHREADED,
        )
        if result in (0, 1):
            return True
        if result == self._RPC_E_CHANGED_MODE:
            return False
        self._check_hresult(result, "CoInitializeEx")
        return False

    def uninitialize_com(self) -> None:
        self._ole32.CoUninitialize()

    def create_product_list(self, output: ctypes.c_void_p) -> None:
        clsid = _Guid.from_uuid(
            NativeWindowsSecurityCenter._CLSID_PRODUCT_LIST
        )
        iid = _Guid.from_uuid(
            NativeWindowsSecurityCenter._IID_PRODUCT_LIST
        )
        result = self._ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            self._CLSCTX_INPROC_SERVER,
            ctypes.byref(iid),
            ctypes.byref(output),
        )
        self._check_hresult(result, "CoCreateInstance(WSCProductList)")

    def initialize_product_list(
        self,
        interface: ctypes.c_void_p,
        provider: int,
    ) -> None:
        function = self._method(
            interface,
            7,
            self._hresult_type,
            ctypes.c_ulong,
        )
        result = function(interface, ctypes.c_ulong(provider))
        self._check_hresult(result, "IWSCProductList.Initialize")

    def get_count(self, interface: ctypes.c_void_p) -> int:
        output = ctypes.c_long()
        function = self._method(
            interface,
            8,
            self._hresult_type,
            ctypes.POINTER(ctypes.c_long),
        )
        result = function(interface, ctypes.byref(output))
        self._check_hresult(result, "IWSCProductList.get_Count")
        return int(output.value)

    def get_item(
        self,
        interface: ctypes.c_void_p,
        index: int,
    ) -> ctypes.c_void_p:
        output = ctypes.c_void_p()
        function = self._method(
            interface,
            9,
            self._hresult_type,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
        )
        result = function(
            interface,
            ctypes.c_ulong(index),
            ctypes.byref(output),
        )
        self._check_hresult(result, "IWSCProductList.get_Item")
        return output

    def get_long(self, interface: ctypes.c_void_p, index: int) -> int:
        output = ctypes.c_long()
        function = self._method(
            interface,
            index,
            self._hresult_type,
            ctypes.POINTER(ctypes.c_long),
        )
        result = function(interface, ctypes.byref(output))
        self._check_hresult(result, f"IWscProduct method {index}")
        return int(output.value)

    def get_bstr(self, interface: ctypes.c_void_p, index: int) -> str:
        output = ctypes.c_void_p()
        function = self._method(
            interface,
            index,
            self._hresult_type,
            ctypes.POINTER(ctypes.c_void_p),
        )
        result = function(interface, ctypes.byref(output))
        self._check_hresult(result, f"IWscProduct method {index}")
        if not output.value:
            return ""
        try:
            return ctypes.wstring_at(output.value)
        finally:
            self._oleaut32.SysFreeString(output)

    def release(self, interface: ctypes.c_void_p) -> None:
        if not interface.value:
            return
        function = self._method(
            interface,
            2,
            ctypes.c_ulong,
        )
        function(interface)

    def _method(
        self,
        interface: ctypes.c_void_p,
        index: int,
        result_type,
        *argument_types,
    ):
        vtable_pointer = ctypes.cast(
            interface,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        )
        address = vtable_pointer.contents[index]
        prototype = self._method_type(
            result_type,
            ctypes.c_void_p,
            *argument_types,
        )
        return prototype(address)

    @staticmethod
    def _check_hresult(result: int, operation: str) -> None:
        if result < 0:
            code = result & 0xFFFFFFFF
            raise WindowsSecurityCenterError(
                f"{operation} failed with HRESULT 0x{code:08X}"
            )


def _enum_or_none(enum_type, value: int):
    try:
        return enum_type(value)
    except ValueError:
        return None


def _stable_product_id(name: str, remediation_path: str) -> str:
    normalized = f"{name.strip().lower()}|{remediation_path.strip().lower()}"
    return uuid5(NAMESPACE_URL, normalized).hex
