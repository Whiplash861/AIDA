
from aida.security.windows.defender_cancel import DefenderCancellationService, DefenderCancelableScan

class Runner:
    def __init__(self, payloads):
        self.payloads=list(payloads); self.scripts=[]
    def run_json(self,script,timeout=15):
        self.scripts.append(script)
        return self.payloads.pop(0)

def test_active_scan_and_provider_confirmed_cancel():
    runner=Runner([
        {"ScanId":"{1}","Mode":"full","StartTime":"2026-01-01T00:00:00Z","Parameters":"Full Scan"},
        {"Requested":True,"ExitCode":0},
        {"State":"CANCELLED"},
    ])
    service=DefenderCancellationService(runner,sleep=lambda _:None)
    active=service.active_cancelable_scan()
    assert active.mode is DefenderCancelableScan.FULL
    result=service.request_cancel(active,confirmation_timeout_seconds=1,poll_interval_seconds=.1)
    assert result.requested and result.confirmed
    assert "-Scan -Cancel" in runner.scripts[1]
