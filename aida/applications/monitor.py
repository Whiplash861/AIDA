
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Iterable

from aida.reporting import render_report

from aida.applications.models import (
    ApplicationHealthAssessment,
    ApplicationHealthState,
    ApplicationProcessObservation,
)


class ApplicationHealthMonitor:
    """Read-only process health observer with conservative classification."""

    def __init__(self, process_source: Any | None = None) -> None:
        self._process_source = process_source
        self._last_errors = 0

    def inspect(self, application_name: str) -> ApplicationHealthAssessment:
        clean_name = application_name.strip()
        if not clean_name:
            raise ValueError("application_name cannot be empty")
        self._last_errors = 0
        try:
            observations = tuple(self._observe(clean_name))
        except (OSError, RuntimeError):
            observations = ()
            self._last_errors += 1
        if not observations:
            return ApplicationHealthAssessment(
                application_name=clean_name,
                state=ApplicationHealthState.UNKNOWN,
                confidence=0.2 if self._last_errors else 0.7,
                summary=f"{clean_name} process visibility is incomplete." if self._last_errors else f"No matching {clean_name} process was observed.",
                observations=(),
                evidence=("Process access failed; absence cannot be established." if self._last_errors else "No matching process was found in the available snapshot.",),
                recommendations=(
                    "Start the application and repeat the health inspection.",
                ),
            )

        evidence: list[str] = []
        recommendations: list[str] = []
        total_memory = sum(item.memory_bytes for item in observations if item.memory_bytes is not None)
        total_cpu = sum(item.cpu_percent for item in observations if item.cpu_percent is not None)
        resources_complete = all(item.memory_bytes is not None and item.cpu_percent is not None for item in observations)
        any_unresponsive = any(item.responding is False for item in observations)

        if any_unresponsive:
            state = ApplicationHealthState.UNRESPONSIVE
            confidence = 0.93
            evidence.append("At least one matching process is not responding.")
            recommendations.extend(
                (
                    "Attempt a graceful application close first.",
                    "Warn about unsaved work before any forced termination.",
                )
            )
        elif total_cpu >= 90.0:
            state = ApplicationHealthState.RESOURCE_INTENSIVE
            confidence = 0.72
            evidence.append(
                f"Matching processes are using approximately {total_cpu:.1f} percent CPU."
            )
            recommendations.append(
                "Observe the process over time before treating a temporary spike as a fault."
            )
        elif total_memory >= 4 * 1024**3:
            state = ApplicationHealthState.RESOURCE_INTENSIVE
            confidence = 0.68
            evidence.append(
                f"Matching processes are using approximately {total_memory / 1024**3:.1f} GB of memory."
            )
            recommendations.append(
                "Compare sustained usage with the application's local baseline."
            )
        else:
            state = ApplicationHealthState.HEALTHY if resources_complete and all(item.responding is True for item in observations) else ApplicationHealthState.UNKNOWN
            confidence = 0.75 if state is ApplicationHealthState.HEALTHY else 0.4
            evidence.append(
                "No extreme resource condition was observed in the available measurements; process scheduling state alone does not establish application responsiveness."
            )
            recommendations.append(
                "Continue observing if the user reports intermittent failures."
            )

        if not resources_complete:
            confidence = min(confidence, 0.5)
            evidence.append("Processor or memory measurements were unavailable for some matching processes; missing values were not treated as zero use.")
        if self._last_errors:
            confidence = min(confidence, 0.5)
            evidence.append("Some process observations were inaccessible or incomplete.")
        evidence.append(f"Matching process count: {len(observations)}.")
        return ApplicationHealthAssessment(
            application_name=clean_name,
            state=state,
            confidence=confidence,
            summary=_summary(clean_name, state),
            observations=observations,
            evidence=tuple(evidence),
            recommendations=tuple(recommendations),
        )

    def _observe(
        self,
        application_name: str,
    ) -> Iterable[ApplicationProcessObservation]:
        psutil = self._process_source or _import_psutil()
        lowered = application_name.lower()
        for process in psutil.process_iter(
            [
                "pid",
                "name",
                "exe",
                "cpu_percent",
                "memory_info",
                "num_threads",
                "create_time",
                "io_counters",
            ]
        ):
            try:
                info = process.info
                name = str(info.get("name") or "")
                executable = str(info.get("exe") or "")
                if lowered not in name.lower() and lowered not in Path(executable).stem.lower():
                    continue
                memory_info = info.get("memory_info")
                io_counters = info.get("io_counters")
                responding = _responding(process)
                yield ApplicationProcessObservation(
                    pid=int(info["pid"]),
                    name=name or Path(executable).name or application_name,
                    executable=Path(executable) if executable else None,
                    responding=responding,
                    cpu_percent=_resource_value(info.get("cpu_percent")),
                    memory_bytes=_resource_value(getattr(memory_info, "rss", None), integer=True),
                    thread_count=int(info.get("num_threads") or 0),
                    handle_count=_optional_call(process, "num_handles"),
                    read_bytes=(
                        int(getattr(io_counters, "read_bytes", 0))
                        if io_counters is not None
                        else None
                    ),
                    write_bytes=(
                        int(getattr(io_counters, "write_bytes", 0))
                        if io_counters is not None
                        else None
                    ),
                    create_time=_timestamp(info.get("create_time")),
                )
            except Exception:
                self._last_errors += 1
                continue


