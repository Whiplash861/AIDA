from __future__ import annotations

import getpass
import time
from collections.abc import Callable
from pathlib import Path

from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.security.models import (
    ProviderDetection,
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.orchestrator import (
    ProviderCapabilityError,
    SecurityOrchestrator,
)
from aida.security.policy import SecurityPolicy
from aida.security.windows.discovery import (
    WindowsAntivirusDiscovery,
    WindowsProviderDiscovery,
)


DiscoveryFunction = Callable[[], WindowsProviderDiscovery]
SleepFunction = Callable[[float], None]
PathExistsFunction = Callable[[Path], bool]


def _discover_windows_provider() -> WindowsProviderDiscovery:
    return WindowsAntivirusDiscovery().discover()


class SecurityStatusExecutor(CommandExecutor):
    def __init__(
        self,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
    ) -> None:
        self._discover = discovery_function

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def task_name(self) -> str:
        return "security_status"

    @property
    def start_message(self) -> str:
        return "Reading Windows antivirus status."

    def execute(self) -> CommandResult:
        try:
            discovery = self._discover()
            status = discovery.provider.get_status()
        except (OSError, RuntimeError) as exc:
            return _failure_result(
                "Antivirus status could not be read.",
                exc,
            )

        lines = [
            "Antivirus status complete.",
            "",
        ]

        if discovery.products:
            lines.append("Registered products:")
            for product in discovery.products:
                state = (
                    product.state.name
                    if product.state is not None
                    else "UNKNOWN"
                )
                signatures = _yes_no_unknown(
                    product.signatures_current
                )
                lines.append(
                    f"- {product.display_name}: "
                    f"state={state}, signatures current={signatures}"
                )
        else:
            lines.append(
                "Windows Security Center reported no registered "
                "antivirus products."
            )

        lines.extend(
            [
                "",
                f"Selected adapter: {discovery.provider.display_name}",
                f"Active: {_yes_no_unknown(status.active)}",
                f"Healthy: {_yes_no_unknown(status.healthy)}",
                (
                    "Real-time protection: "
                    f"{_yes_no_unknown(status.real_time_protection)}"
                ),
                (
                    "Signatures current: "
                    f"{_yes_no_unknown(status.signatures_current)}"
                ),
            ]
        )

        if discovery.detail:
            lines.append(f"Discovery: {discovery.detail}")
        if status.detail:
            lines.append(f"Provider detail: {status.detail}")

        speech = (
            f"{discovery.provider.display_name} status complete. "
            f"Active {_spoken_bool(status.active)}. "
            f"Healthy {_spoken_bool(status.healthy)}."
        )

        return CommandResult(
            transcript_text="\n".join(lines),
            speech_text=speech,
        )


class SecurityScanExecutor(CommandExecutor):
    def __init__(
        self,
        mode: SecurityScanMode,
        authorization_reason: str,
        target_path: str | None = None,
        discovery_function: DiscoveryFunction = _discover_windows_provider,
        sleep_function: SleepFunction = time.sleep,
        path_exists: PathExistsFunction | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._mode = mode
        self._authorization_reason = authorization_reason
        self._target_path = target_path
        self._discover = discovery_function
        self._sleep = sleep_function
        self._path_exists = path_exists or (lambda path: path.exists())
        self._poll_interval_seconds = max(0.05, poll_interval_seconds)

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def task_name(self) -> str:
        return {
            SecurityScanMode.SURFACE: "security_surface_scan",
            SecurityScanMode.DEEP: "security_deep_scan",
            SecurityScanMode.FULL_SWEEP: "security_full_sweep",
        }[self._mode]

    @property
    def start_message(self) -> str:
        return {
            SecurityScanMode.SURFACE: (
                "Surface-level security scan authorized and starting."
            ),
            SecurityScanMode.DEEP: (
                "Targeted deep security scan authorized and starting."
            ),
            SecurityScanMode.FULL_SWEEP: (
                "Full-system sweep directly authorized and starting."
            ),
        }[self._mode]

    def execute(self) -> CommandResult:
        scope_or_result = self._build_scope()
        if isinstance(scope_or_result, CommandResult):
            return scope_or_result
        scope = scope_or_result

        try:
            discovery = self._discover()
            provider_status = discovery.provider.get_status()

            if not provider_status.active:
                return CommandResult(
                    transcript_text=(
                        f"{self._scan_label()} was not started.\n\n"
                        f"{discovery.detail}\n"
                        "The selected antivirus adapter is not active."
                    ),
                    speech_text=(
                        "Security scan not started. "
                        "No active supported antivirus adapter is available."
                    ),
                )

            request = SecurityScanRequest(
                mode=self._mode,
                authorization=SecurityAuthorization(
                    granted=True,
                    granted_by=_local_user_name(),
                    reason=self._authorization_reason.strip()
                    or "Direct frontend security command",
                    autonomous=False,
                ),
                scope=scope,
                local_evidence_only=True,
            )
            orchestrator = SecurityOrchestrator(
                provider=discovery.provider,
                policy=SecurityPolicy(),
            )
            handle = orchestrator.start(request)

            while True:
                outcome = orchestrator.poll(handle)
                if outcome.status.state not in {
                    SecurityScanState.PENDING,
                    SecurityScanState.RUNNING,
                }:
                    break
                self._sleep(self._poll_interval_seconds)

        except ProviderCapabilityError as exc:
            return _failure_result(
                f"{self._scan_label()} was not started.",
                exc,
            )
        except (OSError, RuntimeError) as exc:
            return _failure_result(
                f"{self._scan_label()} could not complete.",
                exc,
            )

        if outcome.status.state is SecurityScanState.COMPLETED:
            return self._completed_result(
                provider_name=discovery.provider.display_name,
                detections=outcome.detections,
            )

        detail = outcome.status.detail or "No provider detail was returned."
        return CommandResult(
            transcript_text=(
                f"{self._scan_label()} did not complete.\n\n"
                f"State: {outcome.status.state.name}\n"
                f"Provider detail: {detail}"
            ),
            speech_text=(
                f"{self._scan_label()} did not complete. "
                "Review the local transcript for provider details."
            ),
        )

    def _build_scope(self) -> ScanScope | CommandResult:
        if self._mode is SecurityScanMode.SURFACE:
            return ScanScope()

        if self._mode is SecurityScanMode.FULL_SWEEP:
            return ScanScope(include_fixed_volumes=True)

        if not self._target_path:
            return CommandResult(
                transcript_text=(
                    "Deep security scan was not started.\n\n"
                    "Provide one explicit local file or folder path. "
                    'Example: Deep scan "C:\\Users\\Austin\\Downloads"'
                ),
                speech_text=(
                    "Deep scan not started. "
                    "Provide an explicit file or folder path."
                ),
            )

        target = Path(self._target_path).expanduser()
        if not self._path_exists(target):
            return CommandResult(
                transcript_text=(
                    "Deep security scan was not started.\n\n"
                    "The requested local path does not exist or is "
                    "not currently accessible."
                ),
                speech_text=(
                    "Deep scan not started. "
                    "The requested path is not accessible."
                ),
            )

        return ScanScope(paths=(target,))

    def _completed_result(
        self,
        provider_name: str,
        detections: tuple[ProviderDetection, ...],
    ) -> CommandResult:
        lines = [
            f"{self._scan_label()} complete.",
            "",
            f"Provider: {provider_name}",
        ]

        if not detections:
            lines.append(
                "Result: The provider reported no detections "
                "for this scan."
            )
            speech = (
                f"{self._scan_label()} complete. "
                "The provider reported no detections."
            )
        else:
            lines.append(
                f"Detections reported: {len(detections)}"
            )
            lines.append("")
            for index, detection in enumerate(detections, start=1):
                lines.extend(
                    _format_detection(index, detection)
                )
            speech = (
                f"{self._scan_label()} complete. "
                f"{len(detections)} detections were reported. "
                "Review the local transcript."
            )

        lines.extend(
            [
                "",
                (
                    "Security command details are stored locally and "
                    "excluded from language-model context."
                ),
            ]
        )

        return CommandResult(
            transcript_text="\n".join(lines),
            speech_text=speech,
        )

    def _scan_label(self) -> str:
        return {
            SecurityScanMode.SURFACE: "Surface-level security scan",
            SecurityScanMode.DEEP: "Deep security scan",
            SecurityScanMode.FULL_SWEEP: "Full-system sweep",
        }[self._mode]


def _format_detection(
    index: int,
    detection: ProviderDetection,
) -> list[str]:
    lines = [
        f"{index}. {detection.name}",
        f"   Severity: {detection.severity.name}",
        f"   Source: {detection.source}",
    ]
    if detection.file_path is not None:
        lines.append(
            f"   Resource: {detection.file_path}"
        )
    if detection.detail:
        lines.append(
            f"   Detail: {detection.detail}"
        )
    return lines


def _failure_result(
    heading: str,
    exc: BaseException,
) -> CommandResult:
    detail = str(exc).strip() or type(exc).__name__
    return CommandResult(
        transcript_text=f"{heading}\n\nReason: {detail}",
        speech_text=(
            f"{heading} Review the local transcript for details."
        ),
    )


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _spoken_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "confirmed" if value else "not confirmed"


def _local_user_name() -> str:
    try:
        name = getpass.getuser().strip()
    except (ImportError, KeyError, OSError):
        name = ""
    return name or "local frontend user"
