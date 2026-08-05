from aida.autonomy.observation import SecurityObservation, _evidence_lines


def test_observation_includes_read_only_threat_analysis_without_action():
    observation = SecurityObservation(
        provider_name="Microsoft Defender Antivirus",
        provider_active=True,
        provider_healthy=True,
        real_time_protection=True,
        signatures_current=True,
        active_scan_description=None,
        detections=(),
        active_stand_down_count=0,
        threat_analysis_summaries=(
            "sample.exe: suspicious at 72% confidence; operational action executed: no",
        ),
    )

    evidence = _evidence_lines(observation)

    assert "Read-only threat-analysis snapshots:" in evidence
    assert any("sample.exe: suspicious" in line for line in evidence)