def render_application_health(assessment: ApplicationHealthAssessment) -> str:
    unknown = ["This process snapshot does not test every application feature or establish the cause of a crash. High resource use alone is not proof of damage."]
    if not assessment.observations:
        unknown.append("There are no matching process observations to assess. The application may be closed, named differently, or unavailable to this check.")
    elif any(item.responding is None for item in assessment.observations):
        unknown.append("Window responsiveness was not checked for every matching process; a running process can still have a frozen window.")
    if any(getattr(item, "cpu_percent", None) is None or getattr(item, "memory_bytes", None) is None for item in assessment.observations):
        unknown.append("Processor or memory use is unknown for some matching processes. Missing measurements do not establish low usage.")
    if not assessment.baseline_comparison:
        unknown.append("No comparison with this application's normal behavior was supplied.")
    return render_report(
        f"Application health: {assessment.application_name}",
        found=[assessment.summary, *assessment.evidence], unknown=unknown,
        next_steps=assessment.recommendations or ("Repeat the health check while the problem is occurring.",),
        details=[f"Recorded state: {assessment.state.value}; internal confidence estimate: {assessment.confidence:.0%}. This is not a measured probability of damage."],
    )


def _resource_value(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return int(value) if integer else float(value)


def _summary(name: str, state: ApplicationHealthState) -> str:
    return {
        ApplicationHealthState.HEALTHY: (
            f"{name} is running without an obvious current fault."
        ),
        ApplicationHealthState.RESOURCE_INTENSIVE: (
            f"{name} is consuming substantial resources and should be observed over time."
        ),
        ApplicationHealthState.UNRESPONSIVE: (
            f"{name} has at least one process that is not responding."
        ),
    }.get(state, f"{name} requires additional inspection.")


def _import_psutil() -> Any:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "Application health monitoring requires psutil."
        ) from exc
    return psutil


def _responding(process: Any) -> bool | None:
    # psutil status describes scheduling/liveness, not GUI message handling.
    # A provider may supply an actual responsiveness probe; otherwise unknown.
    method = getattr(process, "is_responding", None)
    if not callable(method):
        return None
    try:
        result = method()
        return result if isinstance(result, bool) else None
    except Exception:
        return None


def _optional_call(process: Any, name: str) -> int | None:
    method = getattr(process, name, None)
    if not callable(method):
        return None
    try:
        return int(method())
    except Exception:
        return None


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
