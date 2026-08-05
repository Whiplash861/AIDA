from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import psutil

from aida.artificer.events import make_event
from aida.artificer.runtime import get_active_artificer
from aida.audio.tones import play_end_tone, play_start_tone
from aida.audio.voice import speak_text
from aida.brain.llm_client import AIDABrain
from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.frontend.command_router import CommandRouter, CommandType
from aida.frontend.commands.artificer import ArtificerCommandExecutor
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.commands.security import SecurityScanExecutor
from aida.logging_utils import get_logger
from aida.ui.navigation import (
    default_search_roots,
    find_file_by_name,
    open_explorer_select,
    open_settings,
)

log = get_logger(__name__)


def clean_for_tts(text: str) -> str:
    cleaned = (text or "").replace("|", ". ").replace(":", ". ")
    cleaned = cleaned.replace(".exe", " executable")
    cleaned = cleaned.replace(".lnk", " shortcut")
    cleaned = cleaned.replace(".msi", " installer")
    cleaned = re.sub(r"[A-Za-z]:\\[^\s]+", "file path", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def aida_say_text(text: str, config: AidaConfig) -> None:
    message = (text or "").strip()
    if not message:
        return
    print(f"[AIDA] {message}")
    play_start_tone(config, blocking=True)
    speak_text(clean_for_tts(message), config)
    play_end_tone(config, blocking=True)


@dataclass(frozen=True, slots=True)
class Intent:
    name: str
    arg: str = ""


_SETTINGS_PATTERN = re.compile(
    r"(?:show me|open|take me to|go to|navigate to)\s+"
    r"(?P<target>bluetooth|wifi|wi-fi|network|windows update|updates|update|apps|"
    r"apps and features|display|sound|privacy)(?:\s+settings)?\b",
    re.IGNORECASE,
)
_FILE_PATTERNS = (
    re.compile(r"(?:can't find|cannot find|can not find|cant find)\s+(?P<file>.+)$", re.I),
    re.compile(r"(?:help me find|show me where|where is|where's)\s+(?P<file>.+)$", re.I),
    re.compile(r"(?:find|locate)\s+(?:the\s+)?(?:file\s+)?(?P<file>.+)$", re.I),
)


def detect_intent(user_text: str) -> Optional[Intent]:
    text = (user_text or "").strip()
    if not text:
        return None
    settings_match = _SETTINGS_PATTERN.search(text)
    if settings_match:
        target = settings_match.group("target").lower().replace("-", "").replace(" ", "_")
        aliases = {
            "wifi": "wifi",
            "windows_update": "windows_update",
            "updates": "windows_update",
            "update": "windows_update",
            "apps": "apps_features",
            "apps_and_features": "apps_features",
        }
        return Intent("open_settings", aliases.get(target, target))
    for pattern in _FILE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = (match.group("file") or "").strip()
        raw = re.sub(r"^(?:the\s+file|file)\s+", "", raw, flags=re.I)
        raw = re.sub(
            r"\b(?:in my files|on my desktop|in my folders|on my computer|please|for me)\b",
            "",
            raw,
            flags=re.I,
        ).strip(" .!?\"'")
        if raw:
            return Intent("find_file", raw)
    return None


class CLIResourceMonitor:
    """Independent resource monitor that continues while console input blocks."""

    def __init__(
        self,
        config: AidaConfig,
        *,
        interval_seconds: int = 30,
        memory_threshold: float = 85.0,
        cpu_threshold: float = 90.0,
        alert_cooldown_seconds: int = 300,
    ) -> None:
        self.config = config
        self.interval_seconds = max(5, interval_seconds)
        self.memory_threshold = memory_threshold
        self.cpu_threshold = cpu_threshold
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_alert = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="AIDA-CLI-Resource-Monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            memory = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent(interval=1.0)
            breached = []
            if memory >= self.memory_threshold:
                breached.append(f"memory {memory:.1f} percent")
            if cpu >= self.cpu_threshold:
                breached.append(f"CPU {cpu:.1f} percent")
            if not breached:
                continue
            now = time.monotonic()
            if now - self._last_alert < self.alert_cooldown_seconds:
                continue
            self._last_alert = now
            message = "Elevated resource pressure detected. " + " and ".join(breached) + "."
            aida_say_text(message, self.config)
            engine = get_active_artificer()
            if engine is not None:
                engine.event_bus.publish(
                    make_event(
                        source="monitor.resources",
                        event_type="threshold_breach",
                        status="warning",
                        aida_version=self.config.version,
                        platform_profile_id=(
                            engine.platform_profile.profile_id
                            if engine.platform_profile
                            else "unknown"
                        ),
                        metadata={"memory_percent": memory, "cpu_percent": cpu},
                    )
                )


def _summarize_findings(findings: List[Finding], limit: int = 5) -> str:
    if not findings:
        return "No findings were returned."
    lines: List[str] = []
    for finding in findings[:limit]:
        line = finding.title
        if finding.detail:
            line += f": {finding.detail}"
        lines.append(line)
    return "\n".join(lines)


def _friendly_location(path: Path) -> str:
    normalized = str(path).casefold()
    for name in ("desktop", "downloads", "documents", "pictures"):
        if f"/{name}/" in normalized.replace("\\", "/"):
            return name.title()
    return "Other"


def _handle_find_file(name: str, user_text: str, config: AidaConfig) -> None:
    roots = default_search_roots()
    if "desktop" in user_text.casefold():
        roots = [root for root in roots if root.name.casefold() == "desktop"] or roots
    aida_say_text("Searching approved common folders by file name.", config)
    matches, scanned = find_file_by_name(name, roots=roots)
    if not matches:
        aida_say_text(
            f"No matches located. Directories scanned: {scanned}. "
            "Provide the complete file name and extension for a narrower search.",
            config,
        )
        return
    if len(matches) == 1:
        aida_say_text("File located. Opening the platform file manager.", config)
        open_explorer_select(matches[0])
        return
    lines = ["Multiple matches detected:"]
    for index, path in enumerate(matches, start=1):
        lines.append(f"{index}. {path.name} ({_friendly_location(path)})")
    lines.append("Reply with the number to reveal the correct file.")
    aida_say_text("\n".join(lines), config)
    try:
        selection = input("User> ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if selection.isdigit() and 1 <= int(selection) <= len(matches):
        open_explorer_select(matches[int(selection) - 1])


def start_cli_loop(
    config: AidaConfig,
    initial_findings: List[Finding],
    brain: AIDABrain,
) -> None:
    router = CommandRouter()
    engine = get_active_artificer()
    executors = {
        CommandType.QUICKSCAN: QuickscanExecutor(config),
        CommandType.PERFORMANCE_SCAN: PerformanceScanExecutor(engine),
        CommandType.SECURITY_SCAN: SecurityScanExecutor(config),
    }
    if engine is not None:
        for command_type in (
            CommandType.ARTIFICER_STATUS,
            CommandType.ARTIFICER_REVIEW,
            CommandType.ARTIFICER_FINDINGS,
            CommandType.ARTIFICER_COMPATIBILITY,
            CommandType.ARTIFICER_EXPORT,
            CommandType.ARTIFICER_OPEN,
        ):
            executors[command_type] = ArtificerCommandExecutor(engine, command_type)

    recent_findings = list(initial_findings)
    context_lines: List[str] = []
    monitor = CLIResourceMonitor(config)
    monitor.start()
    aida_say_text(
        "Analytical Intelligent Diagnostic Agent is activated. Artificer Engine is observing. Awaiting directive.",
        config,
    )

    try:
        while True:
            try:
                user_input = input("User> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.casefold() in {"exit", "quit", "shutdown"}:
                break

            routed = router.route(user_input)
            if routed is not None:
                executor = executors.get(routed.command_type)
                if executor is None:
                    aida_say_text("Recognized command is unavailable in this runtime.", config)
                    continue
                result = executor.execute()
                if result.ui_action == "open_artificer":
                    aida_say_text(
                        "The Artificer panel is available in the desktop frontend. Current status follows.",
                        config,
                    )
                    if engine is not None:
                        status_result = ArtificerCommandExecutor(
                            engine, CommandType.ARTIFICER_STATUS
                        ).execute()
                        aida_say_text(status_result.transcript_text, config)
                    continue
                aida_say_text(result.transcript_text, config)
                if routed.command_type in {
                    CommandType.QUICKSCAN,
                    CommandType.PERFORMANCE_SCAN,
                    CommandType.SECURITY_SCAN,
                }:
                    if routed.command_type is CommandType.QUICKSCAN:
                        recent_findings = []
                    context_lines.append(result.transcript_text[:2000])
                    context_lines = context_lines[-6:]
                continue

            intent = detect_intent(user_input)
            if intent and intent.name == "open_settings":
                try:
                    open_settings(intent.arg)
                    aida_say_text("Opening the requested platform settings target.", config)
                except Exception as exc:
                    aida_say_text(f"Settings navigation is unavailable. {exc}", config)
                continue
            if intent and intent.name == "find_file":
                _handle_find_file(intent.arg, user_input, config)
                continue

            context: List[str] = list(context_lines[-6:])
            if recent_findings:
                context.append("Recent diagnostic findings:\n" + _summarize_findings(recent_findings))
            try:
                response = brain.think(user_input, context=context)
            except Exception as exc:
                log.exception("Brain failure: %s", exc)
                response = "Processing failure. Provide additional detail. Further analysis required."
            aida_say_text(response, config)
            context_lines.extend([f"User: {user_input}", f"AIDA: {response}"])
            context_lines = context_lines[-12:]
    finally:
        monitor.stop()
        aida_say_text("Shutdown acknowledged. Session terminated.", config)
