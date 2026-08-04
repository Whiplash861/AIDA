
from pathlib import Path
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_intelligence import ThreatIntelligenceBuilder, render_threat_report

def test_attribution_stays_conservative():
    detection=ProviderDetection(detection_id="1",name="Trojan:Win32/Test",severity=SecuritySeverity.HIGH,source="Defender",file_path=Path(r"C:\bad.exe"),metadata={"network_endpoints":["198.51.100.42:443"],"endpoint_regions":{"198.51.100.42:443":"Germany"}})
    report=ThreatIntelligenceBuilder().build(detection)
    assert report.threat_actor.startswith("Unknown")
    assert report.actor_location=="Unknown"
    text=render_threat_report(report)
    assert "Observed network endpoints" in text
    assert "Physical actor location: Unknown" in text
