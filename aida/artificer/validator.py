from __future__ import annotations

import ast
import compileall
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
            source = candidate.read_text(encoding="utf-8")
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

        compiled = compileall.compile_file(str(candidate), quiet=1, force=True)
        checks.append(
            ValidationCheck(
                "compile",
                bool(compiled),
                "Bytecode compilation succeeded" if compiled else "Bytecode compilation failed",
            )
        )
        return ValidationReport(all(check.passed for check in checks), tuple(checks))

    def run_tests(
        self, source_root: str | Path, *, test_paths: tuple[str, ...] = ()
    ) -> ValidationCheck:
        command = [sys.executable, "-m", "pytest", "-q"]
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
