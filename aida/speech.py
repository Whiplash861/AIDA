from __future__ import annotations
from enum import Enum, auto


class SpeechIntent(Enum):
    STATUS = auto()
    ALERT = auto()
    QUERY_ACK = auto()
    CLARIFICATION = auto()
    SOLUTION_STEP = auto()
    SHUTDOWN = auto()
    SYSTEM = auto()


def format_aida_line(intent: SpeechIntent, core_message: str) -> str:
    core = core_message.strip().rstrip(".")

    if intent is SpeechIntent.ALERT:
        return f"Alert. {core}."
    if intent is SpeechIntent.STATUS:
        return f"Status: {core}."
    if intent is SpeechIntent.QUERY_ACK:
        return f"Input received. {core}."
    if intent is SpeechIntent.CLARIFICATION:
        return f"Analysis incomplete. {core}."
    if intent is SpeechIntent.SOLUTION_STEP:
        return f"Directive: {core}."
    if intent is SpeechIntent.SHUTDOWN:
        return f"Session terminated. {core}."
    if intent is SpeechIntent.SYSTEM:
        return core + "."

    return core + "."
