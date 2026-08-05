from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from aida.artificer.models import ArtificerFinding, AuthorityLevel, utc_now

_VERSION_PATTERN = re.compile(r"(?m)^(?:VERSION|__version__)\s*=\s*['\"]([^'\"]+)['\"]")
_WINDOWS_EXECUTION_TOKENS = (
    "powershell",
    "pwsh",
    "explorer",
    "ms-settings:",
)
_WINDOWS_EXECUTION_CALLS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
    "os.startfile",
}
_WINDOWS_ATTRIBUTES = {
    "subprocess.CREATE_NO_WINDOW",
    "ctypes.windll",
}


class Codewright:
    """Deterministic source inspection limited to AIDA's configured source root."""

    MANAGED_FINGERPRINT_PREFIXES = (
        "unreadable:",
        "empty:",
        "syntax:",
        "duplicates:",
        "bare-except:",
        "platform-leak:",
        "metadata:version-drift:",
    )

    def __init__(
        self,
        source_root: str | Path,
        *,
        expectations_path: str | Path | None = None,
    ) -> None:
        self.source_root = Path(source_root).resolve()
        default_expectations = (
            Path(__file__).resolve().parent
            / "manifests"
            / "source_expectations.json"
        )
        self.expectations_path = Path(
            expectations_path or default_expectations
        ).resolve()
        expectations = self._load_expectations()
        self.approved_platform_roots = tuple(
            self._normalize_prefix(value)
            for value in expectations.get("approved_platform_roots", ())
            if str(value).strip()
        )
        intentional = expectations.get("intentional_empty_modules", {})
        if isinstance(intentional, dict):
            self.intentional_empty_modules = frozenset(
                self._normalize_relative(value) for value in intentional
            )
        else:
            self.intentional_empty_modules = frozenset(
                self._normalize_relative(value) for value in intentional
            )

    def inspect(self) -> list[ArtificerFinding]:
        findings: list[ArtificerFinding] = []
        python_files = self._python_files()
        versions: dict[str, str] = {}

        for path in python_files:
            relative = self._relative(path)
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                findings.append(
                    self._finding(
                        category="source_health",
                        title="Source file could not be read",
                        severity="high",
                        affected=(relative,),
                        finding=f"Codewright could not read {relative}.",
                        evidence=str(exc),
                        recommendation="Restore readable source or correct file encoding.",
                        risk=0.10,
                        fingerprint=f"unreadable:{relative}",
                    )
                )
                continue

            if not source.strip() and path.name != "__init__.py":
                if relative in self.intentional_empty_modules:
                    continue
                findings.append(
                    self._finding(
                        category="source_health",
                        title="Empty implementation module",
                        severity="minor",
                        affected=(relative,),
                        finding=f"{relative} contains no implementation.",
                        evidence=(
                            "The file size is zero or contains only whitespace, "
                            "and the path is not declared as an intentional placeholder."
                        ),
                        recommendation=(
                            "Implement the module, remove it, or document it in the "
                            "Artificer source-expectations manifest."
                        ),
                        risk=0.15,
                        fingerprint=f"empty:{relative}",
                    )
                )
                continue

            try:
                tree = ast.parse(source, filename=relative)
            except SyntaxError as exc:
                findings.append(
                    self._finding(
                        category="source_health",
                        title="Python syntax failure",
                        severity="critical",
                        affected=(relative,),
                        finding=f"{relative} cannot be parsed by Python.",
                        evidence=f"Line {exc.lineno}: {exc.msg}",
                        recommendation=(
                            "Prepare a minimal syntax repair in the Forge and "
                            "require validation."
                        ),
                        risk=0.20,
                        authority=AuthorityLevel.OWNER_APPROVAL.value,
                        fingerprint=f"syntax:{relative}:{exc.lineno}:{exc.msg}",
                    )
                )
                continue

            duplicate_names = self._duplicate_top_level_names(tree)
            if duplicate_names:
                findings.append(
                    self._finding(
                        category="maintainability",
                        title="Duplicate top-level definitions",
                        severity="moderate",
                        affected=(relative,),
                        finding=(
                            f"{relative} defines the same top-level name more than once."
                        ),
                        evidence=", ".join(sorted(duplicate_names)),
                        recommendation=(
                            "Consolidate definitions to remove shadowed behavior."
                        ),
                        risk=0.35,
                        fingerprint=(
                            f"duplicates:{relative}:"
                            f"{','.join(sorted(duplicate_names))}"
                        ),
                    )
                )

            broad_excepts = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.ExceptHandler) and node.type is None
            )
            if broad_excepts >= 3:
                findings.append(
                    self._finding(
                        category="observability",
                        title="Broad exception suppression",
                        severity="moderate",
                        affected=(relative,),
                        finding=(
                            f"{relative} contains {broad_excepts} bare exception handlers."
                        ),
                        evidence=(
                            "Bare handlers can conceal operational failures from "
                            "the Artificer."
                        ),
                        recommendation=(
                            "Catch specific exceptions and emit structured failure events."
                        ),
                        risk=0.30,
                        fingerprint=f"bare-except:{relative}:{broad_excepts}",
                    )
                )

            platform_evidence = self._windows_execution_evidence(tree)
            if (
                platform_evidence
                and not self._is_approved_platform_scope(relative)
                and relative != "aida/artificer/codewright.py"
            ):
                findings.append(
                    self._finding(
                        category="platform_compatibility",
                        title="Executable platform behavior outside adapter",
                        severity="moderate",
                        affected=(relative,),
                        finding=(
                            f"{relative} directly executes Windows-specific behavior "
                            "outside an approved platform scope."
                        ),
                        evidence="; ".join(platform_evidence),
                        recommendation=(
                            "Move the executable operating-system operation behind "
                            "the platform adapter interface, or explicitly approve "
                            "the containing platform-scoped package."
                        ),
                        risk=0.40,
                        fingerprint=f"platform-leak:{relative}",
                    )
                )

            version_match = _VERSION_PATTERN.search(source)
            if version_match:
                versions[relative] = version_match.group(1)

        if len(set(versions.values())) > 1:
            evidence = "; ".join(
                f"{path}={version}" for path, version in sorted(versions.items())
            )
            findings.append(
                self._finding(
                    category="metadata_drift",
                    title="AIDA version metadata drift",
                    severity="moderate",
                    affected=tuple(sorted(versions)),
                    finding=(
                        "Multiple AIDA version values are declared across the source tree."
                    ),
                    evidence=evidence,
                    recommendation=(
                        "Use one authoritative version source and import it everywhere else."
                    ),
                    risk=0.20,
                    fingerprint=(
                        "metadata:version-drift:"
                        + hashlib.sha256(evidence.encode()).hexdigest()[:16]
                    ),
                )
            )

        return findings

    def _load_expectations(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.expectations_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _python_files(self) -> list[Path]:
        ignored = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "logs",
            "memory",
        }
        paths: list[Path] = []
        for path in self.source_root.rglob("*.py"):
            if ignored.intersection(part.lower() for part in path.parts):
                continue
            paths.append(path)
        return sorted(paths)

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.source_root)).replace("\\", "/")

    def _is_approved_platform_scope(self, relative: str) -> bool:
        normalized = self._normalize_relative(relative)
        return any(
            normalized.startswith(prefix)
            for prefix in self.approved_platform_roots
        )

    @classmethod
    def _windows_execution_evidence(cls, tree: ast.Module) -> tuple[str, ...]:
        evidence: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = cls._qualified_name(node.func)
                if call_name not in _WINDOWS_EXECUTION_CALLS:
                    continue
                if call_name == "os.startfile":
                    evidence.add("os.startfile executes through the host shell")
                strings: list[str] = []
                for argument in node.args:
                    strings.extend(cls._literal_strings(argument))
                for keyword in node.keywords:
                    strings.extend(cls._literal_strings(keyword.value))
                lowered = " ".join(strings).lower()
                matched = sorted(
                    token
                    for token in _WINDOWS_EXECUTION_TOKENS
                    if token in lowered
                )
                if matched:
                    evidence.add(
                        f"{call_name} executes Windows token(s): "
                        + ", ".join(matched)
                    )
            elif isinstance(node, ast.Attribute):
                attribute = cls._qualified_name(node)
                if attribute in _WINDOWS_ATTRIBUTES:
                    evidence.add(f"Uses Windows-only attribute {attribute}")
        return tuple(sorted(evidence))

    @staticmethod
    def _qualified_name(node: ast.AST) -> str:
        parts: list[str] = []
        current: ast.AST | None = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    @classmethod
    def _literal_strings(cls, node: ast.AST) -> list[str]:
        return [
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ]

    @staticmethod
    def _normalize_relative(value: object) -> str:
        return str(value).strip().replace("\\", "/").lstrip("./")

    @classmethod
    def _normalize_prefix(cls, value: object) -> str:
        normalized = cls._normalize_relative(value)
        return normalized if normalized.endswith("/") else normalized + "/"

    @staticmethod
    def _duplicate_top_level_names(tree: ast.Module) -> set[str]:
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        counts = Counter(names)
        return {name for name, count in counts.items() if count > 1}

    @staticmethod
    def _finding(
        *,
        category: str,
        title: str,
        severity: str,
        affected: tuple[str, ...],
        finding: str,
        evidence: str,
        recommendation: str,
        risk: float,
        fingerprint: str,
        authority: str = AuthorityLevel.RECOMMEND.value,
    ) -> ArtificerFinding:
        now = utc_now()
        return ArtificerFinding(
            finding_id=f"AE-CODE-{uuid.uuid4().hex[:10].upper()}",
            category=category,
            title=title,
            severity=severity,
            confidence=0.98,
            evidence_quality=0.96,
            affected_components=affected,
            first_seen_utc=now,
            last_seen_utc=now,
            observation_count=1,
            finding=finding,
            evidence_summary=evidence,
            reasoning_summary=(
                "The conclusion is derived from deterministic AST analysis and "
                "source inspection. String presence alone is not treated as "
                "executable platform coupling."
            ),
            recommended_change=recommendation,
            expected_outcomes=(
                "Reduced hidden failure risk",
                "Improved maintainability and compatibility",
            ),
            implementation_risk=risk,
            regression_risk=min(0.8, risk + 0.1),
            authority_required=authority,
            fingerprint=fingerprint,
        )
