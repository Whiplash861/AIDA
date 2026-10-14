"""Plain-language views of Artificer's recorded reviews and proposals."""
from __future__ import annotations

from aida.reporting import render_report


def render_overview(snapshot) -> str:
    reviewed = bool(snapshot.last_review_utc)
    found = [
        f"Artificer has {len(snapshot.open_findings)} open finding(s), {len(snapshot.pending_proposals)} proposal(s) awaiting review, and {len(snapshot.source_reviews)} captured code review(s).",
        f"Last completed review: {snapshot.last_review_utc}." if reviewed else "No completed review is recorded for this session.",
        "Automatic maintenance is disabled; reviewing this report does not change AIDA's code.",
    ]
    if snapshot.status == "disabled":
        found.append("Artificer is turned off. Any saved findings below are historical records.")
    return render_report("Artificer — AIDA's own code and operation", found=found,
        unknown=("The recorded checks do not cover every possible software problem or establish that a proposed change will help.",),
        next_steps=("Run Review to inspect the available code and recorded operational events, then open a finding to review its evidence and proposed change.",
                    "Use Source Reviews to inspect the exact code. A candidate export still needs testing and the required approval before any live change."),
        details=(f"Engine state: {snapshot.status}", f"Platform: {snapshot.platform_summary}",
                 f"Telemetry policy: {snapshot.telemetry_level}", f"Reports waiting for dispatch: {snapshot.dispatch_queue_depth}",
                 "Automatic maintenance: DISABLED"))


def render_findings(findings) -> str:
    if not findings:
        return render_report("Artificer findings", found=("No open findings are currently recorded.",),
            unknown=("An empty list does not show that every source file or runtime behavior was checked.",),
            next_steps=("Run Review and check the review date and compatibility results before drawing a conclusion.",))
    reports = []
    for item in findings:
        reports.append(render_report(item.title,
            found=(item.finding, "Recorded evidence: " + item.evidence_summary,
                   f"Recorded {item.observation_count} time(s); affected: {', '.join(item.affected_components) or 'not identified'}.",),
            interpretation=item.reasoning_summary,
            unknown=("The proposed change has not been shown here to fix the issue or avoid other problems.",
                     "Expected results, still to be verified: " + ("; ".join(item.expected_outcomes) or "No expected result was recorded.")),
            next_steps=("Proposed change: " + item.recommended_change,
                        "Inspect the linked source review where available, then review testing, rollback and approval requirements before making a change."),
            details=(f"Finding ID: {item.finding_id}", f"Category: {item.category}; severity: {item.severity}; status: {item.status}",
                     f"Recorded support score: {item.confidence:.2f}; evidence quality: {item.evidence_quality:.2f}. These scores are not proof of a diagnosis.",
                     f"Implementation risk: {item.implementation_risk:.2f}; regression risk: {item.regression_risk:.2f}",
                     f"Required authority: {item.authority_required}", f"Last observed: {item.last_seen_utc.isoformat()}")))
    return "\n\n---\n\n".join(reports)


def render_compatibility(snapshot) -> str:
    labels = {"security.provider": "Security provider"}
    meanings = {"compatible": "reported available in the captured profile",
                "native": "has an operating-system integration; execution still needs verification",
                "unverified": "has not been verified on this machine",
                "unavailable": "was unavailable when checked", "unsupported": "is not supported here",
                "degraded": "has limited or incomplete support", "permission_required": "needs permission before it can be checked or used"}
    found = [f"Captured platform: {snapshot.platform_summary}."]
    found.extend(f"{labels.get(name, name.replace('.', ' ').replace('_', ' '))}: {meanings.get(status, 'reported ' + status.replace('_', ' '))}."
                 for name, status in sorted(snapshot.compatibility_summary.items()))
    if not snapshot.compatibility_summary:
        found.append("No capability check results are available.")
    return render_report("What this installation can currently support", found=found,
        unknown=("A captured capability result does not prove that a particular scan, repair, or other operation will succeed.",),
        next_steps=("Run Review to refresh the profile. For an unavailable feature, review that feature's own status and permission requirements before using it.",),
        details=tuple(f"{name}: {status}" for name, status in sorted(snapshot.compatibility_summary.items())))


def render_proposals(proposals) -> str:
    if not proposals:
        return render_report("Artificer proposals", found=("No proposals are currently waiting for review.",),
            unknown=("This does not establish that no improvements are possible; a proposal needs supporting findings.",),
            next_steps=("Review an open finding and its source evidence before creating a proposal.",))
    return "\n\n---\n\n".join(render_report(item.title,
        found=(f"A proposal is recorded for {item.affected_subsystem}. Its status is {item.status.replace('_', ' ')}.",
               "Reason for the proposal: " + item.rationale),
        interpretation="Expected results, not yet verified: " + ("; ".join(item.expected_outcomes) or "No expected result was recorded."),
        unknown=("A proposal records an intended change; it does not show that the change has been applied or tested successfully.",),
        next_steps=("Required tests: " + ("; ".join(item.required_tests) or "No tests specified; define them before proceeding."),
                    "Success will be judged by: " + ("; ".join(item.success_metrics) or "No success measures specified; agree on these before proceeding."),
                    "Review the rollback plan and obtain the required approval before implementation."),
        details=(f"Proposal ID: {item.proposal_id}",
                 "Source reviews: " + (", ".join(item.source_review_ids) or "No source anchor; operational proposal"),
                 f"Version: {item.current_version} -> {item.proposed_version}", f"Required authority: {item.authority_required}",
                 f"Implementation risk: {item.implementation_risk:.2f}; regression risk: {item.regression_risk:.2f}",
                 "Compatibility requirements: " + ("; ".join(item.compatibility_requirements) or "Not recorded"),
                 "Alternatives considered: " + ("; ".join(item.alternatives_considered) or "Not recorded"),
                 "Rollback: " + item.rollback_procedure)) for item in proposals)


def render_governance(snapshot) -> str:
    return render_report("Artificer permissions and privacy",
        found=("Automatic maintenance is disabled.",
               "A finding, proposal, or language-model response does not authorize a change.",
               "Image contents, personal image paths, recordings and transcript text are excluded from Artificer telemetry.",
               f"Configured telemetry policy: {snapshot.telemetry_level.replace('_', ' ')}."),
        unknown=("This snapshot does not establish that a remote recipient is configured or that a particular report is approved to send.",),
        next_steps=("Review the exact proposal, required tests and rollback plan before approving a modification.",
                    "Review consent and recipient settings before sharing a diagnostic report."),
        details=("Automatic maintenance: DISABLED", "Remote dispatch: DISABLED unless explicitly configured",
                 "Governance, consent, recipient, sanitizer and Ledger code remains protected.",
                 "Every permitted modification requires validation and rollback; major upgrades and security-policy changes require owner approval.",
                 "Autonomy remains governed by its existing control subsystem."))


def render_staged_candidate(manifest) -> str:
    check_result = {"static_checks_passed": "Static checks passed.",
                    "static_checks_failed": "Static checks did not pass; the export is not a validated change."}.get(
                        manifest.get("status"), "Static check results are unavailable.")
    return render_report("Artificer candidate export",
        found=("A candidate was staged as a local export. AIDA's live source was not changed.",
               check_result),
        unknown=("Behavioral tests have not established whether the candidate works or improves the issue.",),
        next_steps=("Review the proposed code and validation results, fix any failed checks, and run the required behavioral tests in isolation before seeking approval to apply it.",),
        details=(f"Stage status: {manifest.get('status', 'unavailable')}", f"Export manifest: {manifest['manifest_path']}"))
