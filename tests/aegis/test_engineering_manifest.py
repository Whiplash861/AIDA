from __future__ import annotations

from aida.aegis.engineering_manifest import build_engineering_manifest
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.learning.store import AegisLearningStore


def test_manifest_exposes_reusable_learning_patterns_without_security_evidence(tmp_path) -> None:
    learning = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    manifest = build_engineering_manifest(learning)

    assert manifest["engine"] == "aegis"
    assert manifest["cross_engine_review"]["owner"] == "artificer"
    assert "deterministic_plus_learned_reasoning" in manifest["architecture_patterns"]
    assert "shadow_model_ready_architecture" in manifest["architecture_patterns"]
    assert "remote_intrusion_correlation" in manifest["architecture_patterns"]
    assert "authorized_support_disambiguation" in manifest["architecture_patterns"]
    assert "exact_identity_active_containment" in manifest["architecture_patterns"]
    assert manifest["authority_contract"]["learning_grants_execution_authority"] is False
    assert manifest["authority_contract"]["sentry_requires_local_user_attacker_confirmation"] is True
    assert manifest["authority_contract"]["sentry_requires_fresh_exact_confirmation"] is True
    assert manifest["authority_contract"]["sentry_network_isolation_enabled"] is False
    assert manifest["privacy_contract"]["raw_paths"] is False
    assert manifest["privacy_contract"]["network_endpoints"] is False
    assert manifest["privacy_contract"]["support_vendor_labels"] is False
    assert len(manifest["learning_capabilities"]) >= 3
