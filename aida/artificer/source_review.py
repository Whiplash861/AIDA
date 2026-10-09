"""Exact local source annotations and inert, user-requested candidate exports."""
from __future__ import annotations

import ast
import difflib
import hashlib
import os
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from aida.artificer.models import SourceReviewAnnotation, utc_now
from aida.artificer.state_file import locked_state, write_json
from aida.artificer.validator import Validator

MAX_SOURCE_BYTES = 1024 * 1024
MAX_REPLACEMENT_BYTES = 128 * 1024


class StaleSourceReview(ValueError):
    """The reviewed file or finding no longer represents current source."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_lines(raw: bytes) -> list[str]:
    return raw.decode("utf-8-sig").splitlines(keepends=True)


def _symbol(tree, line: int) -> str:
    scopes = [(node.end_lineno - node.lineno, node.name) for node in ast.walk(tree)
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
              and node.lineno <= line <= node.end_lineno]
    return min(scopes)[1] if scopes else "module"


def annotations_for_finding(finding, captures: dict[str, bytes]) -> tuple[SourceReviewAnnotation, ...]:
    """Derive anchors from the same bytes Codewright inspected, never a reread."""
    output = []
    for relative in finding.affected_components:
        raw = captures.get(relative)
        if raw is None:
            continue
        lines = _source_lines(raw)
        source = "".join(lines)
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            tree = None
            error_line = exc.lineno or 1
        prefix = finding.fingerprint.split(":", 1)[0]
        nodes = []
        if tree is not None:
            if prefix == "duplicates":
                from aida.artificer.codewright import Codewright
                names = Codewright._duplicate_top_level_names(tree)
                nodes = [node for node in tree.body if getattr(node, "name", None) in names]
            elif prefix == "bare-except":
                nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.type is None]
            elif prefix == "platform-leak":
                from aida.artificer.codewright import Codewright
                nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.Call, ast.Attribute))
                         and Codewright._windows_execution_evidence(ast.Module(body=[node], type_ignores=[]))]
            elif prefix == "metadata":
                nodes = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                         and any(isinstance(child, ast.Name) and child.id in {"VERSION", "__version__"} for child in ast.walk(node))]
        anchors = [(node.lineno, min(node.end_lineno or node.lineno, node.lineno + 199)) for node in nodes]
        if not anchors:
            start = error_line if tree is None else 1
            anchors = [(max(1, start), min(max(1, len(lines)), start + 2 if tree is None else start))]
        for start, end in sorted(set(anchors))[:12]:
            end = max(start, end)
            excerpt = "".join(lines[start - 1:end])
            if len(excerpt.encode("utf-8")) > 32768:
                end = start
                excerpt = lines[start - 1] if lines else ""
                if len(excerpt.encode("utf-8")) > 32768:
                    # Never truncate an editable span midway through a line.
                    # The finding remains visible without an unsafe anchor.
                    continue
            symbol = _symbol(tree, start) if tree is not None else "module (syntax unavailable)"
            outcomes = {
                "syntax": ("The file parses and compiles; runtime behavior still requires regression tests.",),
                "duplicates": ("One explicit implementation owns the reviewed symbol; shadowed definitions no longer hide behavior.",),
                "bare-except": ("Expected failures are observable and cancellation/system-exit exceptions are not silently suppressed.",),
                "platform-leak": ("Platform behavior has an explicit adapter boundary and a testable unsupported-platform outcome.",),
                "empty": ("The module's intended behavior or deliberate placeholder status is explicit and verified.",),
                "metadata": ("The reviewed declaration agrees with the chosen authoritative version source.",),
            }.get(prefix, finding.expected_outcomes)
            validation = (
                f"Re-run Codewright's {prefix} check against the candidate.",
                f"Add or select a regression test covering {relative}:{start} ({symbol}).",
                "Check affected public interfaces and unsupported-platform behavior where applicable.",
                "Static validation alone does not prove correctness; execution tests and owner review remain required.",
            )
            identity = f"{finding.finding_id}|{relative}|{start}|{end}|{digest(raw)}|{finding.recommended_change}"
            output.append(SourceReviewAnnotation(
                review_id="AE-REVIEW-" + digest(identity.encode())[:20].upper(),
                finding_id=finding.finding_id, path=relative, start_line=start, end_line=end,
                symbol=symbol, source_sha256=digest(raw), span_sha256=digest(excerpt.encode("utf-8")),
                reviewed_code=excerpt,
                proposed_change=f"At {symbol}, lines {start}-{end}: {finding.recommended_change}",
                rationale=f"{finding.finding} {finding.reasoning_summary}", evidence=finding.evidence_summary,
                expected_outcomes=tuple(outcomes), validation_requirements=validation,
                change_kind="add_or_document" if prefix == "empty" else "modify",
            ))
    return tuple(output)


def render_annotation(annotation: SourceReviewAnnotation, *, state: str = "not_rechecked") -> str:
    code = "\n".join(f"{annotation.start_line + index:>5}: {line}" for index, line in enumerate(annotation.reviewed_code.splitlines())) or "(empty code span)"
    return "\n".join((
        f"SOURCE REVIEW {annotation.review_id}", f"Finding: {annotation.finding_id}",
        f"Reviewed code: {annotation.path}:{annotation.start_line}-{annotation.end_line}",
        f"Symbol: {annotation.symbol}", f"Source state: {state}", f"Source SHA-256: {annotation.source_sha256}",
        f"Span SHA-256: {annotation.span_sha256}", "", "CAPTURED CODE", code, "",
        "PROPOSED ADDITION OR CHANGE", annotation.proposed_change, "", "RATIONALE", annotation.rationale,
        "", "OBSERVED EVIDENCE", annotation.evidence, "", "EXPECTED OUTCOMES (not yet verified)",
        *["- " + value for value in annotation.expected_outcomes], "", "REQUIRED VALIDATION",
        *["- " + value for value in annotation.validation_requirements], "",
        "This annotation is a review record. It has not changed the source file.",
    ))


class SourceReviewService:
    def __init__(self, source_root: Path, ledger, *, policy=None, validator=None):
        self.source_root = Path(source_root).resolve()
        self.ledger = ledger
        self.policy = policy
        self.validator = validator or Validator()

    def _target(self, relative: str) -> Path:
        lexical = Path(relative)
        if lexical.is_absolute() or ".." in lexical.parts or lexical.suffix.lower() != ".py":
            raise ValueError("Source review requires a relative Python source path")
        target = (self.source_root / lexical).resolve()
        try:
            target.relative_to(self.source_root)
        except ValueError as exc:
            raise ValueError("Source review target escaped its source root") from exc
        if not target.is_file():
            raise FileNotFoundError(relative)
        return target

    def _read(self, annotation):
        target = self._target(annotation.path)
        with target.open("rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the bounded review size")
        if digest(raw) != annotation.source_sha256:
            raise StaleSourceReview("Source changed after review; run a fresh review before staging")
        span = "".join(_source_lines(raw)[annotation.start_line - 1:annotation.end_line])
        if digest(span.encode("utf-8")) != annotation.span_sha256:
            raise StaleSourceReview("Captured source span no longer matches its review")
        return raw

    def get(self, review_id: str) -> SourceReviewAnnotation:
        annotation = self.ledger.get_source_review(review_id)
        if annotation is None:
            raise KeyError(review_id)
        return annotation

    def inspect(self, review_id: str) -> dict:
        annotation = self.get(review_id)
        finding = self.ledger.get_finding(annotation.finding_id)
        state = "current"
        try:
            self._read(annotation)
        except StaleSourceReview:
            state = "stale_source"
        except (OSError, ValueError, UnicodeError):
            state = "source_unavailable"
        if state == "current" and (finding is None or finding.status != "open"):
            state = "finding_not_open"
        return {"annotation": annotation, "state": state, "text": render_annotation(annotation, state=state)}

    def export_review(self, review_id: str, export_dir: str | Path) -> Path:
        result = self.inspect(review_id)
        target_dir = Path(export_dir).expanduser().resolve()
        if not target_dir.is_dir():
            raise ValueError("Choose an existing local export directory")
        target = target_dir / f"{review_id}-{uuid.uuid4().hex[:8]}.review.json"
        write_json(target, {"artifact_type": "source_review", "schema_version": 1,
                            "state_at_export": result["state"], "annotation": result["annotation"].to_record(),
                            "source_modified": False, "execution_authority": False})
        return target

    def stage(self, review_id: str, replacement_text: str, *, expected_source_sha256: str, export_dir: str | Path) -> dict:
        annotation = self.get(review_id)
        if expected_source_sha256 != annotation.source_sha256:
            raise StaleSourceReview("The displayed review differs from this staging request")
        finding = self.ledger.get_finding(annotation.finding_id)
        if finding is None or finding.status != "open":
            raise StaleSourceReview("This finding is no longer open; run a fresh review")
        if not isinstance(replacement_text, str) or len(replacement_text.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
            raise ValueError("Candidate replacement exceeds the 128 KiB limit")
        export_root = Path(export_dir).expanduser().resolve()
        if not export_root.is_dir():
            raise ValueError("Choose an existing local export directory")
        # Lock staging requests across instances; source can still be edited by
        # an editor, so its complete identity is rechecked before publication.
        with locked_state(self.ledger.path.with_suffix(".staging")):
            original = self._read(annotation)
            lines = _source_lines(original)
            newline = "\r\n" if b"\r\n" in original else "\n"
            replacement = replacement_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
            if annotation.end_line < len(lines) and replacement and not replacement.endswith(newline):
                replacement += newline
            proposed = "".join(lines[:annotation.start_line - 1]) + replacement + "".join(lines[annotation.end_line:])
            candidate_bytes = proposed.encode("utf-8")
            if original.startswith(b"\xef\xbb\xbf"):
                candidate_bytes = b"\xef\xbb\xbf" + candidate_bytes
            if len(candidate_bytes) > MAX_SOURCE_BYTES:
                raise ValueError("Candidate exceeds the 1 MiB source limit")
            if candidate_bytes == original:
                raise ValueError("Candidate is unchanged; edit the reviewed code span before staging")
            stage_id = "AE-STAGE-" + uuid.uuid4().hex[:16].upper()
            destination = export_root / stage_id
            diff = "\n".join(difflib.unified_diff(
                original.decode("utf-8-sig").splitlines(), proposed.splitlines(),
                fromfile="a/" + annotation.path, tofile="b/" + annotation.path, lineterm=""))
            with tempfile.TemporaryDirectory(prefix=".aida-stage-", dir=export_root) as staging_dir:
                folder = Path(staging_dir) / stage_id
                folder.mkdir()
                # Inert file extension; no imports, source execution or test runner.
                candidate = folder / "candidate.py.txt"
                candidate.write_bytes(candidate_bytes)
                report = self.validator.validate_python_file(candidate)
                manifest = {
                    "schema_version": 1, "artifact_type": "source_candidate", "stage_id": stage_id,
                    "review_id": review_id, "finding_id": annotation.finding_id,
                    "created_at_utc": utc_now().isoformat(), "source_path": annotation.path,
                    "source_sha256": annotation.source_sha256, "candidate_sha256": digest(candidate_bytes),
                    "replacement_span": {"start_line": annotation.start_line, "end_line": annotation.end_line},
                    "status": "static_checks_passed" if report.passed else "static_checks_failed",
                    "validation": [asdict(check) for check in report.checks],
                    "required_validation": list(annotation.validation_requirements),
                    "protected_source": bool(self.policy and self.policy.is_protected(annotation.path)),
                    "source_modified": False, "execution_authority": False, "behavior_verified": False, "publication": "ready",
                    "candidate_file": "candidate.py.txt", "diff_file": "candidate.diff",
                    "manifest_path": str(destination / "manifest.json"),
                }
                (folder / "candidate.diff").write_text(diff, encoding="utf-8")
                write_json(folder / "annotation.json", annotation.to_record())
                write_json(folder / "manifest.json", manifest)
                self._read(annotation)  # Catch source changes during validation.
                current_finding = self.ledger.get_finding(annotation.finding_id)
                if current_finding is None or current_finding.status != "open":
                    raise StaleSourceReview("The finding closed during staging; review it again")
                self.ledger.record_source_stage({**manifest, "publication": "prepared"})
                os.replace(folder, destination)
                self.ledger.record_source_stage(manifest)
            return manifest
