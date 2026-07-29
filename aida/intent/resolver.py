from __future__ import annotations

from dataclasses import dataclass

from aida.intent.models import (
    IntentCandidate,
    IntentContext,
    IntentDefinition,
    IntentResolution,
    IntentRisk,
    ResolvedIntent,
)
from aida.intent.normalizer import contains_phrase, normalize_input
from aida.intent.registry import IntentRegistry
from aida.intent.slots import extract_slots


@dataclass(frozen=True, slots=True)
class _ScoreParts:
    score: float
    reasons: tuple[str, ...]


class IntentResolver:
    """Deterministic, explainable natural-language intent resolver."""

    def __init__(
        self,
        registry: IntentRegistry,
        *,
        ambiguity_margin: float = 0.12,
    ) -> None:
        self.registry = registry
        self.ambiguity_margin = ambiguity_margin

    def resolve(
        self,
        text: str,
        context: IntentContext | None = None,
    ) -> IntentResolution:
        source_text = text.strip()
        normalized = normalize_input(source_text)
        if not normalized:
            return IntentResolution(resolved=None)

        active_context = context or IntentContext()
        candidates = [
            self._candidate(definition, source_text, normalized, active_context)
            for definition in self.registry.definitions()
        ]
        candidates = [candidate for candidate in candidates if candidate.score > 0.0]
        candidates.sort(
            key=lambda item: (
                item.score,
                item.definition.priority,
                -len(item.missing_slots),
            ),
            reverse=True,
        )
        if not candidates:
            return IntentResolution(resolved=None)

        best = candidates[0]
        if (
            best.score < 0.90
            and _needs_scan_type_clarification(normalized)
        ):
            return IntentResolution(
                resolved=None,
                candidates=tuple(candidates[:4]),
                clarification=(
                    "What type of scan should AIDA run: diagnostic Quickscan, "
                    "Surface Security Scan, targeted Deep Scan, or Full-System Sweep?"
                ),
            )

        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        margin = best.score - runner_up

        if best.score < best.definition.clarification_threshold:
            return IntentResolution(
                resolved=None,
                candidates=tuple(candidates[:3]),
                clarification=self._clarification(candidates[:3]),
            )

        if (
            margin < self.ambiguity_margin
            and runner_up >= best.definition.clarification_threshold
        ):
            return IntentResolution(
                resolved=None,
                candidates=tuple(candidates[:3]),
                clarification=self._clarification(candidates[:3]),
            )

        requires_confirmation = (
            best.score < best.definition.execution_threshold
            or bool(best.missing_slots)
            or best.definition.risk >= IntentRisk.HIGH_IMPACT
        )
        resolved = ResolvedIntent(
            intent_id=best.definition.intent_id,
            command_type=best.definition.command_type,
            confidence=best.score,
            runner_up_confidence=runner_up,
            source_text=source_text,
            normalized_text=normalized,
            slots=best.slots,
            missing_slots=best.missing_slots,
            risk=best.definition.risk,
            requires_confirmation=requires_confirmation,
            local_only=best.definition.local_only,
            reasons=best.reasons,
        )
        return IntentResolution(
            resolved=resolved,
            candidates=tuple(candidates[:5]),
        )

    def _candidate(
        self,
        definition: IntentDefinition,
        source_text: str,
        normalized: str,
        context: IntentContext,
    ) -> IntentCandidate:
        parts = self._score(definition, normalized, context)
        slots = extract_slots(
            definition.intent_id,
            source_text,
            normalized,
            context,
        )
        missing = tuple(
            slot for slot in definition.required_slots if not slots.get(slot)
        )
        score = parts.score
        reasons = list(parts.reasons)
        if missing:
            score -= min(0.20, 0.10 * len(missing))
            reasons.append("required information is missing")
        score = max(0.0, min(1.0, score))
        return IntentCandidate(
            definition=definition,
            score=round(score, 4),
            slots=slots,
            missing_slots=missing,
            reasons=tuple(reasons),
        )

    def _score(
        self,
        definition: IntentDefinition,
        normalized: str,
        context: IntentContext,
    ) -> _ScoreParts:
        reasons: list[str] = []
        alias_matches = [
            alias for alias in definition.aliases if contains_phrase(normalized, alias)
        ]
        if alias_matches:
            score = 0.93 + min(0.05, 0.01 * (len(alias_matches) - 1))
            reasons.append(f"direct phrase match: {alias_matches[0]}")
        else:
            actions = [
                term for term in definition.actions if contains_phrase(normalized, term)
            ]
            objects = [
                term for term in definition.objects if contains_phrase(normalized, term)
            ]
            modifiers = [
                term for term in definition.modifiers if contains_phrase(normalized, term)
            ]
            score = 0.0
            if actions:
                score += 0.20
                reasons.append(f"action concept: {actions[0]}")
            if objects:
                score += 0.30
                reasons.append(f"object concept: {objects[0]}")
            if modifiers:
                score += 0.42
                reasons.append(f"modifier concept: {modifiers[0]}")
            if not definition.modifiers and actions and objects:
                score += 0.24
            if definition.modifiers and objects and not modifiers:
                score -= 0.10

        if (
            definition.intent_id == "security.scan.surface"
            and _is_unqualified_security_scan(normalized)
        ):
            score = max(score, 0.92)
            reasons.append(
                "explicit malware, antivirus, or security scan defaults "
                "to Surface Security Scan"
            )

        negatives = [
            term
            for term in definition.negative_terms
            if contains_phrase(normalized, term)
        ]
        if negatives:
            score -= min(0.55, 0.22 * len(negatives))
            reasons.append(f"conflicting concept: {negatives[0]}")

        domain = definition.intent_id.split(".", 1)[0]
        if context.current_domain == domain:
            score += 0.04
            reasons.append("matches current conversation domain")
        if context.last_intent_id == definition.intent_id:
            score += 0.03
            reasons.append("matches the previous resolved intent")
        if (
            context.pending_confirmation_action
            and definition.intent_id == context.pending_confirmation_action
        ):
            score += 0.08
            reasons.append("matches the pending confirmation")

        return _ScoreParts(
            score=max(0.0, min(1.0, score)),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _clarification(candidates: list[IntentCandidate]) -> str:
        labels = [
            candidate.definition.description or candidate.definition.intent_id
            for candidate in candidates[:2]
        ]
        if len(labels) == 1:
            return f"Did you mean {labels[0]}?"
        return f"Did you mean {labels[0]} or {labels[1]}?"


def _is_unqualified_security_scan(normalized: str) -> bool:
    security_phrases = (
        "malware scan",
        "antivirus scan",
        "anti virus scan",
        "security scan",
        "defender scan",
    )
    if not any(
        contains_phrase(normalized, phrase)
        for phrase in security_phrases
    ):
        return False

    explicit_non_surface_modes = (
        "deep",
        "deeply",
        "targeted",
        "specific file",
        "specific folder",
        "specific path",
        "full",
        "full system",
        "comprehensive",
        "complete system",
        "entire computer",
        "whole machine",
        "all drives",
    )
    return not any(
        contains_phrase(normalized, term)
        for term in explicit_non_surface_modes
    )


def _needs_scan_type_clarification(normalized: str) -> bool:
    if "scan" not in normalized and "sweep" not in normalized:
        return False
    explicit = (
        "quick scan",
        "quickscan",
        "performance",
        "system health",
        "diagnostic",
        "surface",
        "low level",
        "light security",
        "basic malware",
        "quick malware",
        "quick security",
        "deep",
        "deeply",
        "targeted",
        "full",
        "comprehensive",
        "complete system",
        "entire computer",
        "whole machine",
        "all drives",
        "cancel",
        "stop",
        "terminate",
    )
    return not any(contains_phrase(normalized, term) for term in explicit)
