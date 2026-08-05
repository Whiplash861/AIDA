from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aida.artificer.models import TelemetryLevel, utc_now


@dataclass(frozen=True, slots=True)
class ConsentState:
    telemetry_level: TelemetryLevel = TelemetryLevel.LOCAL_ONLY
    allow_crash_reports: bool = False
    allow_compatibility_reports: bool = False
    allow_raw_diagnostic_bundles: bool = False
    updated_at_utc: str = ""


class ConsentManager:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    @property
    def state(self) -> ConsentState:
        return self._state

    def set_level(
        self,
        level: TelemetryLevel,
        *,
        allow_crash_reports: bool | None = None,
        allow_compatibility_reports: bool | None = None,
        allow_raw_diagnostic_bundles: bool | None = None,
    ) -> ConsentState:
        current = self._state
        self._state = ConsentState(
            telemetry_level=level,
            allow_crash_reports=(
                current.allow_crash_reports
                if allow_crash_reports is None
                else allow_crash_reports
            ),
            allow_compatibility_reports=(
                current.allow_compatibility_reports
                if allow_compatibility_reports is None
                else allow_compatibility_reports
            ),
            allow_raw_diagnostic_bundles=(
                current.allow_raw_diagnostic_bundles
                if allow_raw_diagnostic_bundles is None
                else allow_raw_diagnostic_bundles
            ),
            updated_at_utc=utc_now().isoformat(),
        )
        self._save()
        return self._state

    def permits(self, report_type: str) -> bool:
        state = self._state
        if state.telemetry_level is TelemetryLevel.LOCAL_ONLY:
            return False
        if report_type == "critical_crash":
            return state.allow_crash_reports
        if report_type == "compatibility_regression":
            return state.allow_compatibility_reports
        if report_type == "full_diagnostic":
            return (
                state.telemetry_level is TelemetryLevel.FULL_DIAGNOSTIC
                and state.allow_raw_diagnostic_bundles
            )
        return state.telemetry_level in {
            TelemetryLevel.ANONYMOUS,
            TelemetryLevel.PSEUDONYMOUS,
            TelemetryLevel.FULL_DIAGNOSTIC,
        }

    def _load(self) -> ConsentState:
        if not self.path.exists():
            return ConsentState(updated_at_utc=utc_now().isoformat())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return ConsentState(
                telemetry_level=TelemetryLevel(
                    payload.get("telemetry_level", TelemetryLevel.LOCAL_ONLY.value)
                ),
                allow_crash_reports=bool(payload.get("allow_crash_reports", False)),
                allow_compatibility_reports=bool(
                    payload.get("allow_compatibility_reports", False)
                ),
                allow_raw_diagnostic_bundles=bool(
                    payload.get("allow_raw_diagnostic_bundles", False)
                ),
                updated_at_utc=str(payload.get("updated_at_utc", "")),
            )
        except (OSError, ValueError, TypeError):
            return ConsentState(updated_at_utc=utc_now().isoformat())

    def _save(self) -> None:
        payload = {
            "telemetry_level": self._state.telemetry_level.value,
            "allow_crash_reports": self._state.allow_crash_reports,
            "allow_compatibility_reports": self._state.allow_compatibility_reports,
            "allow_raw_diagnostic_bundles": self._state.allow_raw_diagnostic_bundles,
            "updated_at_utc": self._state.updated_at_utc,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)
