from __future__ import annotations

from aida.artificer.forge import Forge
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.rollback import RollbackManager
from aida.artificer.validator import Validator
from aida.artificer.warden import Warden


def test_forge_applies_ast_equivalent_formatting_change(tmp_path) -> None:
    source_root = tmp_path / "source"
    target = source_root / "aida" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("value=1\n", encoding="utf-8")
    ledger = ArtificerLedger(tmp_path / "ledger.db")
    policy = ArtificerPolicy(source_root)
    forge = Forge(
        source_root=source_root,
        ledger=ledger,
        policy=policy,
        warden=Warden(policy),
        validator=Validator(),
        rollback=RollbackManager(tmp_path / "rollback"),
    )
    attempt = forge.apply_text_replacement(
        relative_path="aida/example.py",
        new_content="value = 1\n",
        rule_id="python.format_only",
        confidence=0.99,
        evidence_quality=0.99,
        implementation_risk=0.05,
    )
    assert attempt.status == "applied_restart_required"
    assert target.read_text(encoding="utf-8") == "value = 1\n"
