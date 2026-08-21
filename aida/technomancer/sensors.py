from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import psutil

from aida.technomancer.models import HardwareInventory, TelemetrySample


def machine_id() -> str:
    raw = f"{platform.node()}|{platform.system()}|{uuid.getnode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _windows_powershell_json(script: str, timeout: int = 8) -> Any:
    if os.name != "nt":
        return None
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"$ErrorActionPreference='SilentlyContinue'; {script} | ConvertTo-Json -Depth 5 -Compress",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, creationflags=creationflags)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _memory_type_name(value: Any) -> str | None:
    mapping = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}
    try:
        return mapping.get(int(value))
    except (TypeError, ValueError):
        return None


def collect_hardware_inventory() -> HardwareInventory:
    mid = machine_id()
    vm = psutil.virtual_memory()
    inv = HardwareInventory(
        machine_id=mid,
        system_manufacturer=platform.system(),
        system_model=platform.machine() or "Unknown",
        cpu_model=platform.processor() or platform.machine() or "Unknown",
        total_ram_gb=round(vm.total / (1024 ** 3), 2),
    )

    try:
        inv.disks = [f"{p.device} ({p.fstype or 'unknown'})" for p in psutil.disk_partitions(all=False)]
    except Exception:
        pass

    if os.name != "nt":
        return inv

    system = _windows_powershell_json("Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model")
    board = _windows_powershell_json("Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product")
    bios = _windows_powershell_json("Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion")
    cpu = _windows_powershell_json("Get-CimInstance Win32_Processor | Select-Object -First 1 Name")
    gpus = _windows_powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name")
    memory = _windows_powershell_json("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType,DeviceLocator")
    arrays = _windows_powershell_json("Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices,MaxCapacityEx,MaxCapacity")
    disks = _windows_powershell_json("Get-CimInstance Win32_DiskDrive | Select-Object Model,InterfaceType,Size")

    if isinstance(system, dict):
        inv.system_manufacturer = str(system.get("Manufacturer") or inv.system_manufacturer)
        inv.system_model = str(system.get("Model") or inv.system_model)
    if isinstance(board, dict):
        inv.board_manufacturer = str(board.get("Manufacturer") or inv.board_manufacturer)
        inv.board_model = str(board.get("Product") or inv.board_model)
    if isinstance(bios, dict):
        inv.bios_version = str(bios.get("SMBIOSBIOSVersion") or "") or None
    if isinstance(cpu, dict):
        inv.cpu_model = str(cpu.get("Name") or inv.cpu_model)

    inv.gpus = [str(item.get("Name")) for item in _as_list(gpus) if isinstance(item, dict) and item.get("Name")]

    mem_items = [item for item in _as_list(memory) if isinstance(item, dict)]
    if mem_items:
        inv.ram_slots_used = len(mem_items)
        mem_type = next((_memory_type_name(item.get("SMBIOSMemoryType")) for item in mem_items if _memory_type_name(item.get("SMBIOSMemoryType"))), None)
        inv.ram_generation = mem_type
        speeds = [int(item.get("ConfiguredClockSpeed") or item.get("Speed") or 0) for item in mem_items]
        speeds = [value for value in speeds if value > 0]
        inv.ram_speed_mhz = min(speeds) if speeds else None

    array_items = [item for item in _as_list(arrays) if isinstance(item, dict)]
    if array_items:
        inv.ram_slots_total = sum(int(item.get("MemoryDevices") or 0) for item in array_items) or None
        maximum_bytes = 0
        for item in array_items:
            max_ex = int(item.get("MaxCapacityEx") or 0)
            max_kb = int(item.get("MaxCapacity") or 0)
            maximum_bytes += max_ex if max_ex else max_kb * 1024
        inv.max_ram_gb = round(maximum_bytes / (1024 ** 3), 2) if maximum_bytes else None

    disk_items = [item for item in _as_list(disks) if isinstance(item, dict)]
    if disk_items:
        inv.disks = [f"{item.get('Model', 'Unknown')} ({item.get('InterfaceType', 'Unknown')})" for item in disk_items]

    return inv


