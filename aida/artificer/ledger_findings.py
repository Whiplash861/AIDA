from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from aida.artificer.ledger_records import finding_from_record, proposal_from_record
from aida.artificer.models import ArtificerFinding, UpgradeProposal, utc_now


class LedgerFindingsMixin:
    def upsert_finding(self, finding: ArtificerFinding) -> ArtificerFinding:
        fingerprint = finding.fingerprint or finding.finding_id
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM artificer_findings WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if existing:
                previous = finding_from_record(json.loads(existing["payload_json"]))
                finding = ArtificerFinding(
                    finding_id=previous.finding_id,
                    category=finding.category,
                    title=finding.title,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    evidence_quality=finding.evidence_quality,
                    affected_components=finding.affected_components,
                    first_seen_utc=previous.first_seen_utc,
                    last_seen_utc=finding.last_seen_utc,
                    observation_count=max(
                        previous.observation_count,
                        finding.observation_count,
                    ),
                    finding=finding.finding,
                    evidence_summary=finding.evidence_summary,
                    reasoning_summary=finding.reasoning_summary,
                    recommended_change=finding.recommended_change,
                    expected_outcomes=finding.expected_outcomes,
                    implementation_risk=finding.implementation_risk,
                    regression_risk=finding.regression_risk,
                    authority_required=finding.authority_required,
                    status=(
                        "open" if previous.status == "resolved" else previous.status
                    ),
                    fingerprint=fingerprint,
                )
            payload = finding.to_record()
            connection.execute(
                """INSERT INTO artificer_findings(
                    finding_id,fingerprint,category,title,severity,confidence,evidence_quality,
                    first_seen_utc,last_seen_utc,observation_count,status,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    category=excluded.category,title=excluded.title,severity=excluded.severity,
                    confidence=excluded.confidence,evidence_quality=excluded.evidence_quality,
                    last_seen_utc=excluded.last_seen_utc,
                    observation_count=excluded.observation_count,status=excluded.status,
                    payload_json=excluded.payload_json""",
                (
                    finding.finding_id,
                    fingerprint,
                    finding.category,
                    finding.title,
                    finding.severity,
                    finding.confidence,
                    finding.evidence_quality,
                    finding.first_seen_utc.isoformat(),
                    finding.last_seen_utc.isoformat(),
                    finding.observation_count,
                    finding.status,
                    self._json(payload),
                ),
            )
            self._chain(connection, "artificer_finding", finding.finding_id, payload)
        return finding

    def resolve_absent_findings(
        self,
        *,
        active_fingerprints: Iterable[str],
        fingerprint_prefixes: Iterable[str],
    ) -> int:
        active = {value for value in active_fingerprints if value}
        prefixes = tuple(value for value in fingerprint_prefixes if value)
        if not prefixes:
            return 0

        resolved = 0
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT finding_id,fingerprint,payload_json
                FROM artificer_findings WHERE status='open'"""
            ).fetchall()
            for row in rows:
                fingerprint = str(row["fingerprint"] or "")
                if not fingerprint.startswith(prefixes) or fingerprint in active:
                    continue
                payload = json.loads(row["payload_json"])
                payload["status"] = "resolved"
                connection.execute(
                    """UPDATE artificer_findings
                    SET status='resolved',payload_json=? WHERE finding_id=?""",
                    (self._json(payload), row["finding_id"]),
                )
                self._chain(
                    connection,
                    "finding_status",
                    row["finding_id"],
                    {
                        "status": "resolved",
                        "reason": "Not reproduced by the latest deterministic review.",
                        "fingerprint": fingerprint,
                    },
                )
                resolved += 1
        return resolved

    def list_findings(
        self, *, status: str | None = "open", limit: int = 100
    ) -> list[ArtificerFinding]:
        query = "SELECT payload_json FROM artificer_findings"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status=?"
            parameters.append(status)
        query += " ORDER BY last_seen_utc DESC LIMIT ?"
        parameters.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [finding_from_record(json.loads(row["payload_json"])) for row in rows]

    def set_finding_status(self, finding_id: str, status: str) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM artificer_findings WHERE finding_id=?",
                (finding_id,),
            ).fetchone()
            if not row:
                raise KeyError(finding_id)
            payload = json.loads(row["payload_json"])
            payload["status"] = status
            connection.execute(
                "UPDATE artificer_findings SET status=?,payload_json=? WHERE finding_id=?",
                (status, self._json(payload), finding_id),
            )
            self._chain(connection, "finding_status", finding_id, {"status": status})

    def store_proposal(self, proposal: UpgradeProposal) -> None:
        payload = proposal.to_record()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO upgrade_proposals VALUES(?,?,?,?)",
                (
                    proposal.proposal_id,
                    proposal.status,
                    proposal.created_at_utc.isoformat(),
                    self._json(payload),
                ),
            )
            self._chain(connection, "upgrade_proposal", proposal.proposal_id, payload)

    def list_proposals(
        self, *, status: str | None = "pending"
    ) -> list[UpgradeProposal]:
        query = "SELECT payload_json FROM upgrade_proposals"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status=?"
            parameters.append(status)
        query += " ORDER BY created_at_utc DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [proposal_from_record(json.loads(row["payload_json"])) for row in rows]

    def record_proposal_decision(
        self,
        *,
        proposal_id: str,
        decision: str,
        developer_id: str,
        reason: str,
    ) -> None:
        decided_at = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM upgrade_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if not row:
                raise KeyError(proposal_id)
            payload = json.loads(row["payload_json"])
            payload["status"] = decision
            connection.execute(
                "UPDATE upgrade_proposals SET status=?,payload_json=? WHERE proposal_id=?",
                (decision, self._json(payload), proposal_id),
            )
            connection.execute(
                """INSERT INTO proposal_decisions(
                    proposal_id,decision,developer_id,reason,decided_at_utc
                ) VALUES(?,?,?,?,?)""",
                (proposal_id, decision, developer_id, reason, decided_at),
            )
            self._chain(
                connection,
                "proposal_decision",
                proposal_id,
                {
                    "proposal_id": proposal_id,
                    "decision": decision,
                    "developer_id": developer_id,
                    "reason": reason,
                    "decided_at_utc": decided_at,
                },
            )
