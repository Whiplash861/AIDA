from aida.assistance.models import (
    AssistanceRisk,
    AssistanceTaskKind,
    AssistanceTaskState,
)
from aida.assistance.store import AssistanceTaskStore
from aida.memory.database import MemoryDatabase


def test_task_center_persists_transitions_and_cooperative_cancel(tmp_path):
    store = AssistanceTaskStore(
        MemoryDatabase(tmp_path / "tasks.db"),
        user_id="Austin",
        device_id="Test-PC",
    )
    task = store.create(
        kind=AssistanceTaskKind.THREAT_ANALYSIS,
        title="Analyze sample",
        state=AssistanceTaskState.RUNNING,
        risk=AssistanceRisk.INFORMATIONAL,
        target="C:/sample.exe",
    )

    cancelled = store.request_cancel(task.task_id)

    assert cancelled.state is AssistanceTaskState.CANCELLATION_REQUESTED
    assert store.cancellation_requested(task.task_id) is True
    terminal = store.transition(task.task_id, AssistanceTaskState.CANCELLED)
    assert terminal.state.terminal is True


def test_startup_reconciliation_marks_nonterminal_tasks_interrupted(tmp_path):
    store = AssistanceTaskStore(
        MemoryDatabase(tmp_path / "startup.db"),
        user_id="Austin",
        device_id="Test-PC",
    )
    task = store.create(
        kind=AssistanceTaskKind.EVIDENCE_LOCATION,
        title="Locate evidence",
        state=AssistanceTaskState.RUNNING,
    )

    assert store.mark_startup_interrupted() == 1
    assert store.get(task.task_id).state is AssistanceTaskState.INTERRUPTED
