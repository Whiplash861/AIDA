from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from aida.artificer.ledger import ArtificerLedger
from aida.artificer.models import ModificationAttempt
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.rollback import RollbackManager
from aida.artificer.validator import ValidationReport, Validator
from aida.artificer.warden import Warden


class ForgeError(RuntimeError):
    pass


class Forge:
    """Creates minimal, validated, reversible modifications."""

    def __init__(
        self,
        *,
        source_root: str | Path,
        ledger: ArtificerLedger,
        policy: ArtificerPolicy,
        warden: Warden,
        validator: Validator,
        rollback: RollbackManager,
    ) -> None:
        self.source_root = Path(source_root).resolve()
        self.ledger = ledger
        self.policy = policy
        self.warden = warden
        self.validator = validator
        self.rollback = rollback

    def apply_text_replacement(
        self,
        *,
        relative_path: str,
        new_content: str,
        rule_id: str,
        confidence: float,
        evidence_quality: float,
        implementation_risk: float,
        owner_approved: bool = False,
        proposal_id: str | None = None,
        test_paths: tuple[str, ...] = (),
    ) -> ModificationAttempt:
        target = (self.source_root / relative_path).resolve()
        try:
            target.relative_to(self.source_root)
        except ValueError as exc:
            raise ForgeError("Target escapes the configured AIDA source root") from exc
        if not target.exists() or not target.is_file():
            raise ForgeError(f"Target file does not exist: {relative_path}")

        original = target.read_text(encoding="utf-8")
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        changed_lines = sum(
            1
            for line in diff_lines
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        )
        attempt_id = f"AE-MOD-{uuid.uuid4().hex[:12].upper()}"
        backup = self.rollback.create_backup(target, attempt_id)
        decision = self.warden.authorize(
            path=relative_path,
            rule_id=rule_id,
            confidence=confidence,
            evidence_quality=evidence_quality,
            implementation_risk=implementation_risk,
            rollback_ready=backup.exists(),
            changed_lines=changed_lines,
            owner_approved=owner_approved,
        )
        original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
        proposed_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        if not decision.allowed:
            attempt = ModificationAttempt(
                attempt_id=attempt_id,
                proposal_id=proposal_id,
                path=relative_path,
                rule_id=rule_id,
                authority_level=decision.authority.value,
                original_sha256=original_hash,
                proposed_sha256=proposed_hash,
                diff_text="\n".join(diff_lines),
                status="rejected",
                validation_summary=decision.reason,
                rollback_path=str(backup),
            )
            self.ledger.append_modification_attempt(attempt)
            return attempt

        rule = self.policy.get_rule(rule_id)
        assert rule is not None
        workspace = Path(tempfile.mkdtemp(prefix="aida_artificer_forge_"))
        candidate = workspace / target.name
        candidate.write_text(new_content, encoding="utf-8")
        validation = self.validator.validate_python_file(
            candidate,
            original_source=original,
            require_ast_equivalence=rule.requires_ast_equivalence,
        ) if target.suffix.lower() == ".py" else ValidationReport(True, ())
        for check in validation.checks:
            self.ledger.append_validation_result(
                attempt_id=attempt_id,
                passed=check.passed,
                check_name=check.name,
                detail=check.detail,
            )
        if validation.passed and test_paths:
            test_check = self.validator.run_tests(self.source_root, test_paths=test_paths)
            self.ledger.append_validation_result(
                attempt_id=attempt_id,
                passed=test_check.passed,
                check_name=test_check.name,
                detail=test_check.detail,
            )
            validation = ValidationReport(test_check.passed, validation.checks + (test_check,))

        if not validation.passed:
            shutil.rmtree(workspace, ignore_errors=True)
            attempt = ModificationAttempt(
                attempt_id=attempt_id,
                proposal_id=proposal_id,
                path=relative_path,
                rule_id=rule_id,
                authority_level=decision.authority.value,
                original_sha256=original_hash,
                proposed_sha256=proposed_hash,
                diff_text="\n".join(diff_lines),
                status="validation_failed",
                validation_summary="; ".join(
                    f"{check.name}={'pass' if check.passed else 'fail'}" for check in validation.checks
                ),
                rollback_path=str(backup),
            )
            self.ledger.append_modification_attempt(attempt)
            return attempt

        temporary = target.with_suffix(target.suffix + ".artificer.tmp")
        temporary.write_text(new_content, encoding="utf-8")
        os.replace(temporary, target)
        shutil.rmtree(workspace, ignore_errors=True)
        attempt = ModificationAttempt(
            attempt_id=attempt_id,
            proposal_id=proposal_id,
            path=relative_path,
            rule_id=rule_id,
            authority_level=decision.authority.value,
            original_sha256=original_hash,
            proposed_sha256=proposed_hash,
            diff_text="\n".join(diff_lines),
            status="applied_restart_required" if target.suffix.lower() == ".py" else "applied",
            validation_summary="All required validation checks passed",
            rollback_path=str(backup),
        )
        self.ledger.append_modification_attempt(attempt)
        return attempt

    def rollback_attempt(self, attempt: ModificationAttempt) -> None:
        if not attempt.rollback_path:
            raise ForgeError("No rollback asset is associated with this attempt")
        target = self.source_root / attempt.path
        self.rollback.restore(attempt.rollback_path, target)
