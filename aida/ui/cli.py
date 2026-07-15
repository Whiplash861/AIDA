from __future__ import annotations

import os
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

from aida.config import AidaConfig
from aida.diagnostics.base import Finding
from aida.diagnostics.system_scan import run_file_scan, run_full_diagnostics, run_quickscan
from aida.logging_utils import get_logger
from aida.audio.voice import speak_text
from aida.audio.tones import play_start_tone, play_end_tone
from aida.brain.llm_client import AIDABrain
from aida.ui.navigation import (
    find_file_by_name,
    open_explorer_select,
    open_settings,
    default_search_roots,
)
from aida.ui.settings_targets import SETTINGS_URIS

log = get_logger(__name__)


def clean_for_tts(text: str) -> str:
    t = text

    # Replace symbols with natural pauses
    t = t.replace("|", ". ")
    t = t.replace(":", ". ")

    # Clean file extensions
    t = t.replace(".exe", " executable")
    t = t.replace(".lnk", " shortcut")
    t = t.replace(".msi", " installer")

    # Remove long Windows paths (too noisy)
    t = re.sub(r"[A-Za-z]:\\[^\s]+", "file path", t)

    # Collapse extra spaces
    t = re.sub(r"\s+", " ", t).strip()

    return t


def _friendly_location(p: Path) -> str:
    s = str(p).lower()
    if "\\desktop\\" in s:
        return "Desktop"
    if "\\downloads\\" in s:
        return "Downloads"
    if "\\documents\\" in s:
        return "Documents"
    if "\\start menu\\" in s:
        return "Start Menu"
    return "Other"


