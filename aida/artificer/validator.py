from __future__ import annotations

import ast
import json
import csv
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    passed: bool
    checks: tuple[ValidationCheck, ...]


class Validator:
    def validate_python_file(
        self,
        path: str | Path,
        *,
        original_source: str | None = None,
        require_ast_equivalence: bool = False,
    ) -> ValidationReport:
        candidate = Path(path)
        checks: list[ValidationCheck] = []
        try:
            source = candidate.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(candidate))
            checks.append(ValidationCheck("ast_parse", True, "Python AST parsed successfully"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            checks.append(ValidationCheck("ast_parse", False, str(exc)))
            return ValidationReport(False, tuple(checks))

        if require_ast_equivalence:
            if original_source is None:
                checks.append(ValidationCheck("ast_equivalence", False, "Original source is required"))
            else:
                try:
                    original_tree = ast.parse(original_source)
                    equivalent = ast.dump(original_tree, include_attributes=False) == ast.dump(
                        tree, include_attributes=False
                    )
                    checks.append(
                        ValidationCheck(
                            "ast_equivalence",
                            equivalent,
                            "ASTs are equivalent" if equivalent else "Patch changes Python behavior",
                        )
                    )
                except SyntaxError as exc:
                    checks.append(ValidationCheck("ast_equivalence", False, str(exc)))

        try:
            compile(source, str(candidate), "exec")
            compiled = True
        except (SyntaxError, ValueError):
            compiled = False
        checks.append(
            ValidationCheck(
                "compile",
                bool(compiled),
                "Bytecode compilation succeeded" if compiled else "Bytecode compilation failed",
            )
        )
        return ValidationReport(all(check.passed for check in checks), tuple(checks))

    def validate_data_file(self, path: Path) -> ValidationReport:
        try:
            source = path.read_text(encoding="utf-8")
            if not source.strip():
                raise ValueError("Empty dataset")
            if path.suffix.lower() in {".json", ".geojson"}:
                payload = json.loads(source, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                if not isinstance(payload, (dict, list)):
                    raise ValueError("Dataset must be an object or array")
                if path.suffix.lower() == ".geojson" and (not isinstance(payload, dict) or payload.get("type") not in {"FeatureCollection", "Feature", "GeometryCollection", "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}):
                    raise ValueError("Unrecognized GeoJSON type")
            elif path.suffix.lower() == ".jsonl":
                for line in source.splitlines():
                    json.loads(line)
            elif path.suffix.lower() == ".csv":
                rows = list(csv.reader(io.StringIO(source)))
                if not rows or any(len(row) != len(rows[0]) for row in rows):
                    raise ValueError("CSV rows must have consistent columns")
            else:
                raise ValueError("No schema validator is registered for this dataset type")
        except (OSError, ValueError, csv.Error) as exc:
            return ValidationReport(False, (ValidationCheck("data_schema", False, str(exc)),))
        return ValidationReport(True, (ValidationCheck("data_schema", True, "Structured data parsed; rule-specific tests remain required"),))

    def run_tests(
        self, source_root: str | Path, *, test_paths: tuple[str, ...] = ()
    ) -> ValidationCheck:
        command = [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q"]
        command.extend(test_paths)
        try:
            result = subprocess.run(
                command,
                cwd=Path(source_root),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ValidationCheck("pytest", False, str(exc))
        detail = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        return ValidationCheck("pytest", result.returncode == 0, detail)
