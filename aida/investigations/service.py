from __future__ import annotations

import hashlib
import json
import platform
import re
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import InvestigationCase, ResponseStep, ResponseWorkflow, SecurityAlert, TimelineEntry, utc_now
from .store import InvestigationStore, encode


_ALERT_CLASSES = {"support_session_anomalous", "unauthorized_suspected", "likely_intrusion", "confirmed_intrusion", "degraded"}
_PHASES = {"collecting", "review_required", "paused", "failed", "completed"}
_OUTCOMES = {"succeeded", "failed", "partial", "interrupted", "cancelled", "observed"}


class InvestigationService:
    """Persistent evidence and review workflow, with no system-action executor.

    Plans contain review requirements, never executable authority. Provider
    actions retain their own identity checks and fresh confirmation boundaries.
    """

    def __init__(self, store: InvestigationStore, *, instance_id: str = "local", platform_name: str | None = None):
        self.store = store
        self.instance_id = instance_id
        self.platform = platform_name or platform.system()
        self._listeners = set()
        self._listener_lock = threading.RLock()

    def subscribe(self, callback) -> None:
        """Callbacks receive a persisted alert; callers must marshal UI threads."""
        with self._listener_lock:
            self._listeners.add(callback)

    def unsubscribe(self, callback) -> None:
        with self._listener_lock:
            self._listeners.discard(callback)

    def _notify(self, alert: SecurityAlert | None) -> None:
        if alert is None:
            return
        with self._listener_lock:
            listeners = tuple(self._listeners)
        for callback in listeners:
            try:
                callback(alert)
            except Exception:
                # Delivery failure cannot undo the durable alert or verdict.
                continue

    def create_case(self, title: str, objective: str = "", *, source_kind: str = "manual",
                    source_reference: str = "", authority: str = "local-evidence",
                    case_id: str | None = None) -> InvestigationCase:
        if authority not in {"local-evidence", "reference-only"}:
            raise ValueError("Unknown investigation authority.")
        now = utc_now().isoformat()
        case = InvestigationCase(_text(case_id or "CASE-" + uuid4().hex, 160), _text(title), "review_required",
            now, now, _text(source_kind, 100), _text(source_reference), authority,
            _text(objective), 1, (), _text(objective))
        with self.store.connect(write=True) as connection:
            if source_reference and source_kind != "import":
                row = connection.execute("SELECT case_id FROM investigation_links WHERE source_kind=? AND source_reference=?", (source_kind, source_reference)).fetchone()
                if row:
                    return _require_case(connection, row[0])
            _insert_case(connection, case)
            if source_reference and source_kind != "import":
                _link(connection, source_kind, source_reference, case.case_id)
        return case

    def link_source(self, case_id: str, source_kind: str, source_reference: str) -> None:
        with self.store.connect(write=True) as connection:
            _require_case(connection, case_id)
            _link(connection, _text(source_kind, 100), _text(source_reference), case_id)

    def link_cases(self, case_id: str, related_case_id: str) -> TimelineEntry:
        related = self.get_case(related_case_id)
        if related is None:
            raise KeyError("Unknown related investigation.")
        return self.add_evidence(case_id, "related_case", "Related investigation: " + related.title,
            related_case_id, data={"case_id": related_case_id, "authority": related.authority})

    def get_case(self, case_id: str) -> InvestigationCase | None:
        with self.store.connect() as connection:
            return _get_case(connection, case_id)

    def list_cases(self, *, limit: int = 100) -> list[InvestigationCase]:
        with self.store.connect() as connection:
            rows = connection.execute("SELECT payload FROM investigation_cases ORDER BY updated_at DESC LIMIT ?", (_limit(limit),)).fetchall()
        return [_case(json.loads(row[0])) for row in rows]

    def set_phase(self, case_id: str, phase: str, *, summary: str = "") -> InvestigationCase:
        if phase not in _PHASES:
            raise ValueError("This phase cannot be assigned by an investigation runner.")
        with self.store.connect(write=True) as connection:
            current = _require_case(connection, case_id)
            if current.source_kind == "aegis" and phase == "completed":
                phase = "review_required"  # Completed diagnostics never close a threat case.
            updated = replace(current, status=phase, summary=_text(summary) or current.summary, updated_at=utc_now().isoformat(), revision=current.revision + 1)
            _save_case(connection, updated)
            _append(connection, case_id, "phase", summary or phase, "phase:" + uuid4().hex, phase, {})
            updated = _require_case(connection, case_id)
        return updated

    def add_evidence(self, case_id: str, kind: str, summary: str, source_reference: str,
                     *, status: str = "observed", data: dict | None = None, occurred_at: datetime | str | None = None) -> TimelineEntry:
        with self.store.connect(write=True) as connection:
            _require_case(connection, case_id)
            return _append(connection, case_id, kind, summary, source_reference, status, data or {}, occurred_at)

    def timeline(self, case_id: str, *, limit: int = 500) -> list[TimelineEntry]:
        with self.store.connect() as connection:
            _require_case(connection, case_id)
            rows = connection.execute("SELECT payload FROM investigation_timeline WHERE case_id=? ORDER BY occurred_at DESC,rowid DESC LIMIT ?", (case_id, _limit(limit))).fetchall()
        return [TimelineEntry(**json.loads(row[0])) for row in reversed(rows)]

    def record_aegis_case(self, source_case) -> InvestigationCase:
        record = source_case.to_record()
        source_reference = source_case.case_id + ":" + hashlib.sha256(encode(record).encode()).hexdigest()
        with self.store.connect(write=True) as connection:
            existing = _get_case(connection, source_case.case_id)
            now = source_case.updated_at.isoformat()
            candidate = InvestigationCase(source_case.case_id, "Aegis security investigation", source_case.status.value,
                source_case.created_at.isoformat(), now, "aegis", source_case.case_id, "local-evidence",
                source_case.summary, existing.revision + 1 if existing else 1,
                tuple(source_case.remaining_uncertainty), existing.objective if existing else "Investigate and verify the security evidence.")
            duplicate = connection.execute("SELECT 1 FROM investigation_timeline WHERE case_id=? AND kind='aegis_assessment' AND source_reference=?", (candidate.case_id, source_reference)).fetchone()
            if duplicate:
                return existing
            latest = connection.execute("SELECT occurred_at FROM investigation_timeline WHERE case_id=? AND kind='aegis_assessment' ORDER BY occurred_at DESC,rowid DESC LIMIT 1", (candidate.case_id,)).fetchone()
            # Journal edits have their own timestamp; only native assessment
            # timestamps may supersede another native assessment.
            if existing and (existing.status == "resolved" or (latest and latest[0] > _iso(source_case.updated_at))):
                return existing
            _save_case(connection, candidate)
            _link(connection, "aegis", source_case.case_id, candidate.case_id)
            _append(connection, candidate.case_id, "aegis_assessment", candidate.summary, source_reference,
                candidate.status, record, source_case.updated_at)
            alert = None
            if candidate.status in {"threat_confirmed", "action_pending", "monitoring"}:
                # Stable risk/identity signature avoids a new alert for elapsed timestamps.
                signature = _digest({"status": candidate.status, "nodes": sorted(node.node_id for node in source_case.evidence_nodes),
                    "coverage": source_case.coverage.to_record() if hasattr(source_case.coverage, "to_record") else record["coverage"]})
                alert = _alert(connection, "case:" + candidate.case_id, candidate.case_id, signature,
                    "critical" if candidate.status == "threat_confirmed" else "warning", candidate.summary)
            elif candidate.status == "resolved":
                _end_episode(connection, "case:" + candidate.case_id)
            candidate = _require_case(connection, candidate.case_id)
        self._notify(alert)
        return candidate

    def sync_aegis_store(self, aegis_store, *, limit: int = 100) -> None:
        """Reconcile bounded native case snapshots without querying any sensor."""
        for case in reversed(aegis_store.list_cases(limit=_limit(limit))):
            self.record_aegis_case(case)

    def record_analysis(self, case_id: str, analysis) -> TimelineEntry:
        return self.add_evidence(case_id, "file_analysis", analysis.assessment.value.replace("_", " "), analysis.analysis_id,
            status=analysis.assessment.value, occurred_at=analysis.created_at,
            data={"analysis_id": analysis.analysis_id, "path": str(analysis.path), "sha256": analysis.sha256,
                  "provider_detection_id": analysis.provider_detection_id, "remaining_uncertainty": list(analysis.remaining_uncertainty)})

    def case_for_source(self, source_kind: str, source_reference: str) -> InvestigationCase | None:
        with self.store.connect() as connection:
            row = connection.execute("SELECT case_id FROM investigation_links WHERE source_kind=? AND source_reference=?", (source_kind, source_reference)).fetchone()
            return _get_case(connection, row[0]) if row else None

    def record_remote(self, assessment) -> InvestigationCase | None:
        from aida.aegis.remote.monitor import _assessment_signature
        classification = assessment.classification.value
        signature = _digest(_assessment_signature(assessment))
        with self.store.connect(write=True) as connection:
            now = _iso(assessment.created_at)
            watermark = connection.execute("SELECT observed_at FROM source_watermarks WHERE source_key='remote'").fetchone()
            episode = connection.execute("SELECT * FROM security_episodes WHERE channel='remote' AND active=1").fetchone()
            if watermark and now <= watermark[0]:
                return _get_case(connection, episode["case_id"]) if episode else None
            connection.execute("INSERT INTO source_watermarks VALUES('remote',?,?) ON CONFLICT(source_key) DO UPDATE SET observed_at=excluded.observed_at,source_reference=excluded.source_reference",
                (now, assessment.assessment_id))
            if classification == "no_remote_activity" and not assessment.degraded_reasons:
                _end_episode(connection, "remote")
                return None
            case_id = episode["case_id"] if episode else "CASE-REMOTE-" + uuid4().hex
            existing = _get_case(connection, case_id)
            case = InvestigationCase(case_id, "Remote access investigation", "review_required", existing.created_at if existing else now,
                now, "remote", assessment.assessment_id, "local-evidence", classification.replace("_", " "),
                existing.revision + 1 if existing and episode["signature"] != signature else existing.revision if existing else 1,
                tuple(assessment.degraded_reasons) + ("Remote access observations do not prove who controls a session.",))
            _save_case(connection, case)
            _link(connection, "remote_assessment", assessment.assessment_id, case_id)
            previous_record = connection.execute("SELECT payload FROM investigation_timeline WHERE case_id=? AND kind='remote_assessment' ORDER BY rowid DESC LIMIT 1", (case_id,)).fetchone()
            content = assessment.to_record()
            previous_content = json.loads(previous_record[0])["data"] if previous_record else {}
            if _remote_content_signature(content) != _remote_content_signature(previous_content):
                _append(connection, case_id, "remote_assessment", case.summary, assessment.assessment_id,
                    classification, content, assessment.created_at)
            severity = "critical" if classification in {"confirmed_intrusion", "likely_intrusion"} else "warning"
            alert = _alert(connection, "remote", case_id, signature, severity, case.summary,
                notify=classification in _ALERT_CLASSES)
            case = _require_case(connection, case_id)
        self._notify(alert)
        return case

    def end_remote_episode(self) -> None:
        with self.store.connect(write=True) as connection:
            _end_episode(connection, "remote")

    def list_alerts(self, *, include_acknowledged: bool = False, limit: int = 100) -> list[SecurityAlert]:
        with self.store.connect() as connection:
            rows = connection.execute("SELECT * FROM security_alerts " + ("" if include_acknowledged else "WHERE acknowledged_at IS NULL AND ended_at IS NULL ") + "ORDER BY created_at DESC LIMIT ?", (_limit(limit),)).fetchall()
        return [_alert_record(row) for row in rows]

    def acknowledge_alert(self, alert_id: str) -> SecurityAlert:
        with self.store.connect(write=True) as connection:
            connection.execute("UPDATE security_alerts SET acknowledged_at=COALESCE(acknowledged_at,?),updated_at=? WHERE alert_id=?", (utc_now().isoformat(), utc_now().isoformat(), alert_id))
            row = connection.execute("SELECT * FROM security_alerts WHERE alert_id=?", (alert_id,)).fetchone()
            if row is None:
                raise KeyError("Unknown security alert.")
        return _alert_record(row)

    def record_action(self, case_id: str, action_type: str, outcome: str, *, evidence_refs=(),
                      source_reference: str | None = None, detail: str = "", provider_verified: bool = False) -> TimelineEntry:
        if outcome not in _OUTCOMES:
            raise ValueError("Unknown action outcome.")
        case = self.get_case(case_id)
        if case is None or case.authority != "local-evidence":
            raise ValueError("Imported reference evidence cannot receive local action authority.")
        return self.add_evidence(case_id, "action_result", detail or f"{action_type}: {outcome}",
            source_reference or "action:" + uuid4().hex, status=outcome,
            data={"action_type": _text(action_type, 100), "provider_verified": provider_verified is True,
                  "evidence_refs": [_text(str(value), 160) for value in list(evidence_refs)[:32]]})

    def record_sentry(self, plan, result) -> None:
        case = self.case_for_source("remote_assessment", plan.assessment_id)
        if case is None:
            return
        state = result.state.value
        self.record_action(case.case_id, "sentry_containment", "succeeded" if state == "completed" else "partial" if state == "partial" else "failed",
            source_reference=plan.plan_id, evidence_refs=(plan.assessment_id,),
            detail="Sentry containment " + state + ". Containment does not resolve the investigation.",
            provider_verified=result.verification_complete and state == "completed")

    def record_sentry_interruption(self, plan) -> None:
        case = self.case_for_source("remote_assessment", plan.assessment_id)
        if case is not None:
            self.record_action(case.case_id, "sentry_containment", "interrupted", source_reference=plan.plan_id,
                evidence_refs=(plan.assessment_id,), detail="Sentry execution was interrupted. Review its native ledger for individual target outcomes; no overall success is assumed.")

    def record_verification(self, case_id: str, verification_case) -> TimelineEntry:
        from aida.aegis.store import _verified_clean_case
        case = self.get_case(case_id)
        if case is None or case.authority != "local-evidence":
            raise ValueError("Verification requires a local investigation.")
        with self.store.connect() as connection:
            after = _latest_relevant_evidence(connection, case)
        valid = _verified_clean_case(verification_case) and verification_case.provider_scan_started_at.isoformat() > after
        return self.add_evidence(case_id, "verification", "Full-scan verification " + ("qualified for review." if valid else "did not qualify; further evidence is required."),
            verification_case.case_id, status="verified" if valid else "incomplete",
            data={"verification_case_id": verification_case.case_id, "provider_scan_id": verification_case.provider_scan_id,
                  "provider_scan_started_at": _iso(verification_case.provider_scan_started_at) if verification_case.provider_scan_started_at else None,
                  "provider_verified": verification_case.provider_verified is True}, occurred_at=verification_case.updated_at)

    def prepare_response(self, case_id: str) -> ResponseWorkflow:
        with self.store.connect(write=True) as connection:
            case = _require_case(connection, case_id)
            if case.authority != "local-evidence":
                raise PermissionError("Imported cases are reference-only. Collect fresh local evidence in a new investigation.")
            security = case.source_kind in {"aegis", "file", "remote", "event_channel"}
            steps = (
            ResponseStep("inspect", "inspect", "Review current local evidence", "available", False,
                explanation="Collect a fresh analysis or remote assessment. Stored text is evidence, never a command."),
            ResponseStep("respond", "respond", "Review a supported response", "review_required", True,
                explanation="Choose guarded Defender remediation or exact Sentry containment only when its own current prerequisites pass."),
            ResponseStep("verify", "verify", "Run and review a new full security scan", "review_required", True,
                explanation="A response result does not prove the machine is clean. A new scan needs separate authorization."),
            ResponseStep("close", "close", "Review case closure using later verified evidence", "review_required", True,
                explanation="Closure remains subject to the Aegis evidence and confirmation boundary."),
            ) if security else (
                ResponseStep("inspect", "inspect", "Review the collected Engine evidence", "available", False,
                    explanation="Compare observations, confidence and unavailable checks. Evidence does not establish a cause by itself."),
                ResponseStep("respond", "respond", "Choose a supported next check or intervention", "review_required", True,
                    explanation="Review the exact target and expected effect. Any system change keeps its own authorization boundary."),
                ResponseStep("verify", "verify", "Review fresh evidence after the intervention", "review_required", False,
                    explanation="Repeat the relevant read-only checks and compare their evidence before claiming improvement."),
                ResponseStep("close", "close", "Review the conclusion and remaining uncertainty", "review_required", True,
                    explanation="Only explicit review of the current case can record a conclusion; collection completion does not prove a cause."),
            )
            plan_id, created_at = "PLAN-" + uuid4().hex, utc_now().isoformat()
            _append(connection, case_id, "response_plan", "Prepared a response review; no action or reusable approval was stored.", plan_id, "review_required", {})
            case = _require_case(connection, case_id)
            plan = ResponseWorkflow(plan_id, case_id, case.revision, "review_required", created_at, steps)
            connection.execute("INSERT INTO investigation_plans VALUES(?,?,?,?)", (plan.plan_id, case_id, plan.created_at, encode(plan.to_record())))
        return plan

    def review_conclusion(self, case_id: str, summary: str, *, expected_revision: int, user_reviewed: bool = False) -> InvestigationCase:
        if user_reviewed is not True:
            raise PermissionError("A conclusion requires explicit review of the current case.")
        with self.store.connect(write=True) as connection:
            current = _require_case(connection, case_id)
            if current.authority != "local-evidence" or current.source_kind not in {"aida.investigation", "manual"}:
                raise PermissionError("Security cases require their separate verified resolution workflow.")
            if current.revision != expected_revision:
                raise RuntimeError("The case changed; review its current evidence before recording a conclusion.")
            _append(connection, case_id, "human_review", _text(summary), "conclusion:" + uuid4().hex, "reviewed", {})
            current = _require_case(connection, case_id)
            result = replace(current, status="reviewed", summary=_text(summary))
            _save_case(connection, result)
            return result

    def get_plan(self, plan_id: str) -> ResponseWorkflow | None:
        with self.store.connect() as connection:
            row = connection.execute("SELECT payload FROM investigation_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        case = self.get_case(record["case_id"])
        entries = self.timeline(record["case_id"])
        with self.store.connect() as connection:
            latest_action = _latest_relevant_evidence(connection, case)
        steps = []
        for item in record["steps"]:
            evidence = next((entry for entry in reversed(entries)
                if entry.recorded_at >= record["created_at"] and
                ((item["kind"] == "inspect" and entry.kind in {"file_analysis", "remote_assessment", "engine_observation"}) or
                 (item["kind"] == "respond" and entry.kind == "action_result") or
                 (item["kind"] == "verify" and entry.kind == "verification"))), None)
            if evidence:
                complete = evidence.status in {"observed", "assessed", "low_concern", "suspicious", "likely_malicious", "provider_confirmed_malicious", "unauthorized_suspected", "likely_intrusion", "confirmed_intrusion", "authorized_support", "support_session_anomalous", "remote_access_observed", "no_remote_activity"}
                if item["kind"] == "respond":
                    complete = evidence.status == "succeeded" and evidence.data.get("provider_verified") is True
                if item["kind"] == "verify":
                    scan_start = evidence.data.get("provider_scan_started_at")
                    complete = (evidence.status == "verified" and evidence.data.get("provider_verified") is True
                        and isinstance(scan_start, str) and scan_start > latest_action)
                item["state"] = "completed" if complete else "review_required"
                item["evidence_reference"] = evidence.source_reference
            if item["kind"] == "close" and case.status in {"resolved", "reviewed"}:
                item["state"] = "completed"
            steps.append(ResponseStep(**item))
        state = "completed" if case.status in {"resolved", "reviewed"} else "verification_required" if steps[1].state == "completed" and steps[2].state != "completed" else "review_required"
        return ResponseWorkflow(record["plan_id"], record["case_id"], record["case_revision"], state, record["created_at"], tuple(steps))

    def export_payload(self, case_id: str, *, redact: bool = True) -> dict:
        case = self.get_case(case_id)
        if case is None:
            raise KeyError("Unknown investigation.")
        entries = self.timeline(case_id)
        evidence = [{"id": row.event_id, "kind": row.kind, "occurredAt": row.occurred_at,
            "summary": (row.kind.replace("_", " ") + ": " + row.status) if redact else row.summary,
            "sourceReference": "reference:" + _digest(row.source_reference)[:24] if redact else row.source_reference,
            "status": row.status} for row in entries]
        payload = {"schemaVersion": 1, "authority": "reference-only", "caseId": case.case_id,
            "title": "AIDA investigation" if redact else case.title, "createdAt": case.created_at,
            "exportedAt": utc_now().isoformat(), "redacted": bool(redact),
            "source": {"instanceId": "instance:" + _digest(self.instance_id)[:16] if redact else self.instance_id, "platform": self.platform},
            "evidence": evidence, "findings": ["Investigation status: " + case.status] if redact else [case.summary],
            "unresolvedQuestions": ["Review the original local evidence and its visibility limitations."] if redact and case.unresolved_questions else list(case.unresolved_questions),
            "completedChecks": sorted({row.kind for row in entries if row.status in {"succeeded", "completed", "assessed", "resolved"}})}
        validate_import(payload)
        return payload

    def export_case(self, case_id: str, path: str | Path, *, redact: bool = True) -> Path:
        target = Path(path)
        payload = self.export_payload(case_id, redact=redact)
        # Do not overwrite user files or implicitly send evidence anywhere.
        with target.open("x", encoding="utf-8") as output:
            output.write(encode(payload))
        return target

    def import_case(self, payload: dict | str, *, reviewed: bool = False) -> InvestigationCase:
        value = validate_import(payload)
        if not reviewed:
            raise PermissionError("Review the case preview before importing reference evidence.")
        now = utc_now().isoformat()
        case = InvestigationCase("IMPORT-" + uuid4().hex, value["title"], "review_required", now, now,
            "import", value["caseId"], "reference-only", "Imported reference; collect fresh local evidence before action.", 1)
        with self.store.connect(write=True) as connection:
            _insert_case(connection, case)
            for row in value["evidence"]:
                _append(connection, case.case_id, "imported_reference", row["summary"], "import:" + row["id"],
                    "reference_only", {"source": value["source"], "original_kind": row["kind"], "original_status": row["status"]}, row["occurredAt"])
            _append(connection, case.case_id, "imported_findings", "Imported findings and questions require independent local verification.",
                "import:findings", "reference_only", {key: value[key] for key in ("findings", "unresolvedQuestions", "completedChecks")})
            return _require_case(connection, case.case_id)


def validate_import(payload: dict | str) -> dict:
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Imported case exceeds one MiB.")
        payload = json.loads(payload)
    if not isinstance(payload, dict) or len(encode(payload).encode("utf-8")) > 1024 * 1024:
        raise ValueError("Invalid imported case.")
    allowed = {"schemaVersion", "authority", "caseId", "title", "createdAt", "source", "evidence", "findings", "unresolvedQuestions", "completedChecks", "exportedAt", "redacted"}
    if set(payload) - allowed or type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1 or payload.get("authority") != "reference-only":
        raise ValueError("Only the reference-only case exchange schema is accepted.")
    if not _text(payload.get("caseId"), 160):
        raise ValueError("Case identity cannot be empty.")
    _text(payload.get("title")); _import_time(payload.get("createdAt"))
    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {"instanceId", "platform"}:
        raise ValueError("Invalid case source.")
    _text(source["instanceId"], 160); _text(source["platform"], 160)
    for name in ("findings", "unresolvedQuestions", "completedChecks"):
        items = payload.get(name)
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("Invalid bounded case text list.")
        for item in items:
            _text(item)
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 500:
        raise ValueError("Invalid bounded evidence list.")
    seen = set()
    for row in evidence:
        if not isinstance(row, dict) or set(row) != {"id", "kind", "occurredAt", "summary", "sourceReference", "status"}:
            raise ValueError("Invalid case evidence entry.")
        for name in ("id", "kind", "status"):
            _text(row[name], 160)
        if not row["id"] or row["id"] in seen:
            raise ValueError("Evidence identities must be nonempty and unique.")
        seen.add(row["id"])
        _text(row["summary"]); _text(row["sourceReference"]); _import_time(row["occurredAt"])
    if "exportedAt" in payload:
        _import_time(payload["exportedAt"])
    if "redacted" in payload and type(payload["redacted"]) is not bool:
        raise ValueError("Invalid redaction flag.")
    return json.loads(encode(payload))


def _text(value, limit=4000) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("Invalid or oversized investigation text.")
    return value


def _import_time(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", _text(value, 50)):
        raise ValueError("Case timestamps require ISO-8601 date/time and timezone.")
    return _iso(value)


def _iso(value=None) -> str:
    if value is None:
        return utc_now().isoformat()
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(_text(value, 80).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps require a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def _limit(value) -> int:
    return max(1, min(int(value), 500))


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _remote_content_signature(record) -> str:
    return _digest({key: value for key, value in record.items() if key not in {"assessment_id", "created_at"}})


def _case(record) -> InvestigationCase:
    record["unresolved_questions"] = tuple(record.get("unresolved_questions", ()))
    return InvestigationCase(**record)


def _get_case(connection, case_id):
    row = connection.execute("SELECT payload FROM investigation_cases WHERE case_id=?", (case_id,)).fetchone()
    return _case(json.loads(row[0])) if row else None


def _require_case(connection, case_id):
    case = _get_case(connection, case_id)
    if case is None:
        raise KeyError("Unknown investigation.")
    return case


def _latest_relevant_evidence(connection, case):
    row = connection.execute("SELECT MAX(occurred_at) FROM investigation_timeline WHERE case_id=? AND kind IN ('action_result','file_analysis','remote_assessment','engine_observation','aegis_assessment') AND (kind<>'aegis_assessment' OR json_extract(payload,'$.status')<>'resolved')", (case.case_id,)).fetchone()
    return max(case.created_at, row[0] or case.created_at)


def _insert_case(connection, case):
    connection.execute("INSERT INTO investigation_cases VALUES(?,?,?)", (case.case_id, case.updated_at, encode(case.to_record())))


def _save_case(connection, case):
    connection.execute("INSERT INTO investigation_cases VALUES(?,?,?) ON CONFLICT(case_id) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload", (case.case_id, case.updated_at, encode(case.to_record())))


def _link(connection, kind, reference, case_id):
    connection.execute("INSERT OR IGNORE INTO investigation_links VALUES(?,?,?)", (kind, reference, case_id))


def _append(connection, case_id, kind, summary, reference, status, data, occurred_at=None):
    existing = connection.execute("SELECT payload FROM investigation_timeline WHERE case_id=? AND kind=? AND source_reference=?", (case_id, kind, reference)).fetchone()
    if existing:
        return TimelineEntry(**json.loads(existing[0]))
    record = TimelineEntry(uuid4().hex, case_id, _text(kind, 100), _iso(occurred_at), utc_now().isoformat(),
        _text(summary), _text(reference), _text(status, 160), data)
    connection.execute("INSERT INTO investigation_timeline VALUES(?,?,?,?,?,?)", (record.event_id, case_id, record.occurred_at, kind, reference, encode(record.to_record())))
    current = _require_case(connection, case_id)
    _save_case(connection, replace(current, updated_at=max(current.updated_at, record.recorded_at), revision=current.revision + 1))
    _link(connection, kind, reference, case_id)
    return record


def _alert(connection, channel, case_id, signature, severity, message, *, notify=True):
    now = utc_now().isoformat()
    episode = connection.execute("SELECT * FROM security_episodes WHERE channel=? AND active=1", (channel,)).fetchone()
    episode_id = episode["episode_id"] if episode else uuid4().hex
    changed = not episode or episode["signature"] != signature
    connection.execute("INSERT INTO security_episodes VALUES(?,?,?,?,1,?) ON CONFLICT(channel) DO UPDATE SET episode_id=excluded.episode_id,case_id=excluded.case_id,signature=excluded.signature,active=1,last_seen=excluded.last_seen", (channel, episode_id, case_id, signature, now))
    if changed:
        connection.execute("UPDATE security_alerts SET ended_at=COALESCE(ended_at,?),updated_at=? WHERE episode_id=? AND signature<>?", (now, now, episode_id, signature))
    if not notify:
        return None
    existing = connection.execute("SELECT * FROM security_alerts WHERE episode_id=? AND signature=?", (episode_id, signature)).fetchone()
    if existing and existing["ended_at"] is None:
        connection.execute("UPDATE security_alerts SET updated_at=? WHERE alert_id=?", (now, existing["alert_id"]))
        return None
    # A signature that recurs after a different state is a new alert episode.
    if existing:
        episode_id = uuid4().hex
        connection.execute("UPDATE security_episodes SET episode_id=? WHERE channel=?", (episode_id, channel))
    alert_id = "ALERT-" + uuid4().hex
    connection.execute("INSERT INTO security_alerts VALUES(?,?,?,?,?,?,NULL,NULL,?,?)", (alert_id, case_id, episode_id, signature, now, now, severity, _text(message)))
    return _alert_record(connection.execute("SELECT * FROM security_alerts WHERE alert_id=?", (alert_id,)).fetchone())


def _end_episode(connection, channel):
    now = utc_now().isoformat()
    episode = connection.execute("SELECT * FROM security_episodes WHERE channel=? AND active=1", (channel,)).fetchone()
    if episode:
        connection.execute("UPDATE security_episodes SET active=0,last_seen=? WHERE channel=?", (now, channel))
        connection.execute("UPDATE security_alerts SET ended_at=COALESCE(ended_at,?),updated_at=? WHERE episode_id=?", (now, now, episode["episode_id"]))
        _append(connection, episode["case_id"], "activity_ended", "Observed activity episode ended. This does not resolve the security case.",
            "episode:" + episode["episode_id"], "ended", {})


def _alert_record(row):
    return SecurityAlert(**{key: row[key] for key in SecurityAlert.__dataclass_fields__})