def _friendly_type(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".lnk":
        return "Shortcut"
    if ext in {".exe", ".msi"}:
        return "Application"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return "Image"
    if ext == ".pdf":
        return "PDF"
    return ext[1:].upper() if ext else "File"


def aida_say_text(text: str, config: AidaConfig) -> None:
    msg = (text or "").strip()
    if not msg:
        return
    print(f"[AIDA] {msg}")
    play_start_tone(config, blocking=True)
    tts_msg = clean_for_tts(msg)
    speak_text(tts_msg, config)
    play_end_tone(config, blocking=True)


@dataclass(frozen=True)
class Intent:
    name: str
    arg: str = ""


_FILE_PATTERNS = [
    re.compile(r"(?:can't find|cannot find|can not find|cant find)\s+(?P<file>.+)$", re.I),
    re.compile(r"(?:help me find|show me where|where is|where's)\s+(?P<file>.+)$", re.I),
    re.compile(r"(?:find|locate)\s+(?:the\s+)?(?:file\s+)?(?P<file>.+)$", re.I),
    re.compile(r"(?:open|launch)\s+(?:file explorer|explorer)\s+(?:and\s+)?(?:lead me to|take me to|show me)\s+(?P<file>.+)$", re.I),
    re.compile(r"(?:put)\s+(?P<file>.+?)\s+(?:in front of me)$", re.I),
]

_SETTINGS_PATTERNS = [
    re.compile(
        r"(?:show me|open|take me to|go to|navigate to)\s+"
        r"(?P<target>bluetooth|wifi|network|windows update|updates|update|apps|apps and features|display|sound|privacy)\b",
        re.I,
    ),
    re.compile(
        r"(?:can't find|cannot find|cant find)\s+"
        r"(?P<target>bluetooth|wifi|network|windows update|updates|update|apps|apps and features|display|sound|privacy)\b",
        re.I,
    ),
]


def detect_intent(user_text: str) -> Optional[Intent]:
    s = (user_text or "").strip()
    if not s:
        return None

    s_l = s.lower()

    if re.search(r"\b(quick\s*scan|quickscan|run\s+a\s+scan|scan\s+my\s+system|system\s+scan)\b", s_l):
        return Intent("run_quickscan", "")

    if re.search(r"\b(scan|check|analyze).*(files|malware|virus|threat)\b", s_l):
        return Intent("run_file_scan", "")

    if re.search(
        r"\b("
        r"scan|check|analyze|analyse|inspect|review|identify|find|look for|detect|optimize"
        r")\b.*\b("
        r"ram|memory|performance|slow|slowness|optimization|optimisation|bottleneck|resource usage"
        r")\b",
        s_l,
    ):
        return Intent("run_perf_scan", "")

    if "settings" in s_l:
        if any(
            k in s_l
            for k in [
                "bluetooth",
                "wifi",
                "wi-fi",
                "network",
                "update",
                "windows update",
                "apps",
                "display",
                "sound",
                "privacy",
            ]
        ):
            if "bluetooth" in s_l:
                return Intent("open_settings", "bluetooth")
            if "wi-fi" in s_l or "wifi" in s_l:
                return Intent("open_settings", "wifi")
            if "windows update" in s_l or "update" in s_l or "updates" in s_l:
                return Intent("open_settings", "windows_update")
            if "apps" in s_l:
                return Intent("open_settings", "apps_features")
            if "display" in s_l:
                return Intent("open_settings", "display")
            if "sound" in s_l:
                return Intent("open_settings", "sound")
            if "privacy" in s_l:
                return Intent("open_settings", "privacy")
            if "network" in s_l:
                return Intent("open_settings", "network")

    for pat in _SETTINGS_PATTERNS:
        m = pat.search(s)
        if m:
            target = (m.group("target") or "").strip().lower()
            target = target.replace(" ", "_")
            if target in {"updates", "update"}:
                target = "windows_update"
            if target in {"apps", "apps_and_features"}:
                target = "apps_features"
            return Intent("open_settings", target)

    for pat in _FILE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue

        raw = (m.group("file") or "").strip()
        raw = re.sub(r"^(the\s+file|file)\s+", "", raw, flags=re.I).strip()

        raw = re.split(
            r"\b(can you|could you|please|for me|put it|show me|open it|lead me|take me|in front of me)\b",
            raw,
            maxsplit=1,
            flags=re.I,
        )[0].strip()

        raw = re.sub(
            r"\b(in my files|on my desktop|in my desktop files|in my folders|on my computer)\b",
            "",
            raw,
            flags=re.I,
        ).strip()

        raw = raw.strip(" .!?\"'").rstrip(",").strip()

        if raw:
            return Intent("find_file", raw)

    return None


def _summarize_findings(findings: List[Finding]) -> List[str]:
    lines: List[str] = []

    for f in findings[:5]:
        title = (f.title or "Unnamed finding").strip()
        detail = (f.detail or "").strip()

        if detail:
            lines.append(f"{title}: {detail}")
        else:
            lines.append(title)

    return lines

def extract_memory_percent(findings: List[Finding]) -> Optional[float]:
    for f in findings:
        text = f"{f.title} {f.detail}".lower()
        match = re.search(r"memory usage:\s*(\d+\.?\d*)%", text)
        if match:
            return float(match.group(1))
    return None

def extract_cpu_percent(findings: List[Finding]) -> Optional[float]:
    for f in findings:
        text = f"{f.title} {f.detail}".lower()

        # common patterns
        match = re.search(r"cpu usage:\s*(\d+\.?\d*)%", text)
        if match:
            return float(match.group(1))

        # fallback pattern (in case format changes)
        match = re.search(r"(\d+\.?\d*)%\s*cpu", text)
        if match:
            return float(match.group(1))

    return None

def interpret_memory(text: str) -> Optional[str]:
    match = re.search(r"memory usage:\s*(\d+\.?\d*)%", text.lower())
    if not match:
        return None

    percent = float(match.group(1))

    if percent < 60:
        return "Memory usage is within normal operating range."
    elif percent < 75:
        return "System is under moderate memory load."
    else:
        return "High memory pressure detected. Optimization recommended."


def interpret_cpu(percent: float) -> str:
    if percent < 40:
        return "CPU usage is within normal operating range."
    elif percent < 75:
        return "CPU is under moderate load."
    else:
        return "High CPU utilization detected. Performance may be impacted."
    
def classify_memory(percent: float) -> str:
    if percent < 50:
        return "INFO"
    elif percent < 70:
        return "WARNING"
    else:
        return "CRITICAL"
    
def generate_system_verdict(
    memory_percent: Optional[float],
    cpu_percent: Optional[float],
    memory_delta: Optional[float],
    cpu_delta: Optional[float],
) -> Optional[str]:

    if memory_percent is None and cpu_percent is None:
        return None

    issues = []

    # --- CURRENT STATE ---
    if memory_percent is not None:
        if memory_percent >= 85:
            issues.append("high memory usage")
        elif memory_percent >= 60:
            issues.append("moderate memory load")

    if cpu_percent is not None:
        if cpu_percent >= 75:
            issues.append("high CPU usage")
        elif cpu_percent >= 40:
            issues.append("moderate CPU load")

    # --- TREND ---
    trend = None
    if memory_delta is not None or cpu_delta is not None:
        increases = []
        decreases = []

        if memory_delta is not None:
            if memory_delta > 1:
                increases.append("memory")
            elif memory_delta < -1:
                decreases.append("memory")

        if cpu_delta is not None:
            if cpu_delta > 2:
                increases.append("CPU")
            elif cpu_delta < -2:
                decreases.append("CPU")

        if increases and not decreases:
            trend = "increasing"
        elif decreases and not increases:
            trend = "decreasing"

    # --- FINAL VERDICT ---
    if issues:
        if trend == "increasing":
            return f"System performance has degraded due to {' and '.join(issues)}."
        elif trend == "decreasing":
            return f"System performance is improving as {' and '.join(issues)} stabilize."
        else:
            return f"System is experiencing {' and '.join(issues)}."

    return None

def recommend_repair(
    memory_percent: Optional[float],
    cpu_percent: Optional[float],
    memory_delta: Optional[float],
    cpu_delta: Optional[float],
) -> Optional[str]:

    if memory_percent is not None and memory_percent >= 90:
        return "Severe memory pressure detected. Recommend system file integrity scan."

    if cpu_percent is not None and cpu_percent >= 90:
        return "Sustained high CPU usage detected. Recommend system file integrity scan."

    if memory_delta is not None and memory_delta > 15:
        return "Rapid memory usage increase detected. Recommend system file integrity scan."

    if cpu_delta is not None and cpu_delta > 20:
        return "Rapid CPU usage increase detected. Recommend system file integrity scan."

    return None

def _ask_yes_no(prompt: str, config: AidaConfig) -> bool:
    aida_say_text(prompt + " Reply: yes or no.", config)
    while True:
        try:
            ans = input("User> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if ans in {"yes", "y"}:
            return True
        if ans in {"no", "n"}:
            return False
        aida_say_text("Response unclear. Reply: yes or no.", config)


def start_cli_loop(config: AidaConfig, initial_findings: List[Finding], brain: AIDABrain) -> None:
    aida_say_text(
        "Analytical Intelligent Diagnostic Agent is activated. Awaiting directive.",
        config,
    )

    context_state = {
        "last_scan_type": None,
        "last_scan_time": None,
        "last_focus": None,   # NEW (this is key)
        "last_findings": [],
        "previous_findings": [],  # (store findings from previous scans for comparison)
        "last_alert_time": None,  # NEW (track when we last alerted about critical memory)
    }

    while True:
        memory_percent = None
        cpu_percent = None
        # --- passive monitoring ---
        current_time = time.time()

        if context_state["last_scan_time"] is None:
            context_state["last_scan_time"] = current_time

        elif current_time - context_state["last_scan_time"] > 30:
            findings = run_quickscan(config)
            context_state["last_findings"] = findings

            memory_percent = extract_memory_percent(findings)
            cpu_percent = extract_cpu_percent(findings)

            if memory_percent is not None:
                level = classify_memory(memory_percent)

                if level == "CRITICAL":
                    if (
                        context_state["last_alert_time"] is None
                        or current_time - context_state["last_alert_time"] > 60
                    ):
                        aida_say_text("Critical memory pressure detected.", config)
                        context_state["last_alert_time"] = current_time

            context_state["last_scan_time"] = current_time
        try:
            user_input = input("User> ").strip()
        except (EOFError, KeyboardInterrupt):
            aida_say_text("Shutdown acknowledged. Session terminated.", config)
            break

        if not user_input:
            continue

        lower = user_input.lower()
        if lower in {"exit", "quit"}:
            aida_say_text("Shutdown acknowledged. Session terminated.", config)
            break

        intent = detect_intent(user_input)
        print(f"[DEBUG] intent={intent}")

        # Predictive context handling
        if not intent and context_state["last_focus"]:
            user_l = user_input.lower()

            if "optimize" in user_l or "fix" in user_l:
                if context_state["last_focus"] == "memory":
                    intent = Intent("run_perf_scan", "")
                elif context_state["last_focus"] == "security":
                    intent = Intent("run_file_scan", "")

            if "scan again" in user_l or "run it again" in user_l:
                intent = Intent(context_state["last_scan_type"], "")

        if intent and intent.name in {"run_quickscan", "run_perf_scan", "run_file_scan"}:
            try:
                if intent.name == "run_file_scan":
                    aida_say_text(
                        "File scan initiated. Security analysis in progress.",
                        config,
                    )
                    findings = run_file_scan(config)
                elif intent.name == "run_perf_scan":
                    aida_say_text(
                        "Performance scan initiated. Preliminary system assessment in progress.",
                        config,
                    )

                    findings = run_full_diagnostics(config)
                else:
                    aida_say_text(
                        "Quickscan initiated. Preliminary system assessment in progress.",
                        config,
                    )
                    findings = run_quickscan(config)

            except Exception as exc:
                log.exception("Scan failed: %s", exc)
                aida_say_text(
                    "Scan failed. Manual diagnostic intake required.",
                    config,
                )
                continue

            context_state["last_scan_type"] = intent.name
            context_state["last_scan_time"] = time.time()
            context_state["previous_findings"] = context_state["last_findings"]
            context_state["last_findings"] = findings

            # infer focus
            if intent.name == "run_perf_scan":
                context_state["last_focus"] = "memory"
            elif intent.name == "run_file_scan":
                context_state["last_focus"] = "security"
            else:
                context_state["last_focus"] = "system"

            if not findings:
                if intent.name == "run_file_scan":
                    aida_say_text(
                        "No active threats detected in Defender quick scan scope.",
                        config,
                    )
                    aida_say_text("Security scan complete. Standing by.", config)
                else:
                    aida_say_text(
                        "Scan complete. No surface-level anomalies detected.",
                        config,
                    )
                    aida_say_text("Diagnostic Prototype on standby.", config)
                continue

            if intent.name == "run_perf_scan":
                filtered = [
                    line for line in _summarize_findings(findings)
                    if any(
                        k in line.lower()
                        for k in ["memory", "ram", "process", "cpu", "usage", "performance", "optimize", "bottleneck"]
                    )
                ]
                summary_lines = filtered if filtered else _summarize_findings(findings)
            else:
                summary_lines = _summarize_findings(findings)

            summary_text = "\n".join(summary_lines)

            memory_percent = None
            cpu_percent = None
            previous_memory_percent = None
            previous_cpu_percent = None

            memory_delta = None
            cpu_delta = None

            memory_delta_text = None
            cpu_delta_text = None

            memory_interpretation = None
            cpu_interpretation = None

            if intent.name == "run_perf_scan":
                # Extract current and previous metrics once.
                memory_percent = extract_memory_percent(context_state["last_findings"])
                cpu_percent = extract_cpu_percent(context_state["last_findings"])

                previous_memory_percent = extract_memory_percent(context_state["previous_findings"])
                previous_cpu_percent = extract_cpu_percent(context_state["previous_findings"])

                # Interpret current memory state.
                for line in summary_lines:
                    memory_interpretation = interpret_memory(line)
                    if memory_interpretation:
                        break

                # Interpret current CPU state.
                if cpu_percent is not None:
                    cpu_interpretation = interpret_cpu(cpu_percent)

                # Compare memory against previous scan.
                if memory_percent is not None and previous_memory_percent is not None:
                    memory_delta = round(memory_percent - previous_memory_percent, 1)

                    if abs(memory_delta) >= 1:
                        if memory_delta > 0:
                            memory_delta_text = f"Memory usage increased by {memory_delta}% since last scan."
                        else:
                            memory_delta_text = f"Memory usage decreased by {abs(memory_delta)}% since last scan."

                # Compare CPU against previous scan.
                if cpu_percent is not None and previous_cpu_percent is not None:
                    cpu_delta = round(cpu_percent - previous_cpu_percent, 1)

                    if abs(cpu_delta) >= 2:
                        if cpu_delta > 0:
                            cpu_delta_text = f"CPU usage increased by {cpu_delta}% since last scan."
                        else:
                            cpu_delta_text = f"CPU usage decreased by {abs(cpu_delta)}% since last scan."

            if intent.name == "run_file_scan":
                aida_say_text(summary_text, config)
                aida_say_text("Security scan complete. Standing by.", config)

            elif intent.name == "run_perf_scan":
                aida_say_text(
                    f"Performance scan complete. Findings detected: {len(findings)}.",
                    config,
                )

                if memory_interpretation:
                    aida_say_text(memory_interpretation, config)

                if cpu_interpretation:
                    aida_say_text(cpu_interpretation, config)

                if memory_delta_text:
                    aida_say_text(memory_delta_text, config)

                if cpu_delta_text:
                    aida_say_text(cpu_delta_text, config)

                # 🔥 SYSTEM VERDICT
                system_verdict = generate_system_verdict(
                    memory_percent,
                    cpu_percent,
                    memory_delta,
                    cpu_delta,
                )

                if system_verdict:
                    aida_say_text(system_verdict, config)

                # 🔥 REPAIR RECOMMENDATION
                repair_recommendation = recommend_repair(
                    memory_percent,
                    cpu_percent,
                    memory_delta,
                    cpu_delta,
                )

                if repair_recommendation:
                    if _ask_yes_no(repair_recommendation + " Proceed?", config):
                        aida_say_text(
                            "To execute system file check, run SFC /scannow in an elevated command prompt.",
                            config,
                        )

# Speak summarized findings (limited to avoid overload)
                if summary_lines:
                    aida_say_text("Top findings:", config)

                seen = set()

                aida_say_text(f"Top findings out of {len(findings)} detected:", config)

                for line in summary_lines:
                    if line not in seen:
                        aida_say_text(line, config)
                        seen.add(line)
                    if len(seen) >= 3:
                        break

                print(summary_text)
                aida_say_text("Diagnostic Prototype on standby.", config)

            else:
                aida_say_text(
                    f"Quickscan complete. Findings detected: {len(findings)}. {summary_text}",
                    config,
                )
                aida_say_text("Diagnostic Prototype on standby.", config)

            continue

        if intent and intent.name == "open_settings":
            target = intent.arg
            uri = SETTINGS_URIS.get(target)

            if not uri:
                opts = ", ".join(sorted(SETTINGS_URIS.keys()))
                aida_say_text(
                    f"Settings target not recognized. Available targets: {opts}.",
                    config,
                )
                continue

            aida_say_text("Navigating. Opening Settings page.", config)
            open_settings(uri)
            continue

        if intent and intent.name == "find_file":
            name = intent.arg
            aida_say_text("Navigating. Searching common folders.", config)

            text_l = user_input.lower()
            desktop_hint = "desktop" in text_l

            if desktop_hint:
                desktop_roots = [p for p in default_search_roots() if p.name.lower() == "desktop"]
                matches, scanned = find_file_by_name(
                    name,
                    roots=desktop_roots,
                    max_dirs_scanned=2000,
                )
            else:
                matches, scanned = find_file_by_name(name)

            if not matches:
                expanded_roots: List[Path] = []

                appdata = os.environ.get("APPDATA")
                programdata = os.environ.get("ProgramData")

                if appdata:
                    p = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                    if p.exists():
                        expanded_roots.append(p)

                if programdata:
                    p = Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                    if p.exists():
                        expanded_roots.append(p)

                expanded_roots.append(Path.home())

                aida_say_text("Expanding search scope. Name-only scan in progress.", config)
                matches, scanned = find_file_by_name(
                    name,
                    roots=expanded_roots,
                    max_dirs_scanned=15000,
                )

            if not matches:
                aida_say_text(
                    f"No matches located. Directories scanned: {scanned}. "
                    "If the file is on Desktop, Downloads, or Documents, reply with one of those words. "
                    "If you know the full file name, include the ending like .jpg or .lnk.",
                    config,
                )
                continue

            if len(matches) == 1:
                aida_say_text("File located. Opening File Explorer.", config)
                open_explorer_select(matches[0])
                continue

            lines = ["Multiple matches detected:"]
            for i, p in enumerate(matches, start=1):
                loc = _friendly_location(p)
                typ = _friendly_type(p)
                lines.append(f"{i}. {p.name} ({typ} • {loc})")
            lines.append("Reply with the number to open the correct one.")
            aida_say_text("\n".join(lines), config)

            choice = input("User> ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(matches):
                    aida_say_text("Opening File Explorer at selected match.", config)
                    open_explorer_select(matches[idx - 1])
            continue

        if any(word in user_input.lower() for word in ["earlier", "last scan", "previous scan"]) and context_state["last_findings"]:
            if context_state["last_scan_time"]:
                seconds_ago = int(time.time() - context_state["last_scan_time"])
                time_text = f"{seconds_ago} seconds ago"
            else:
                time_text = "recently"

            if context_state["last_scan_type"] == "run_perf_scan":
                aida_say_text(
                    f"Last performance scan ran {time_text} and detected moderate system load.",
                    config,
                )
            elif context_state["last_scan_type"] == "run_quickscan":
                aida_say_text(
                    f"Last quickscan ran {time_text} and reported general system status.",
                    config,
                )
            elif context_state["last_scan_type"] == "run_file_scan":
                aida_say_text(
                    f"Last security scan ran {time_text} and reported no active threats.",
                    config,
                )
            continue

        context: List[str] = []

        if context_state["last_findings"]:
            context.append("Recent quickscan findings:")
            for line in _summarize_findings(context_state["last_findings"]):
                context.append(f"- {line}")

        try:
            response = brain.think(user_input, context=context)
        except Exception as exc:
            log.exception("Brain failure: %s", exc)
            response = "Processing failure. Provide additional detail. Further analysis required."

        aida_say_text(response, config)