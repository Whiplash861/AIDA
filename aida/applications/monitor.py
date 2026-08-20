
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from aida.applications.models import (
    ApplicationHealthAssessment,
    ApplicationHealthState,
    ApplicationProcessObservation,
)


class ApplicationHealthMonitor:
    """Read-only process health observer with conservative classification."""

    def __init__(self, process_source: Any | None = None) -> None:
        self._process_source = process_source

    def inspect(self, application_name: str) -> ApplicationHealthAssessment:
        clean_name = application_name.strip()
        if not clean_name:
            raise ValueError("application_name cannot be empty")
        observations = tuple(self._observe(clean_name))
        if not observations:
            return ApplicationHealthAssessment(
                application_name=clean_name,
                state=ApplicationHealthState.UNKNOWN,
                confidence=0.95,
                summary=f"{clean_name} is not currently running.",
                observations=(),
                evidence=("No matching running process was found.",),
                recommendations=(
                    "Start the application and repeat the health inspection.",
                ),
            )

        evidence: list[str] = []
        recommendations: list[str] = []
        total_memory = sum(item.memory_bytes for item in observations)
        total_cpu = sum(item.cpu_percent for item in observations)
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
            state = ApplicationHealthState.HEALTHY
            confidence = 0.75
            evidence.append(
                "No current unresponsive state or extreme resource condition was observed."
            )
            recommendations.append(
                "Continue observing if the user reports intermittent failures."
            )

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
                    cpu_percent=float(info.get("cpu_percent") or 0.0),
                    memory_bytes=int(
                        getattr(memory_info, "rss", 0) if memory_info else 0
                    ),
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
                continue


def render_application_health(
    assessment: ApplicationHealthAssessment,
) -> str:
    lines = [
        "APPLICATION HEALTH REPORT",
        "",
        f"Application: {assessment.application_name}",
        f"State: {assessment.state.value.replace('_', ' ').title()}",
        f"Confidence: {round(assessment.confidence * 100)} percent",
        f"Summary: {assessment.summary}",
    ]
    if assessment.evidence:
        lines.extend(["", "Observed evidence:"])
        lines.extend(f"- {item}" for item in assessment.evidence)
    if assessment.recommendations:
        lines.extend(["", "Recommended next steps:"])
        lines.extend(f"- {item}" for item in assessment.recommendations)
    lines.extend(
        [
            "",
            "A high resource value alone is not treated as proof that the application is damaged.",
        ]
    )
    return "\n".join(lines)


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
    method = getattr(process, "status", None)
    if not callable(method):
        return None
    try:
        status = str(method()).lower()
    except Exception:
        return None
    return status not in {"stopped", "zombie", "dead"}


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
