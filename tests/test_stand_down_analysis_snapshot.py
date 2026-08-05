from dataclasses import dataclass

from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.stand_down import StandDownService, StandDownStatus


@dataclass
class Identity:
    signer_subject: str
    publisher: str
    signer_thumbprint: str
    file_version: str
    detected_type: str = "Windows PE executable"
    signature_state: str = "valid"


def test_stand_down_captures_analysis_identity_and_suspends_on_signer_change(tmp_path):
    target = tmp_path / "trusted.exe"
    target.write_bytes(b"trusted")
    current = Identity("CN=Vendor", "Vendor", "AAA", "1.0")
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(database, user_id="Austin", device_id="Test-PC")
    service = StandDownService(
        database,
        memory,
        identity_inspector=lambda path: current,
    )

    record = service.create(target, reason="User accepts this build", authorized_by="Austin")
    assert record.signer_thumbprint == "AAA"
    assert record.analysis_snapshot["detected_type"] == "Windows PE executable"
    assert service.evaluate(target).suppress_aida_recommendation is True

    current.signer_thumbprint = "BBB"
    evaluation = service.evaluate(target)
    assert evaluation.status is StandDownStatus.SUSPENDED
    assert evaluation.suppress_aida_recommendation is False
    assert "thumbprint" in evaluation.reason
