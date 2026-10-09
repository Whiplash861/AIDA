from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from aida.artificer.models import ModificationAttempt
from aida.artificer.state_file import locked_state
from aida.artificer.validator import ValidationCheck, ValidationReport


class ForgeError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Forge:
    """Governed candidate validation with a durable prepare/apply record."""

    def __init__(self, *, source_root, ledger, policy, warden, validator, rollback):
        self.source_root = Path(source_root).resolve()
        self.ledger, self.policy, self.warden = ledger, policy, warden
        self.validator, self.rollback = validator, rollback

    def _target(self, relative_path: str, rule_id: str) -> tuple[Path, object]:
        target = (self.source_root / relative_path).resolve()
        try:
            target.relative_to(self.source_root)
        except ValueError as exc:
            raise ForgeError("Target escapes the source root") from exc
        rule = self.policy.get_rule(rule_id)
        # No target content or rollback asset is read before this gate.
        if rule is None or self.policy.is_protected(target) or not self.policy.is_path_allowed(target, rule):
            raise ForgeError("Protected target or unsupported maintenance scope")
        if not target.is_file():
            raise ForgeError("Target must be an existing regular file")
        return target, rule

    def apply_text_replacement(self, *, relative_path: str, new_content: str,
                               rule_id: str, confidence: float, evidence_quality: float,
                               implementation_risk: float, owner_approved: bool = False,
                               approval_token: str | None = None, proposal_id: str | None = None,
                               test_paths: tuple[str, ...] = ()) -> ModificationAttempt:
        target, rule = self._target(relative_path, rule_id)
        canonical = target.relative_to(self.source_root).as_posix()
        original_bytes = target.read_bytes()
        original = original_bytes.decode("utf-8")
        proposed_bytes = new_content.encode("utf-8")
        original_hash, proposed_hash = _sha(original_bytes), _sha(proposed_bytes)
        # A caller-provided Boolean is not a scoped authorization token.
        approved = bool(approval_token and self.warden.consume_approval(
            approval_token, path=canonical, rule_id=rule_id,
            original_sha256=original_hash, proposed_sha256=proposed_hash))
        diff = list(difflib.unified_diff(original.splitlines(), new_content.splitlines(),
                                       fromfile=f"a/{canonical}", tofile=f"b/{canonical}", lineterm=""))
        changed = sum(line.startswith(("+", "-")) and not line.startswith(("+++", "---")) for line in diff)
        decision = self.warden.authorize(path=canonical, rule_id=rule_id, confidence=confidence,
            evidence_quality=evidence_quality, implementation_risk=implementation_risk,
            rollback_ready=True, changed_lines=changed, owner_approved=approved)
        attempt = ModificationAttempt(
            attempt_id=f"AE-MOD-{uuid.uuid4().hex[:12].upper()}", proposal_id=proposal_id,
            path=canonical, rule_id=rule_id, authority_level=decision.authority.value,
            original_sha256=original_hash, proposed_sha256=proposed_hash,
            diff_text="\n".join(diff), status="rejected", validation_summary=decision.reason, rollback_path=None)
        if not decision.allowed:
            self.ledger.append_modification_attempt(attempt)
            return attempt
        # Behavioral/data changes need explicit relevant tests. Format-only AST
        # equivalence is the single exception allowed by the maintenance rule.
        if not rule.requires_ast_equivalence and not test_paths:
            attempt = replace(attempt, status="validation_failed", validation_summary="Relevant candidate tests are required")
            self.ledger.append_modification_attempt(attempt)
            return attempt
        for test_path in test_paths:
            path = Path(test_path)
            if path.is_absolute() or ".." in path.parts or test_path.startswith("-"):
                raise ForgeError("Tests must be source-relative file paths")
        with tempfile.TemporaryDirectory(prefix="aida_artificer_forge_") as temporary_dir:
            workspace = Path(temporary_dir) / "source"
            def ignore(directory, names):
                return [name for name in names if name in {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
                        or name.startswith(".env") or (Path(directory) / name).is_symlink()]
            shutil.copytree(self.source_root, workspace, ignore=ignore)
            candidate = workspace / canonical
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(proposed_bytes)
            validation = (self.validator.validate_python_file(candidate, original_source=original,
                          require_ast_equivalence=rule.requires_ast_equivalence)
                          if target.suffix.lower() == ".py" else self.validator.validate_data_file(candidate))
            if validation.passed and test_paths:
                test = self.validator.run_tests(workspace, test_paths=test_paths)
                validation = ValidationReport(test.passed, validation.checks + (test,))
            for check in validation.checks:
                self.ledger.append_validation_result(attempt_id=attempt.attempt_id, passed=check.passed,
                                                     check_name=check.name, detail=check.detail)
            if not validation.passed:
                attempt = replace(attempt, status="validation_failed",
                                  validation_summary="; ".join(f"{check.name}: {check.detail}" for check in validation.checks))
                self.ledger.append_modification_attempt(attempt)
                return attempt
        # Serialize Forge instances; external edits are also checked immediately
        # before replacement. The prepared record supports interrupted-run review.
        with locked_state(self.rollback.rollback_root / "forge-operation"):
            with self.ledger._lock, self.ledger._connect() as connection:
                pending = connection.execute("SELECT attempt_id FROM modification_attempts WHERE path=? AND status IN ('prepared','rollback_prepared')", (canonical,)).fetchone()
            if pending:
                raise ForgeError("An interrupted change for this path requires recovery review first")
            current_target, _ = self._target(canonical, rule_id)
            if current_target != target or _sha(target.read_bytes()) != original_hash:
                attempt = replace(attempt, status="source_changed", validation_summary="Source changed during validation; review a fresh candidate")
                self.ledger.append_modification_attempt(attempt)
                return attempt
            backup = self.rollback.create_backup(target, attempt.attempt_id)
            if _sha(backup.read_bytes()) != original_hash:
                raise ForgeError("Source changed while creating the rollback asset")
            attempt = replace(attempt, status="prepared", rollback_path=str(backup), validation_summary="Candidate validation passed")
            self.ledger.append_modification_attempt(attempt)
            descriptor, filename = tempfile.mkstemp(prefix=target.name + ".artificer.", dir=target.parent)
            temporary = Path(filename)
            replaced = False
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(proposed_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                if _sha(target.read_bytes()) != original_hash:
                    raise ForgeError("Source changed immediately before application")
                os.replace(temporary, target)
                replaced = True
                if _sha(target.read_bytes()) != proposed_hash:
                    raise ForgeError("Applied content failed verification")
                attempt = replace(attempt, status="applied_restart_required" if target.suffix.lower() == ".py" else "applied",
                                  validation_summary="Candidate checks passed; applied bytes verified")
                self.ledger.append_modification_attempt(attempt)
            except Exception:
                # Do not overwrite an unrelated edit made after our replacement.
                if replaced and target.exists() and _sha(target.read_bytes()) == proposed_hash:
                    self.rollback.restore(backup, target)
                try:
                    self.ledger.append_modification_attempt(replace(attempt, status="application_failed", validation_summary="Apply interrupted; original restored when identity remained unchanged"))
                except Exception:
                    pass  # Durable prepared record remains for recovery inspection.
                raise
            finally:
                temporary.unlink(missing_ok=True)
        return attempt

    def inspect_pending_recovery(self) -> list[dict[str, str]]:
        """Report interrupted transactions without silently changing source files."""
        pending = []
        with self.ledger._lock, self.ledger._connect() as connection:
            rows = connection.execute("SELECT attempt_id,payload_json FROM modification_attempts WHERE status IN ('prepared','rollback_prepared')").fetchall()
        import json
        for row in rows:
            record = json.loads(row["payload_json"])
            try:
                target, _ = self._target(record["path"], record["rule_id"])
                digest = _sha(target.read_bytes())
                state = ("original_present" if digest == record["original_sha256"] else
                         "candidate_present" if digest == record["proposed_sha256"] else "source_changed")
            except (OSError, ForgeError, KeyError):
                state = "unavailable"
            pending.append({"attempt_id": row["attempt_id"], "source_state": state,
                            "action": "Review interrupted application before applying another change"})
        return pending

    def rollback_attempt(self, attempt: ModificationAttempt, *, approval_token: str | None = None) -> None:
        stored = self.ledger.get_modification_attempt(attempt.attempt_id)
        if stored != attempt.to_record() or attempt.status not in {"applied", "applied_restart_required"}:
            raise ForgeError("Rollback requires the exact audited applied attempt")
        target, rule = self._target(attempt.path, attempt.rule_id)
        approved = bool(approval_token and self.warden.consume_approval(
            approval_token, path=attempt.path, rule_id=attempt.rule_id,
            original_sha256=attempt.proposed_sha256, proposed_sha256=attempt.original_sha256))
        if rule.requires_owner_approval and not approved:
            raise ForgeError("Rollback requires fresh scoped owner approval")
        if not attempt.rollback_path:
            raise ForgeError("Missing rollback asset")
        backup = Path(attempt.rollback_path).resolve()
        try:
            backup.relative_to(self.rollback.rollback_root.resolve())
        except ValueError as exc:
            raise ForgeError("Rollback asset escaped its store") from exc
        with locked_state(self.rollback.rollback_root / "forge-operation"):
            if _sha(backup.read_bytes()) != attempt.original_sha256 or _sha(target.read_bytes()) != attempt.proposed_sha256:
                raise ForgeError("Rollback content or current source no longer matches the audited identity")
            self.ledger.append_modification_attempt(replace(attempt, status="rollback_prepared"))
            self.rollback.restore(backup, target)
            if _sha(target.read_bytes()) != attempt.original_sha256:
                raise ForgeError("Rollback verification failed")
            self.ledger.append_modification_attempt(replace(attempt, status="rolled_back"))
            self.ledger.append_rollback_event(attempt.attempt_id, "completed", "Original bytes verified")
