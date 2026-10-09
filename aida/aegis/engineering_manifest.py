from __future__ import annotations

from typing import Any

from aida.aegis.learning.service import AegisLearningService


MANIFEST_VERSION = "1.1"


def build_engineering_manifest(
    learning: AegisLearningService,
) -> dict[str, Any]:
    """Return privacy-safe architecture metadata for engineering review.

    The manifest intentionally describes reusable engineering patterns rather
    than security evidence. Artificer can inspect this contract and Aegis source
    to decide whether another Engine may benefit from similar architecture.
    """

    model = learning.snapshot()
    return {
        "engine": "aegis",
        "domain": "security",
        "manifest_version": MANIFEST_VERSION,
        "architecture_patterns": (
            "deterministic_plus_learned_reasoning",
            "evidence_graph",
            "competing_hypotheses",
            "multi_axis_risk_and_coverage",
            "adaptive_scan_orchestration",
            "privacy_preserving_feature_learning",
            "poisoning_resistant_training_gate",
            "versioned_feature_schema",
            "versioned_model_lifecycle",
            "remote_intrusion_correlation",
            "authorized_support_disambiguation",
            "exact_identity_active_containment",
            "fresh_scope_bound_confirmation",
            "post_containment_verification",
            "shadow_model_ready_architecture",
            "rollback_ready_model_contract",
        ),
        "learning_capabilities": tuple(
            capability.to_record() for capability in learning.capabilities
        ),
        "model": model.to_record(),
        "cross_engine_review": {
            "recommended": True,
            "owner": "artificer",
            "instruction": (
                "Compare reusable engineering patterns against other Engines and "
                "recommend adoption only where the target domain benefits."
            ),
        },
        "privacy_contract": {
            "raw_paths": False,
            "hashes": False,
            "network_endpoints": False,
            "command_lines": False,
            "support_vendor_labels": False,
            "security_case_contents": False,
            "user_conversation": False,
        },
        "authority_contract": {
            "learning_grants_execution_authority": False,
            "learned_inference_overrides_provider_evidence": False,
            "learned_inference_overrides_policy": False,
            "remote_support_authorization_is_security_whitelist": False,
            "sentry_requires_local_user_attacker_confirmation": True,
            "sentry_requires_fresh_exact_confirmation": True,
            "sentry_network_isolation_enabled": False,
            "sentry_file_deletion_enabled": False,
        },
    }


def bridge_metadata(learning: AegisLearningService) -> dict[str, Any]:
    snapshot = learning.snapshot()
    return {
        "engineering_manifest_version": MANIFEST_VERSION,
        "learning_capability_count": len(learning.capabilities),
        "learning_model_version": snapshot.model_version,
        "learning_feature_schema_version": snapshot.feature_schema_version,
        "learning_model_stage": snapshot.stage.value,
        "learning_sample_count": snapshot.sample_count,
        "learning_ready": snapshot.ready,
        "shadow_supported": snapshot.shadow_supported,
        "rollback_supported": snapshot.rollback_supported,
    }