def _gpu_metrics() -> tuple[float | None, float | None, float | None]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=4, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        return None, None, None
    if result.returncode != 0 or not result.stdout.strip():
        return None, None, None
    try:
        row = next(csv.reader(io.StringIO(result.stdout)))
        util, used, total, temp = [float(value.strip()) for value in row[:4]]
        return util, (used / total * 100.0 if total else None), temp
    except (ValueError, StopIteration, IndexError):
        return None, None, None


def _wifi_signal_windows() -> float | None:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (result.stdout or "").splitlines():
        if line.strip().lower().startswith("signal") and ":" in line:
            value = line.split(":", 1)[1].strip().rstrip("%")
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _idle_seconds_windows() -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:
        return None


def _windows_reliability_counts() -> tuple[int, int, int]:
    if os.name != "nt":
        return 0, 0, 0
    script = """
    $now=Get-Date;
    [PSCustomObject]@{
      AppCrashes=(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=$now.AddDays(-7)} -ErrorAction SilentlyContinue | Measure-Object).Count;
      ServiceFailures=(Get-WinEvent -FilterHashtable @{LogName='System'; Id=7000,7001,7009,7011; StartTime=$now.AddDays(-7)} -ErrorAction SilentlyContinue | Measure-Object).Count;
      UnexpectedShutdowns=(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41; StartTime=$now.AddDays(-30)} -ErrorAction SilentlyContinue | Measure-Object).Count
    }
    """
    data = _windows_powershell_json(script, timeout=10)
    if not isinstance(data, dict):
        return 0, 0, 0
    return int(data.get("AppCrashes") or 0), int(data.get("ServiceFailures") or 0), int(data.get("UnexpectedShutdowns") or 0)


def _storage_reliability_windows() -> tuple[int | None, int | None, float | None]:
    data = _windows_powershell_json("Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object -First 1 ReadErrorsTotal,WriteErrorsTotal,Wear", timeout=8)
    if not isinstance(data, dict):
        return None, None, None
    try:
        read_errors = int(data.get("ReadErrorsTotal")) if data.get("ReadErrorsTotal") is not None else None
    except (TypeError, ValueError):
        read_errors = None
    try:
        write_errors = int(data.get("WriteErrorsTotal")) if data.get("WriteErrorsTotal") is not None else None
    except (TypeError, ValueError):
        write_errors = None
    try:
        wear = float(data.get("Wear")) if data.get("Wear") is not None else None
    except (TypeError, ValueError):
        wear = None
    return read_errors, write_errors, wear


def collect_telemetry(context_level: str = "basic") -> TelemetrySample:
    mid = machine_id()
    cpu = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    root = Path.home().anchor or "/"
    disk = psutil.disk_usage(root)
    net = psutil.net_io_counters()
    battery = psutil.sensors_battery()
    gpu, vram, gpu_temp = _gpu_metrics()
    app_crashes, service_failures, shutdowns = _windows_reliability_counts()
    read_errors, write_errors, wear = _storage_reliability_windows()

    workload_context = None
    if context_level == "process":
        heavy: list[tuple[float, str]] = []
        for proc in psutil.process_iter(["name", "cpu_percent"]):
            try:
                heavy.append((float(proc.info.get("cpu_percent") or 0.0), str(proc.info.get("name") or "unknown")))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        heavy.sort(reverse=True)
        workload_context = ", ".join(name for value, name in heavy[:5] if value > 0.0) or None

    return TelemetrySample(
        timestamp=time.time(),
        machine_id=mid,
        cpu_percent=cpu,
        memory_percent=float(memory.percent),
        swap_percent=float(swap.percent),
        disk_percent=float(disk.percent),
        disk_free_gb=round(disk.free / (1024 ** 3), 2),
        process_count=len(psutil.pids()),
        gpu_percent=gpu,
        vram_percent=vram,
        gpu_temp_c=gpu_temp,
        battery_percent=float(battery.percent) if battery else None,
        battery_plugged=bool(battery.power_plugged) if battery else None,
        wifi_signal_percent=_wifi_signal_windows(),
        network_bytes_sent=int(net.bytes_sent),
        network_bytes_recv=int(net.bytes_recv),
        idle_seconds=_idle_seconds_windows(),
        context_level=context_level,
        workload_context=workload_context,
        unexpected_shutdowns_30d=shutdowns,
        app_crashes_7d=app_crashes,
        service_failures_7d=service_failures,
        storage_read_errors=read_errors,
        storage_write_errors=write_errors,
        storage_wear_percent=wear,
    )
