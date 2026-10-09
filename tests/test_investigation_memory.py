from datetime import timedelta

import pytest

from aida.memory.models import MemoryStatus, utc_now
from aida.memory.service import MemoryService


def test_ranked_retrieval_uses_relevance_and_excludes_ineligible(tmp_path):
    memory = MemoryService(tmp_path / "memory.db", user_id="owner", device_id="pc")
    relevant = memory.add_memory(category="history", title="Outlook freezing", summary="Memory pressure observed")
    memory.add_memory(category="history", title="New observation", summary="Outlook appeared once", pinned=True)
    memory.add_memory(category="history", title="Outlook freezing repeatedly", summary="Disputed", status=MemoryStatus.DISPUTED)
    memory.add_memory(category="history", title="Outlook freezing repeatedly", summary="Expired", expires_at=utc_now()-timedelta(days=1))
    results = memory.retrieve_context("What did we try for Outlook freezing?")
    assert results[0].memory_id == relevant.memory_id
    assert len(results) == 2


def test_context_links_are_scoped_and_purged(tmp_path):
    memory = MemoryService(tmp_path / "memory.db", user_id="owner", device_id="pc")
    item = memory.remember_investigation(case_id="CASE-A", title="Check", summary="CPU fell after restart",
        entity_key="app:v1", observation_id="OBS-A", action_id="ACT-A", outcome="improvement_observed")
    assert not item.facts["causal_success_verified"]
    assert memory.retrieve_context("unrelated words", case_id="CASE-A") == [item]
    assert memory.retrieve_context("", entity_key="app:v2") == []
    other = MemoryService(memory.database, user_id="other", device_id="pc")
    assert other.retrieve_context("", case_id="CASE-A") == []
    with pytest.raises(KeyError):
        other.link_context(item.memory_id, case_id="CASE-B")
    memory.purge(item.memory_id)
    with memory.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_context_links").fetchone()[0] == 0


def test_explicit_supersession_retains_history(tmp_path):
    memory = MemoryService(tmp_path / "memory.db")
    old = memory.add_memory(category="history", title="Cause", summary="Earlier conclusion")
    new = memory.add_memory(category="history", title="Cause", summary="Later evidence")
    memory.supersede_memory(old.memory_id, replacement_id=new.memory_id, reason="New evidence contradicts it")
    assert [item.memory_id for item in memory.retrieve_context("Cause")] == [new.memory_id]
    assert memory.get_memory(old.memory_id).facts["superseded_by"] == new.memory_id
    assert len(memory.list_revisions(old.memory_id)) == 2


def test_search_wildcards_are_literal(tmp_path):
    memory = MemoryService(tmp_path / "memory.db")
    memory.add_memory(category="history", title="Elsewhere", summary="Unrelated")
    assert memory.search("xyz_") == []
