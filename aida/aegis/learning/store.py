from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from aida.aegis.learning.models import AEGIS_FEATURE_SCHEMA_VERSION, AegisFeatureVector
from aida.aegis.learning.online_model import OnlineAnomalyModel
from aida.artificer.state_file import locked_state, write_json
from aida.memory.privacy import sanitize_text


class LearningStoreError(RuntimeError):
    """Existing model state is unavailable; never silently replace its baseline."""


class LearningConflictError(LearningStoreError):
    pass


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _validate_record(record):
    if not isinstance(record, dict) or record.get("feature_schema_version") != AEGIS_FEATURE_SCHEMA_VERSION:
        raise LearningStoreError("Incompatible or invalid learning feature schema; retained state needs explicit migration")
    for field in ("model_version", "minimum_samples", "sample_count", "max_identity_keys"):
        value = record.get(field, 12000 if field == "max_identity_keys" else None)
        if not isinstance(value, int) or isinstance(value, bool) or value < (0 if field == "sample_count" else 1):
            raise LearningStoreError(f"Invalid persisted {field}")
    if not isinstance(record.get("model_id"), str) or not record["model_id"]:
        raise LearningStoreError("Missing persisted model identity")
    for field in ("last_anomaly_score", "last_confidence"):
        value = record.get(field, 0)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise LearningStoreError(f"Invalid persisted {field}")
    stats = record.get("numeric_stats", {})
    identities = record.get("identity_counts", {})
    if not isinstance(stats, dict) or not isinstance(identities, dict) or len(stats) > 256 or len(identities) > 12000:
        raise LearningStoreError("Invalid or oversized persisted feature state")
    for key, stat in stats.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) or not isinstance(stat, dict):
            raise LearningStoreError("Invalid numeric feature")
        count = stat.get("count")
        if not isinstance(count, int) or not 0 <= count <= record["sample_count"]:
            raise LearningStoreError("Invalid numeric sample count")
        if any(not isinstance(stat.get(name), (int, float)) or not math.isfinite(stat[name]) for name in ("mean", "m2")) or stat["m2"] < 0:
            raise LearningStoreError("Invalid numeric aggregate")
    for key, count in identities.items():
        if not re.fullmatch(r"[a-z_]{1,48}:[0-9a-f]{64}", key) or not isinstance(count, int) or count < 0:
            raise LearningStoreError("Learning identities must be bounded hashed tokens with nonnegative counts")
    return OnlineAnomalyModel.from_record(record)


