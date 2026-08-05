from __future__ import annotations

from aida.artificer.codewright import Codewright


def test_codewright_detects_syntax_error_and_empty_module(tmp_path) -> None:
    package = tmp_path / "aida"
    package.mkdir()
    (package / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (package / "placeholder.py").write_text("", encoding="utf-8")
    findings = Codewright(tmp_path).inspect()
    titles = {finding.title for finding in findings}
    assert "Python syntax failure" in titles
    assert "Empty implementation module" in titles
