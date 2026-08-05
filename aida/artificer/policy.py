from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aida.artificer.models import AuthorityLevel


@dataclass(frozen=True, slots=True)
class MaintenanceRule:
    rule_id: str
    description: str
    authority: AuthorityLevel
    allowed_extensions: tuple[str, ...]
    allowed_roots: tuple[str, ...]
    requires_ast_equivalence: bool = False
    requires_owner_approval: bool = False
    maximum_changed_lines: int = 20


DEFAULT_PROTECTED_PATHS = (
    "aida/artificer/policy.py",
    "aida/artificer/warden.py",
    "aida/artificer/developer_registry.py",
    "aida/artificer/consent.py",
    "aida/artificer/sanitizer.py",
    "aida/artificer/ledger.py",
    "aida/artificer/ledger_core.py",
    "aida/artificer/ledger_schema.py",
    "aida/artificer/ledger_events.py",
    "aida/artificer/ledger_findings.py",
    "aida/artificer/ledger_operations.py",
    "aida/artificer/ledger_records.py",
    "aida/artificer/manifests/protected_paths.json",
    ".env",
)

DEFAULT_RULES = {
    "python.format_only": MaintenanceRule(
        rule_id="python.format_only",
        description="Nonfunctional Python whitespace or formatting correction.",
        authority=AuthorityLevel.BOUNDED_MAINTENANCE,
        allowed_extensions=(".py",),
        allowed_roots=("aida/",),
        requires_ast_equivalence=True,
        maximum_changed_lines=30,
    ),
    "python.syntax_repair": MaintenanceRule(
        rule_id="python.syntax_repair",
        description="Minor Python syntax repair proven by compilation and tests.",
        authority=AuthorityLevel.OWNER_APPROVAL,
        allowed_extensions=(".py",),
        allowed_roots=("aida/",),
        requires_owner_approval=True,
        maximum_changed_lines=12,
    ),
    "data.timezone_refresh": MaintenanceRule(
        rule_id="data.timezone_refresh",
        description="Refresh approved timezone or locale data.",
        authority=AuthorityLevel.BOUNDED_MAINTENANCE,
        allowed_extensions=(".json", ".csv"),
        allowed_roots=("aida/data/timezones/",),
        maximum_changed_lines=100000,
    ),
    "data.geofence_refresh": MaintenanceRule(
        rule_id="data.geofence_refresh",
        description="Refresh approved geofencing boundary data without changing policy.",
        authority=AuthorityLevel.BOUNDED_MAINTENANCE,
        allowed_extensions=(".json", ".geojson", ".csv"),
        allowed_roots=("aida/data/geofencing/",),
        maximum_changed_lines=100000,
    ),
    "generated.index_refresh": MaintenanceRule(
        rule_id="generated.index_refresh",
        description="Rebuild approved generated indexes and manifests.",
        authority=AuthorityLevel.BOUNDED_MAINTENANCE,
        allowed_extensions=(".json", ".jsonl", ".txt"),
        allowed_roots=("memory/generated/", "aida/generated/"),
        maximum_changed_lines=100000,
    ),
}


class ArtificerPolicy:
    def __init__(
        self,
        source_root: str | Path,
        *,
        protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS,
        rules: dict[str, MaintenanceRule] | None = None,
    ) -> None:
        self.source_root = Path(source_root).resolve()
        self.protected_paths = tuple(self._normalize(path) for path in protected_paths)
        self.rules = dict(rules or DEFAULT_RULES)

    def _normalize(self, path: str | Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(self.source_root)
            except ValueError:
                return str(candidate.resolve()).replace("\\", "/").lower()
        return str(candidate).replace("\\", "/").lstrip("./").lower()

    def is_protected(self, path: str | Path) -> bool:
        normalized = self._normalize(path)
        for protected in self.protected_paths:
            if normalized == protected or normalized.startswith(protected.rstrip("/") + "/"):
                return True
        return False

    def get_rule(self, rule_id: str) -> MaintenanceRule | None:
        return self.rules.get(rule_id)

    def is_path_allowed(self, path: str | Path, rule: MaintenanceRule) -> bool:
        normalized = self._normalize(path)
        suffix = Path(normalized).suffix.lower()
        if suffix not in rule.allowed_extensions:
            return False
        return any(normalized.startswith(root.lower()) for root in rule.allowed_roots)
