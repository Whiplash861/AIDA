"""AIDA-owned, deterministic investigations over explicitly read-only Engine calls."""
from __future__ import annotations

from threading import Event, RLock
from typing import Callable
from uuid import uuid4

from aida.engines.base import EngineDescriptor, EngineRequest, EngineResponse
from aida.engines.coordinator import EngineCoordinator


class ReadOnlyEngineAdapter:
    def __init__(self, key: str, reader: Callable[[], str]):
        self.descriptor = EngineDescriptor(key, key.title(), "", "Read-only investigation evidence")
        self.reader = reader

    def handle(self, request: EngineRequest) -> EngineResponse:
        if request.intent != "inspect":
            raise ValueError("This investigation adapter only supports inspection")
        return EngineResponse(self.descriptor.key, self.reader())


class InvestigationRunner:
    """Persist progress; only incomplete read-only checks may run on resumption.

    Objective text is an evidence label. It cannot select executable code, a
    command, a mutation, or permission. All readers are bound by application code.
    """
    def __init__(self, service, memory, readers: dict[str, Callable[[], str]]):
        self.service, self.memory = service, memory
        self.coordinator = EngineCoordinator()
        self.readers = dict(readers)
        self._lock = RLock()
        for key, reader in self.readers.items():
            self.coordinator.register(ReadOnlyEngineAdapter(key, reader))

    def run(self, objective: str = "", *, case_id: str | None = None,
            cancelled: Event | None = None):
        cancelled = cancelled or Event()
        with self._lock:
            if case_id:
                case = self.service.get_case(case_id)
                if case is None:
                    raise KeyError("Investigation was not found")
                if case.authority != "local-evidence":
                    raise ValueError("Imported cases are reference-only. Start a local investigation to collect local evidence.")
                if case.source_kind != "aida.investigation":
                    raise ValueError("This case belongs to its original security workflow. Start a new general investigation or review its response plan.")
            else:
                if not objective.strip() or len(objective) > 1000:
                    raise ValueError("Supply an investigation objective of 1–1000 characters")
                case = self.service.create_case(objective, objective=objective, source_kind="aida.investigation")
            history = self.service.timeline(case.case_id)
            run_id = uuid4().hex
            completed = {entry.data.get("engine_key") for entry in history
                         if entry.kind == "engine_observation" and entry.status == "observed"}
            if completed.issuperset({"memory", *self.readers}) and case.status in {"review_required", "reviewed", "completed"}:
                return case
            if cancelled.is_set():
                return self.service.set_phase(case.case_id, "paused", summary="Paused before collecting evidence.")
            failed = False
            if "memory" not in completed:
                try:
                    prior = self.memory.retrieve_context(case.title, limit=5)
                    memory_text = "\n".join(f"{item.memory_id}: {item.summary}" for item in prior) or "No relevant eligible memories were retrieved."
                    self.service.add_evidence(case.case_id, "engine_observation", _excerpt(memory_text),
                        "memory:" + run_id, data={"engine_key": "memory", "memory_ids": [item.memory_id for item in prior]})
                except Exception as exc:
                    failed = True
                    self.service.add_evidence(case.case_id, "engine_observation",
                        f"Memory retrieval unavailable ({type(exc).__name__}); prior outcomes could not be checked.",
                        "memory:" + run_id, status="unavailable", data={"engine_key": "memory"})
            self.service.set_phase(case.case_id, "collecting", summary="Collecting bounded read-only Engine evidence.")
            for key in self.readers:
                if key in completed:
                    continue
                if cancelled.is_set():
                    self.service.set_phase(case.case_id, "paused", summary="Investigation paused; incomplete read-only checks can be resumed.")
                    return self.service.get_case(case.case_id)
                self.service.add_evidence(case.case_id, "check_started", f"Reading {key} evidence.", key,
                                          status="started", data={"engine_key": key})
                try:
                    response = self.coordinator.execute(key, EngineRequest("inspect", source_engine="aida"), temporary=True)
                    text = _excerpt(response.text)
                    self.service.add_evidence(case.case_id, "engine_observation", text, key + ":" + run_id,
                                              data={"engine_key": key, "evidence_kind": "reported_engine_observation"})
                except Exception as exc:
                    failed = True
                    self.service.add_evidence(case.case_id, "engine_observation",
                        f"{key} evidence is unavailable ({type(exc).__name__}). This check does not establish a clean result.",
                        key + ":" + run_id, status="unavailable", data={"engine_key": key})
            phase = "paused" if cancelled.is_set() else "failed" if failed else "review_required"
            summary = ("Read-only evidence collected; review the timeline before selecting a response. "
                       "No repair or security response has been executed; the cause remains unverified.")
            self.service.set_phase(case.case_id, phase, summary=summary)
            try:
                self.memory.remember_investigation(case_id=case.case_id, title=case.title,
                    summary=summary, observation_id=case.case_id, outcome=phase)
            except Exception as exc:
                self.service.add_evidence(case.case_id, "memory_retention",
                    f"The case remains saved, but Memory linking is unavailable ({type(exc).__name__}).",
                    "memory-retention:" + run_id, status="unavailable")
            return self.service.get_case(case.case_id)


def _excerpt(text: str) -> str:
    return text if len(text) <= 3900 else text[:3900] + "\n[Evidence excerpt truncated; review the original Engine or Memory record.]"
