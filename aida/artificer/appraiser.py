from __future__ import annotations

import uuid
from collections import Counter, defaultdict

from aida.artificer.ledger import ArtificerLedger
from aida.artificer.models import ArtificerFinding, AuthorityLevel, utc_now


class Appraiser:
    """Correlates repeated operational events into evidence-based findings."""

    def __init__(self, ledger: ArtificerLedger) -> None:
        self.ledger = ledger

    def review(self) -> list[ArtificerFinding]:
        events = self.ledger.recent_events(limit=1000)
        findings: list[ArtificerFinding] = []
        failures = [event for event in events if event["status"].lower() in {"failed", "error"}]
        by_source: Counter[str] = Counter(event["source"] for event in failures)

        for source, count in by_source.items():
            if count < 3:
                continue
            findings.append(
                self._finding(
                    category="reliability",
                    title="Repeated subsystem failures",
                    severity="high" if count >= 10 else "moderate",
                    affected=(source,),
                    finding=f"{source} produced {count} recent failure events.",
                    evidence=f"{count} failed or error events exist in the latest 1,000 operational events.",
                    reasoning="Repeated failures indicate a persistent problem rather than an isolated transient event.",
                    recommendation="Inspect the failing operation paths, provider availability, and retry behavior.",
                    fingerprint=f"failures:{source}",
                    count=count,
                    risk=0.35,
                )
            )

        durations: dict[str, list[float]] = defaultdict(list)
        for event in events:
            if event.get("duration_ms") is not None:
                durations[event["source"]].append(float(event["duration_ms"]))
        for source, samples in durations.items():
            if len(samples) < 5:
                continue
            average = sum(samples) / len(samples)
            maximum = max(samples)
            if average < 5000 and maximum < 15000:
                continue
            findings.append(
                self._finding(
                    category="performance",
                    title="Sustained operation latency",
                    severity="moderate",
                    affected=(source,),
                    finding=f"{source} operations are completing slowly.",
                    evidence=f"Average {average:.0f} ms across {len(samples)} samples; maximum {maximum:.0f} ms.",
                    reasoning="Repeated latency increases user wait time and may indicate provider, locking, or workload inefficiency.",
                    recommendation="Profile the operation and separate provider wait time from local processing.",
                    fingerprint=f"latency:{source}",
                    count=len(samples),
                    risk=0.30,
                )
            )

        fallback_count = sum(
            1 for event in events if event["event_type"] == "command_fallback"
        )
        command_count = sum(
            1
            for event in events
            if event["event_type"] in {"command_routed", "command_fallback"}
        )
        if command_count >= 10 and fallback_count / command_count >= 0.35:
            findings.append(
                self._finding(
                    category="routing",
                    title="High language-model fallback rate",
                    severity="moderate",
                    affected=("command_router", "brain"),
                    finding="A large share of recent commands bypassed deterministic routing.",
                    evidence=f"{fallback_count} of {command_count} commands used the fallback path.",
                    reasoning="Frequent fallback increases latency, cost, and nondeterminism for requests AIDA may be able to handle locally.",
                    recommendation="Review fallback phrases and add validated command intents or local classifiers.",
                    fingerprint="routing:fallback-rate",
                    count=fallback_count,
                    risk=0.25,
                )
            )
        return findings

    @staticmethod
    def _finding(
        *,
        category: str,
        title: str,
        severity: str,
        affected: tuple[str, ...],
        finding: str,
        evidence: str,
        reasoning: str,
        recommendation: str,
        fingerprint: str,
        count: int,
        risk: float,
    ) -> ArtificerFinding:
        now = utc_now()
        return ArtificerFinding(
            finding_id=f"AE-OPS-{uuid.uuid4().hex[:10].upper()}",
            category=category,
            title=title,
            severity=severity,
            confidence=0.94,
            evidence_quality=0.92,
            affected_components=affected,
            first_seen_utc=now,
            last_seen_utc=now,
            observation_count=count,
            finding=finding,
            evidence_summary=evidence,
            reasoning_summary=reasoning,
            recommended_change=recommendation,
            expected_outcomes=("Higher operational reliability", "Lower user-visible failure rate"),
            implementation_risk=risk,
            regression_risk=min(0.75, risk + 0.15),
            authority_required=AuthorityLevel.RECOMMEND.value,
            fingerprint=fingerprint,
        )
