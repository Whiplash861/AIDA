from pathlib import Path

from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_analysis import (
    LocalThreatAnalyzer,
    SignatureState,
    ThreatAnalysisService,
    ThreatAssessmentLevel,
)


def _memory(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    return database, MemoryService(database, user_id="Austin", device_id="Test-PC")


def test_read_only_analysis_detects_disguised_pe_and_persists_snapshot(tmp_path):
    target = tmp_path / "invoice.txt"
    target.write_bytes(b"MZ" + b"\0" * 64)
    analyzer = LocalThreatAnalyzer(
        signature_inspector=lambda path: {"status": "NotSigned"},
        process_iterator=lambda: (),
    )
    database, memory = _memory(tmp_path)
    service = ThreatAnalysisService(database, memory, analyzer=analyzer)

    record = service.analyze(target, source="test")

    assert record.identity.detected_type == "Windows PE executable"
    assert record.identity.signature_state is SignatureState.NOT_SIGNED
    assert any(item.code == "extension_header_mismatch" for item in record.indicators)
    assert record.assessment in {
        ThreatAssessmentLevel.SUSPICIOUS,
        ThreatAssessmentLevel.LIKELY_MALICIOUS,
    }
    assert service.get(record.analysis_id) == record
    assert service.latest_for_path(target).analysis_id == record.analysis_id


def test_provider_confirmed_active_detection_remains_separate_from_local_confidence(tmp_path):
    target = tmp_path / "sample.exe"
    target.write_bytes(b"MZ" + b"\0" * 64)
    detection = ProviderDetection(
        detection_id="d-1",
        name="Trojan:Win32/Test",
        severity=SecuritySeverity.HIGH,
        source="Microsoft Defender Antivirus",
        file_path=target,
        metadata={"is_active": True, "threat_id": "42"},
    )
    analyzer = LocalThreatAnalyzer(
        signature_inspector=lambda path: {"status": "Valid", "subject": "CN=Test"},
        process_iterator=lambda: (),
    )

    record = analyzer.analyze(target, detection=detection)

    assert record.assessment is ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS
    assert record.provider_severity is SecuritySeverity.HIGH
    assert record.confidence >= 0.9
    assert record.identity.signer_subject == "CN=Test"