class AegisLearningStore:
    """Versioned local snapshots, atomic updates, explicit rollback and recovery.

    Digests detect accidental/tampered content; they are not signatures against
    a party able to rewrite the entire local store. Raw evidence is not retained.
    """

    def __init__(self, path: str | Path, *, history_limit: int = 16) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_path = self.path.with_suffix(self.path.suffix + ".previous")
        self.history_limit = max(2, min(64, int(history_limit)))
        self._lock = threading.RLock()

    @staticmethod
    def _empty():
        return {"store_schema_version": 1, "revision": 0, "active_version": None, "versions": []}

    def _read(self, path=None):
        path = path or self.path
        if not path.exists():
            return self._empty()
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise LearningStoreError("Learning store exceeds its size limit")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Root must be an object")
            if "store_schema_version" not in payload:
                model = _validate_record(payload)
                # Read-only import. First committed update writes a versioned envelope.
                return {"store_schema_version": 1, "revision": model.model_version,
                        "active_version": model.model_version, "versions": [
                            self._entry(model, "active", "legacy_import", None)]}
            if payload["store_schema_version"] != 1 or not isinstance(payload.get("versions"), list):
                raise ValueError("Unsupported store schema")
            if len(payload["versions"]) > 64 or not isinstance(payload.get("revision"), int):
                raise ValueError("Invalid version history")
            seen = set()
            for entry in payload["versions"]:
                if not isinstance(entry, dict) or entry.get("digest") != _digest(entry.get("model")):
                    raise ValueError("Model snapshot digest mismatch")
                model = _validate_record(entry["model"])
                if entry.get("version") != model.model_version or model.model_version in seen or model.model_version > payload["revision"]:
                    raise ValueError("Invalid model version identity")
                if entry.get("role") not in {"active", "shadow"}:
                    raise ValueError("Invalid model role")
                seen.add(model.model_version)
            active = payload.get("active_version")
            if active is not None and not any(item["version"] == active and item["role"] == "active" for item in payload["versions"]):
                raise ValueError("Active snapshot is unavailable")
            return payload
        except LearningStoreError:
            raise
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise LearningStoreError("Learning state is unreadable or inconsistent; original file preserved") from exc

    @staticmethod
    def _entry(model, role, reason, parent_version, **metadata):
        record = model.to_record()
        _validate_record(record)
        return {"version": model.model_version, "role": role, "parent_version": parent_version,
                "created_at": datetime.now(timezone.utc).isoformat(), "reason": sanitize_text(reason)[:500],
                "model": record, "digest": _digest(record), **metadata}

    @staticmethod
    def _active(payload):
        return next((item for item in payload["versions"] if item["version"] == payload["active_version"]), None)

    def load(self) -> OnlineAnomalyModel | None:
        with self._lock:
            active = self._active(self._read())
            return _validate_record(active["model"]) if active else None

    def load_version(self, version: int) -> OnlineAnomalyModel:
        with self._lock:
            for entry in self._read()["versions"]:
                if entry["version"] == version:
                    return _validate_record(entry["model"])
        raise KeyError(version)

    def history(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple({key: value for key, value in entry.items() if key != "model"}
                         for entry in self._read()["versions"])

    def _commit(self, payload, model, *, role="active", reason="trusted_observation", **metadata):
        previous = json.loads(json.dumps(payload))
        parent = payload["active_version"]
        model = _validate_record(model.to_record())
        model.model_version = payload["revision"] + 1
        entry = self._entry(model, role, reason, parent, **metadata)
        payload["revision"] = model.model_version
        payload["versions"].append(entry)
        if role == "active":
            payload["active_version"] = model.model_version
        keep = {payload["active_version"], model.model_version}
        remaining = [entry for entry in payload["versions"] if entry["version"] not in keep]
        preserved = [entry for entry in payload["versions"] if entry["version"] in keep]
        slots = max(0, self.history_limit - len(preserved))
        payload["versions"] = sorted(preserved + (remaining[-slots:] if slots else []), key=lambda item: item["version"])
        if previous["versions"]:
            write_json(self.previous_path, previous)
        write_json(self.path, payload)
        return model

    def update(self, updater, *, factory=OnlineAnomalyModel) -> OnlineAnomalyModel:
        """Reload and mutate under a process lock so accepted samples are not lost."""
        with self._lock, locked_state(self.path):
            payload = self._read()
            active = self._active(payload)
            model = _validate_record(active["model"]) if active else factory()
            updater(model)
            return self._commit(payload, model)

    def save(self, model: OnlineAnomalyModel, *, expected_version: int | None = None) -> None:
        with self._lock, locked_state(self.path):
            payload = self._read()
            active = self._active(payload)
            expected = model.model_version if expected_version is None else expected_version
            if active and (active["version"] != expected or active["model"]["model_id"] != model.model_id):
                raise LearningConflictError("Model changed in another instance; reload before saving")
            committed = self._commit(payload, model)
            model.model_version = committed.model_version

    def stage_shadow(self, model: OnlineAnomalyModel, *, expected_active_version: int, reason: str) -> int:
        with self._lock, locked_state(self.path):
            payload = self._read()
            if payload["active_version"] != expected_active_version:
                raise LearningConflictError("Active model changed before shadow staging")
            return self._commit(payload, _validate_record(model.to_record()), role="shadow", reason=reason).model_version

    def evaluate_shadow(self, version: int, samples: tuple[tuple[AegisFeatureVector, bool], ...], *, expected_active_version: int) -> dict:
        """Evaluate independently labelled holdout samples; persist aggregate evidence only.

        The reviewer is responsible for independent, representative labels. This
        evaluates the submitted set; it cannot establish real-world calibration.
        """
        if not 20 <= len(samples) <= 10000:
            raise ValueError("Evaluation requires 20 to 10000 labelled holdout samples")
        with self._lock, locked_state(self.path):
            payload = self._read()
            if payload["active_version"] != expected_active_version:
                raise LearningConflictError("Active model changed before evaluation")
            entry = next((item for item in payload["versions"] if item["version"] == version and item["role"] == "shadow"), None)
            if entry is None:
                raise KeyError(version)
            active = self._active(payload)
            candidate = _validate_record(entry["model"])
            baseline = _validate_record(active["model"])
            if not candidate.ready or not baseline.ready:
                raise LearningStoreError("Both models need enough trusted training samples before comparison")
            counts = {"benign_samples": 0, "anomalous_samples": 0,
                      "candidate_false_positives": 0, "candidate_true_positives": 0,
                      "active_false_positives": 0, "active_true_positives": 0}
            dataset = hashlib.sha256()
            for features, anomalous in samples:
                features.validate()
                if not isinstance(anomalous, bool):
                    raise ValueError("Holdout labels must be booleans")
                dataset.update(_digest({"numeric": features.numeric, "identities": features.identity_tokens, "anomalous": anomalous}).encode())
                counts["anomalous_samples" if anomalous else "benign_samples"] += 1
                for name, model in (("candidate", candidate), ("active", baseline)):
                    if model.assess(features).anomaly_score >= 0.5:
                        counts[name + ("_true_positives" if anomalous else "_false_positives")] += 1
            if min(counts["benign_samples"], counts["anomalous_samples"]) < 10:
                raise ValueError("Evaluation requires at least ten samples of each label")
            candidate_fpr = counts["candidate_false_positives"] / counts["benign_samples"]
            candidate_recall = counts["candidate_true_positives"] / counts["anomalous_samples"]
            active_fpr = counts["active_false_positives"] / counts["benign_samples"]
            active_recall = counts["active_true_positives"] / counts["anomalous_samples"]
            evidence = {"candidate_digest": entry["digest"], "active_version": expected_active_version,
                        "active_digest": active["digest"], "dataset_digest": dataset.hexdigest(),
                        "evaluated_at": datetime.now(timezone.utc).isoformat(), "decision_threshold": 0.5,
                        **counts, "candidate_false_positive_rate": candidate_fpr, "candidate_recall": candidate_recall,
                        "active_false_positive_rate": active_fpr, "active_recall": active_recall,
                        "passed": candidate_fpr <= 0.10 and candidate_recall >= 0.80
                                  and candidate_fpr <= active_fpr + 0.05 and candidate_recall >= active_recall - 0.05}
            entry["evaluation"] = evidence
            # Evaluation is metadata for an immutable model version, not training.
            write_json(self.path, payload)
            return dict(evidence)

    def promote(self, version: int, *, expected_active_version: int, evidence: dict, reviewed_by: str, reason: str) -> OnlineAnomalyModel:
        with self._lock, locked_state(self.path):
            payload = self._read()
            if payload["active_version"] != expected_active_version:
                raise LearningConflictError("Active model changed after evaluation")
            entry = next((item for item in payload["versions"] if item["version"] == version and item["role"] == "shadow"), None)
            if entry is None:
                raise KeyError(version)
            recorded = entry.get("evaluation")
            active = self._active(payload)
            if (not reviewed_by.strip() or not reason.strip() or not isinstance(recorded, dict)
                    or recorded != evidence or recorded.get("candidate_digest") != entry["digest"]
                    or recorded.get("active_digest") != active["digest"]
                    or recorded.get("active_version") != expected_active_version or recorded.get("passed") is not True):
                raise LearningStoreError("Promotion requires recorded, reviewed, digest-bound held-out evaluation")
            model = _validate_record(entry["model"])
            if not model.ready:
                raise LearningStoreError("A warming model cannot be promoted")
            return self._commit(payload, model, reason=reason, promoted_from=version,
                                reviewed_by=sanitize_text(reviewed_by)[:100], evaluation=recorded)

    def rollback(self, version: int, *, expected_active_version: int, reason: str) -> OnlineAnomalyModel:
        if not reason.strip():
            raise ValueError("Rollback needs a reason")
        with self._lock, locked_state(self.path):
            payload = self._read()
            if payload["active_version"] != expected_active_version:
                raise LearningConflictError("Active model changed before rollback")
            entry = next((item for item in payload["versions"] if item["version"] == version and item["role"] == "active"), None)
            if entry is None:
                raise KeyError(version)
            return self._commit(payload, _validate_record(entry["model"]), reason=reason, restored_from=version)

    def recover_previous(self, *, expected_file_digest: str, reason: str) -> OnlineAnomalyModel:
        """Explicit recovery keeps a separate copy of the unreadable current file."""
        if not reason.strip():
            raise ValueError("Recovery needs a reason")
        with self._lock, locked_state(self.path):
            raw = self.path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_file_digest:
                raise LearningConflictError("Learning file changed before recovery")
            payload = self._read(self.previous_path)
            active = self._active(payload)
            if not active:
                raise LearningStoreError("No previous snapshot is recoverable")
            # Use a content-addressed recovery artifact, never overwrite the evidence.
            backup = self.path.with_suffix(self.path.suffix + ".corrupt-" + expected_file_digest[:16])
            if not backup.exists():
                backup.write_bytes(raw)
            return self._commit(payload, _validate_record(active["model"]), reason=reason, recovered_previous=True)
